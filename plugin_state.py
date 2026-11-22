# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Lettori di nomi/preset dallo stato salvato. Nessun plugin viene eseguito."""
import plistlib
import re
import json
import xml.etree.ElementTree as ET


def fourcc(value):
    if isinstance(value, int) and 0 <= value <= 0xffffffff:
        return value.to_bytes(4, 'big').decode('ascii', errors='replace')
    return value if isinstance(value, str) and len(value) == 4 else None


def embedded_au_states(data):
    """Legge tutti i plist XML, conservando offset e identità AU per l'associazione."""
    for match in re.finditer(rb'<\?xml\b[^>]*\?>\s*(?:<!DOCTYPE[^>]*>\s*)?<plist\b', data):
        end = data.find(b'</plist>', match.start())
        if end < 0:
            continue
        try:
            state = plistlib.loads(data[match.start():end + 8])
        except (ValueError, plistlib.InvalidFileException, ET.ParseError):
            continue
        if isinstance(state, dict) and all(k in state for k in ('type', 'subtype', 'manufacturer')):
            yield match.start(), state


def xml_state(value):
    if not isinstance(value, (bytes, str)):
        return None
    if isinstance(value, bytes) and value.startswith(b'VC2!') and len(value) >= 8:
        length = int.from_bytes(value[4:8], 'little')
        if not 0 < length <= len(value) - 8:
            return None
        value = value[8:8 + length]
    value = value.rstrip(b'\0 \r\n\t') if isinstance(value, bytes) else value.rstrip('\0 \r\n\t')
    try:
        return ET.fromstring(value)
    except (ET.ParseError, ValueError):
        return None


def zstd_state(value):
    """Opzionale: libzstd già installata. Dimensione esplicita e limite di 16 MiB."""
    if not isinstance(value, bytes) or not value.startswith(b'\x28\xb5\x2f\xfd'):
        return None
    import ctypes
    from ctypes.util import find_library
    from pathlib import Path
    candidates = [str(Path(__file__).resolve().parent / 'Native' / 'libzstd.dylib'),
                  '/opt/homebrew/lib/libzstd.dylib', '/usr/local/lib/libzstd.dylib']
    candidates += [find_library('zstd')]
    for candidate in candidates:
        if not candidate or ('/' in candidate and not Path(candidate).exists()):
            continue
        try:
            lib = ctypes.CDLL(candidate)
            lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
            size = lib.ZSTD_getFrameContentSize(value, len(value))
            if not 0 < size <= 16 * 1024 * 1024:
                return None
            target = ctypes.create_string_buffer(size)
            lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
            lib.ZSTD_decompress.restype = ctypes.c_size_t
            count = lib.ZSTD_decompress(target, size, value, len(value))
            if count != size:
                return None
            return json.loads(target.raw.decode('utf-8'))
        except (OSError, AttributeError, ValueError, UnicodeError):
            continue
    return None


def arturia_title(value):
    """Header Boost osservato: stringa con lunghezza in byte, senza euristiche sui nomi."""
    if not isinstance(value, bytes):
        return None
    match = re.match(rb'22 serialization::archive 10 0 7 0 7 (\d+) ', value)
    if not match:
        return None
    length = int(match[1])
    if not 0 < length <= 4096:
        return None
    end = match.end() + length
    if end >= len(value) or not re.match(rb' \d+ ', value[end:]):
        return None
    try:
        return value[match.end():end].decode('utf-8')
    except UnicodeDecodeError:
        return None


def preset_details(state, manufacturer, subtype):
    """Il campo AU generico 'name=Untitled' non sostituisce mai il preset interno."""
    presets = []

    def add(name, source, role='Preset', modified=None):
        if isinstance(name, str) and name.strip():
            presets.append({'name': name.strip(), 'source': source, 'role': role,
                            'modified': modified, 'status': 'letto dallo stato salvato'})

    if manufacturer == 'Artu':
        add(arturia_title(state.get('Controller State')), 'Controller State / header Boost Arturia')
    elif manufacturer == 'Ikmm' and subtype == 'Hamm':
        root = xml_state(state.get('jucePluginState'))
        if root is not None:
            for current in root.findall('./CurrentPreset'):
                filename = current.get('FileName')
                if filename:
                    # Preserva il nome originale nel campo sorgente e segnala Dirty.
                    name = filename.replace('\\', '/').rsplit('/', 1)[-1]
                    name = re.sub(r'\.b3xp$', '', name, flags=re.I)
                    dirty = current.get('Dirty')
                    add(name, 'jucePluginState / CurrentPreset.FileName',
                        modified=True if dirty == '1' else False if dirty == '0' else None)
    elif manufacturer == 'GOSW' and subtype == 'Ambr':
        root = xml_state(state.get('data0'))
        if root is not None and root.tag == 'SynthMaster':
            entry = root.find('./ENTRYDESCR')
            if entry is not None:
                add(entry.get('name'), 'data0 / SynthMaster.ENTRYDESCR', 'Multi')
            for index, part in enumerate(root.findall('./SynthSubEngine'), 1):
                entry = part.find('./SynthEngine/SYNTHENG/ENTRYDESCR')
                if entry is not None:
                    add(entry.get('name'), f'data0 / SynthSubEngine[{index}]/SYNTHENG.ENTRYDESCR',
                        f'Parte {index}')
    elif manufacturer == 'Sopr':
        root = xml_state(state.get('SEPRESET'))
        if root is not None and root.tag == 'Preset':
            add(root.get('name'), 'SEPRESET / Preset.name')
    elif (manufacturer, subtype) in [('AdTy', 'Er7e'), ('oDin', 'sMas')]:
        root = xml_state(state.get('jucePluginState'))
        expected = 'Echoes_Preset' if manufacturer == 'AdTy' else 'ValhallaSupermassive'
        if root is not None and root.tag == expected:
            add(root.get('presetName'), 'jucePluginState / ' + expected + '.presetName')
    elif manufacturer == 'VSLS' and subtype == 'VIN0':
        decoded = zstd_state(state.get('PluginState'))
        if isinstance(decoded, dict) and isinstance(decoded.get('data'), dict):
            current = decoded['data'].get('currentPreset')
            if isinstance(current, str) and current:
                add(current, 'PluginState (Zstandard) / data.currentPreset')
    elif manufacturer == 'Ymau':
        value = state.get('jucePluginState')
        if isinstance(value, bytes) and b'CMAI' in value[:100]:
            offset = value.find(b'DPFM', 0, 128)
            if offset >= 0 and offset + 32 <= len(value):
                size = int.from_bytes(value[offset + 4:offset + 8], 'little')
                if 24 <= size <= len(value) - offset - 8 and value[offset + 8:offset + 12] == b'\0\0\0\x15':
                    title = value[offset + 12:offset + 32].split(b'\0', 1)[0]
                    if title and all(32 <= byte <= 126 for byte in title):
                        add(title.decode('ascii'), 'jucePluginState / blocco Yamaha DPFM (formato osservato)', 'Performance')

    status = 'letto dallo stato salvato' if presets else 'non ricavabile dal formato supportato'
    # I nomi dello stato AU sono metadati separati, anche quando non sono Untitled.
    return {'presets': presets, 'preset_status': status,
            'au_preset_name': state.get('name') if isinstance(state.get('name'), str) else None}


def enrich_records(data, records, registry):
    """Associa lo stato a un'istanza solo se offset e tripla AU coincidono."""
    records = [dict(record) for record in records]
    for offset, state in embedded_au_states(data):
        identity = tuple(fourcc(state[k]) for k in ('type', 'subtype', 'manufacturer'))
        if not all(identity):
            continue
        eligible = [(i, r) for i, r in enumerate(records)
                    if r['offset'] < offset and tuple(r.get(k) for k in ('type', 'subtype', 'manufacturer')) == identity]
        # Un plist deve appartenere al record che lo precede, non attraversare altri slot.
        preceding = max((r['offset'] for r in records if r['offset'] < offset), default=-1)
        eligible = [(i, r) for i, r in eligible if r['offset'] == preceding and 'state_offset' not in r]
        if eligible:
            index, record = eligible[0]
        else:
            # Non creare una seconda istanza quando l'associazione è ambigua.
            continue
        full = registry.get(identity)
        if full:
            record['name'] = full
            record['name_status'] = 'identificativo AU risolto nel registro locale'
        record.update(preset_details(state, identity[2], identity[1]))
        record['state_offset'] = offset
        record['state_identity'] = dict(zip(('type', 'subtype', 'manufacturer'), identity))
        records[index] = record
    for record in records:
        if 'GAME' in record['source'] and record['offset'] >= 106:
            # Campo di 64 byte osservato nei record nativi; non equivale allo
            # stato attuale e #default non prova che i parametri siano predefiniti.
            field = data[record['offset'] - 106:record['offset'] - 42]
            filename = field.split(b'\0', 1)[0]
            if filename.endswith(b'.pst') and all(32 <= byte <= 126 for byte in filename):
                record['setting_file'] = filename.decode('ascii')
                if filename != b'#default.pst':
                    record['setting_name'] = filename[:-4].decode('ascii')
                    record['setting_source'] = 'nome impostazione .pst nel campo del record nativo osservato'
        record.setdefault('presets', [])
        record.setdefault('preset_status', 'non ricavabile dal formato supportato')
        record.setdefault('name_status', 'nome nativo noto' if 'GAME' in record['source']
                          else 'nome da registro locale' if (record.get('type'), record.get('subtype'), record.get('manufacturer')) in registry
                          else 'abbreviazione salvata, non verificata')
        record['display_label'] = record['name']
        if record['presets']:
            record['display_label'] += ' — ' + '; '.join(
                f"{p['role']}: {p['name']}" + (' (modificato)' if p['modified'] is True else '')
                for p in record['presets'])
        else:
            record['display_label'] += (' — impostazione salvata: ' + record['setting_name']
                                        if record.get('setting_name') else ' — preset non disponibile')
    return records


def saved_bypass(data, record):
    """Flag di slot nel formato CST 6.14 osservato e confrontato con MainStage.

    AU: il nome breve di 12 byte precede la tripla 4CC. Nativi: offset punta
    già al nome. Il byte bypass è otto byte prima del nome, distinto dal layer.
    Formati o header non riconosciuti restituiscono None.
    """
    if data[:8] != b'OCuA\x06\x00\x0e\x00':
        return None
    offset = record.get('offset', -1) - (12 if record.get('type') else 0)
    if offset < 8 or offset + 12 > len(data):
        return None
    if data[offset - 2:offset] not in (b'\0\2', b'\2\2', b'\0\0', b'\0\1'):
        return None
    short = data[offset:offset + 12].split(b'\0', 1)[0]
    if not short or not all(32 <= c <= 126 for c in short):
        return None
    flag = data[offset - 8]
    return bool(flag) if flag in (0, 1) else None
