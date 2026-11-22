#!/usr/bin/env python3
# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""MainStage Concert Inspector
Uso:  python3 mainstage_inspector.py [Concerto.concert] [--cli | --diag]
Solo libreria standard.

Struttura MainStage:  Concert.patch/ (cartelle .patch annidate = Set > Patch)
  data.plist  -> parametri del patch (channels, nodes, ...)
  *.cst       -> channel strip (plugin)
  workspace.layout/setupZ.layout -> hardware / controller
"""
import os, re, sys, json, plistlib, zlib, bz2, lzma

NAME_KEYS = ("name", "Name", "patchName", "title", "displayName", "pluginName", "deviceName", "AUName")
AU_KEYS   = {"manufacturer", "componentManufacturer", "componentSubType", "subtype", "componentType", "AUType"}
PLUGIN_CLS = re.compile(r"AudioUnit|AUPlug|Plug-?in|AUInstrument|AUEffect|InsertSlot", re.I)
CTRL_CLS   = re.compile(r"Controller|MIDIDevice|HardwareDevice|ControlSurface|ScreenControl|MIDIInput", re.I)
CTRL_KEY   = re.compile(r"midi|controller|hardware|mapping|screencontrol|assign", re.I)
ORDER_PREFIX = re.compile(r"^\d+__#\$!@%!#__")
MARKERS = (b"bplist00", b"<?xml", b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x1f\x8b")


VERSION = "v1.0.0"

# ---------------------------- lettura plist ----------------------------
def decode_keyed_archive(pl):
    objs, cache, busy = pl["$objects"], {}, set()
    if not isinstance(objs, list):
        raise ValueError("$objects deve essere una lista")
    def res(v):
        if isinstance(v, plistlib.UID): return dec(v.data)
        if isinstance(v, list): return [res(x) for x in v]
        if isinstance(v, dict): return {k: res(x) for k, x in v.items()}
        return v
    def dec(i):
        if not isinstance(i, int) or not 0 <= i < len(objs):
            raise ValueError(f"Riferimento NSKeyedArchiver non valido: {i}")
        if i in cache: return cache[i]
        if i in busy: return f"<ref {i}>"
        o = objs[i]
        if o == "$null": return None
        if not isinstance(o, dict):
            busy.add(i)
            out = res(o)
            busy.discard(i); cache[i] = out
            return out
        busy.add(i); cls = ""
        if isinstance(o.get("$class"), plistlib.UID):
            cls_obj = dec(o["$class"].data)
            cls = cls_obj.get("$classname", "") if isinstance(cls_obj, dict) else ""
        if "NS.keys" in o and "NS.objects" in o:
            if len(o["NS.keys"]) != len(o["NS.objects"]):
                raise ValueError("Dizionario archiviato con chiavi e valori di lunghezza diversa")
            out = {str(res(k)): res(v) for k, v in zip(o["NS.keys"], o["NS.objects"])}
        elif "NS.objects" in o: out = res(o["NS.objects"])
        elif "NS.string" in o: out = o["NS.string"]
        else:
            out = {k: res(v) for k, v in o.items() if k != "$class"}
            if cls: out["_class"] = cls
        busy.discard(i); cache[i] = out
        return out
    return {k: res(v) for k, v in pl.get("$top", {}).items()}

_DECOMP = [lambda x: x, lambda x: zlib.decompress(x, 47), lambda x: zlib.decompress(x, -15),
           bz2.decompress, lzma.decompress]

def _try(b):
    for off in (0, 4, 8, 12, 16):
        for fn in _DECOMP:
            try: return plistlib.loads(fn(b[off:]))
            except Exception: pass
    return None

def parse_plist_bytes(b, deep=False):
    """Prova il file intero; con deep=True cerca plist/compressi incorporati nei dati."""
    pl = _try(b)
    if pl is None and deep:
        n = 0
        for m in MARKERS:
            for mt in re.finditer(re.escape(m), b):
                pl = _try(b[mt.start():]); n += 1
                if pl is not None or n > 40: break
            if pl is not None or n > 40: break
    if isinstance(pl, dict) and "$objects" in pl and "$top" in pl:
        pl = decode_keyed_archive(pl)
    return pl

def read_plist(path, deep=False):
    try:
        with open(path, "rb") as f: return parse_plist_bytes(f.read(), deep)
    except Exception: return None

def strings_of(b, minlen=5):
    out = [m.group().decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, b)]
    out += [m.group().decode("utf-16le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, b)]
    seen, res = set(), []
    for s in out:
        s = s.strip()
        if s and s not in seen: seen.add(s); res.append(s)
    return res


# ------------------------------- analisi -------------------------------
def clean(n):
    return ORDER_PREFIX.sub("", re.sub(r"\.(patch|cst)$", "", n))

def _nm(d):
    for k in NAME_KEYS:
        if isinstance(d.get(k), str) and d[k].strip(): return d[k].strip()

def _det(d, n=5):
    return ", ".join(f"{k}={v}" for k, v in d.items()
                     if isinstance(v, (str, int, float, bool)) and not k.startswith("_") and v != "")[:n * 40]

def find_plugins(obj):
    out = []
    def w(o):
        if isinstance(o, dict):
            cls, nm = o.get("_class", ""), _nm(o)
            if nm and ((cls and PLUGIN_CLS.search(cls)) or (AU_KEYS & o.keys())):
                lab = f"{nm} [{_det({k: v for k, v in o.items() if k in AU_KEYS})}]"
                if lab not in out: out.append(lab)
            for v in o.values(): w(v)
        elif isinstance(o, list):
            for v in o: w(v)
    w(obj); return out

def find_controllers(obj):
    out = []
    def w(o, path):
        if isinstance(o, dict):
            cls = o.get("_class", "")
            if cls and CTRL_CLS.search(cls):
                out.append(f"{_nm(o) or cls} [{_det(o)}]")
            for k, v in o.items():
                if CTRL_KEY.search(str(k)) and isinstance(v, (dict, list)) and v:
                    out.append(f"{path}/{k}  ({len(v)} elementi)")
                w(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o): w(v, f"{path}[{i}]")
    w(obj, ""); return list(dict.fromkeys(out))


# ---- Audio Unit: identificativi 4CC (salvati al contrario: manufacturer, type, subtype) ----
AU_RE = re.compile(rb"([\x20-\x7e]{4})(umua|xfua|fmua|imua|ngua|xmua|tnua|xrua)([\x20-\x7e]{4})")
AU_TYPES = {"aumu": "strumento", "aufx": "effetto", "aumf": "effetto MIDI", "aumi": "MIDI processor",
            "augn": "generatore", "aumx": "mixer", "aurx": "reverb/format"}
_AU = None

def au_names():
    """Nomi ufficiali dai metadati AudioComponents installati, senza avviare plugin."""
    global _AU
    if _AU is None:
        _AU = {}
        import glob
        for d in ("/Library/Audio/Plug-Ins/Components", os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
                  "/System/Library/Components"):
            for ip in glob.glob(os.path.join(d, "*.component", "Contents", "Info.plist")):
                try:
                    with open(ip, "rb") as f: info = plistlib.load(f)
                    for c in info.get("AudioComponents", []):
                        _AU.setdefault((c["type"], c["subtype"], c["manufacturer"]), c.get("name", ""))
                except Exception: pass
    return _AU

def au_records(b):
    res = []
    for m in AU_RE.finditer(b):
        mfr, typ, sub = (m[i].decode()[::-1] for i in (1, 2, 3))
        pre = re.findall(rb"[\x20-\x7e]{4,}", b[max(0, m.start() - 48):m.start()])
        hint = next((x.decode() for x in reversed(pre) if not x.endswith(b".aupreset")), "")
        full = au_names().get((typ, sub, mfr))
        kind = AU_TYPES.get(typ, typ)
        lab = f"{full or hint or '?'}  [{kind}; {typ} {sub} {mfr}]" + ("" if full else "  (nome da .cst, può essere troncato)")
        res.append({"name": full or hint or "?", "label": lab, "source": "firma AU nel .cst",
                    "offset": m.start(), "type": typ, "subtype": sub, "manufacturer": mfr,
                    "bypass": None, "slot": None})
    return res

def find_au(b):
    return [r["label"] for r in au_records(b)]

# Nomi abbreviati osservati nei record nativi GAME. Non cercare semplicemente
# stringhe nel file: preset, campioni e stato interno possono contenere altri nomi.
NATIVE_NAMES = {"Chan EQ": "Channel EQ", "Space D": "Space Designer",
                "MultiMtr": "Multimeter", "Klopfgeis": "Klopfgeist",
                "ChordTrig": "Chord Trigger", "Rotor": "Rotor Cabinet",
                "Delay D": "Delay Designer", "Chorus": "Chorus", "Exciter": "Exciter"}
NATIVE_RE = re.compile(rb"([\x20-\x7e]{1,12})\x00{1,12}GAME\x00{4}")

def native_records(b):
    records = []
    for m in NATIVE_RE.finditer(b):
        short = m[1].decode("ascii")
        name = NATIVE_NAMES.get(short, short)
        records.append({"name": name, "label": f"Apple: {name} [record nativo .cst; nome salvato: {short}]",
                        "source": "record nativo GAME nel .cst", "offset": m.start(),
                        "bypass": None, "slot": None})
    return records

def strip_info(path):
    from plugin_state import enrich_records, saved_bypass
    from midi_inputs import read_keyboard_layer
    with open(path, "rb") as f: b = f.read()
    pl = parse_plist_bytes(b, deep=True)
    strs = [s for s in strings_of(b) if re.search(r"[A-Za-z]{3}", s) and len(s) < 80]
    records = sorted(au_records(b) + native_records(b), key=lambda r: r["offset"])
    # Il registro viene consultato solo quando esiste almeno una firma AU.
    registry = au_names() if any('type' in r for r in records) else {}
    records = enrich_records(b, records, registry)
    for record in records:
        record["bypass"] = saved_bypass(b, record)
        if record["bypass"] is not None:
            record["bypass_source"] = "flag slot CST 6.14, confrontato con MainStage"
    return {"name": clean(os.path.basename(path)), "file": os.path.basename(path),
            "plugins": [r["display_label"] for r in records], "plugin_records": records,
            "plist_plugin_candidates": find_plugins(pl) if pl is not None else [],
            "warnings": ["Rilevamento da firme .cst: completezza e numero di slot non verificati; bypass disponibile solo per header riconosciuti."],
            "plist": pl, "strings": strs[:40], "keyboard_layer": read_keyboard_layer(b, parse_plist_bytes)}


GUID = re.compile(r"^[0-9A-F]{8}-([0-9A-F]{4}-){3}[0-9A-F]{12}$", re.I)

def deep_decode(o):
    """Decodifica ricorsivamente i blob bplist (NSKeyedArchiver annidati)."""
    if isinstance(o, (bytes, bytearray)) and bytes(o[:8]) == b"bplist00":
        try:
            pl = plistlib.loads(bytes(o))
            if isinstance(pl, dict) and "$objects" in pl: pl = decode_keyed_archive(pl)
            return deep_decode(pl)
        except Exception: return o
    if isinstance(o, dict): return {k: deep_decode(v) for k, v in o.items()}
    if isinstance(o, list): return [deep_decode(v) for v in o]
    return o

def find_key(o, key):
    res = []
    def w(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == key and not isinstance(v, (dict, list)): res.append(v)
                w(v)
        elif isinstance(x, list):
            for v in x: w(v)
    w(o); return res

def parse_hardware(hw, hardware_map=None, records=None):
    """Assegnazioni salvate; i codici MIDI interni restano espliciti."""
    hardware_map = hardware_map if hardware_map is not None else {}
    devs, lines = set(), []
    cm = (hw or {}).get("controllerMapping") or {} if isinstance(hw, dict) else {}
    if not isinstance(cm, dict):
        raise ValueError("HardwareSetup.controllerMapping non è un dizionario")
    for k, v in cm.items():
        if not isinstance(v, dict): continue
        m = re.search(r"'uuidString': '([^']*)'", str(k)); name = m[1] if m else str(k)
        port = v.get("MIDIPort") or {}
        if not isinstance(port, dict):
            raise ValueError(f"MIDIPort non valido per {name}")
        dev = " ".join(x for x in (port.get("manufacturer"), port.get("model")) if x) or port.get("name", "?")
        devs.add(dev + (f"  (porta MIDI: {port['name']})" if port.get("name") else ""))
        cid, ch = v.get("controllerID"), v.get("channelID")
        # I codici interni type/controllerID non equivalgono sempre a CC MIDI.
        desc = (dev + (f", porta {port['name']}" if port.get("name") else "")
                + f", tipo MainStage {v.get('type', '?')}, controllerID {cid}"
                + (f", canale salvato {ch}" if ch is not None else ""))
        hardware_map[name] = desc
        if records is not None:
            records.append({"control": name, "device": dev, "port": port.get("name", "Porta non specificata"),
                            "channel": ch, "controller_id": cid, "message_type": v.get("type")})
        shown = f"controllo {name}" if GUID.match(name) else name
        lines.append(f"{shown}  <-  {desc}")
    return sorted(devs), sorted(lines)

def patch_controllers(pl, hardware_map=None, instance_names=None):
    """Controlli con mapping nel Patch (patchMappings) + controlli del workspace con valori personalizzati."""
    out = []
    if not isinstance(pl, dict): return out
    patch = pl.get("patch") or {}
    inst = dict(instance_names or {})
    inst.update({c.get("Channel_instID"): c.get("Channel_name") for c in pl.get("channels") or [] if isinstance(c, dict)})
    pm = deep_decode(patch.get("patchMappings") or {})
    for ident, nums in (pm.items() if isinstance(pm, dict) else []):
        name = str(ident).replace("\x01IDENTITY:", "")
        label = f"controllo a schermo {name[:8]}" if GUID.match(name) else name
        hw = (hardware_map or {}).get(name)
        tg = []
        for mp in (nums.values() if isinstance(nums, dict) else [nums]):
            ids, act = find_key(mp, "kGInstIDKey"), find_key(mp, "actionIndex")
            t = ", ".join(str(inst.get(i, f"instID {i}")) for i in ids) or "destinazione non risolta"
            tg.append(f"-> {t}" + (f" (azione {act[0]})" if act else ""))
        out.append(f"Mapping: {label}" + (f" [{hw}]" if hw else " [nessuna assegnazione hardware risolta]") + "  " + "; ".join(tg))
    ui = (patch.get("engineNode") or {}).get("uiPluginDataDict") or {}
    for k, v in sorted(ui.items()):
        ident = str(v.get("identity", k) if isinstance(v, dict) else k).replace("\x01IDENTITY:", "")
        if GUID.match(ident) or not isinstance(v, dict): continue
        if any(v.get(x) for x in ("storeDict", "overrideDict", "containsDictionary")):
            out.append(f"Controllo a schermo: {ident}  (valori personalizzati; non prova un uso MIDI)")
    for ch in pl.get("channels") or []:
        mt = ch.get("MIDITransform") if isinstance(ch, dict) else None
        if mt and mt.get("transforms"):
            out.append(f"Trasformazioni MIDI su '{ch.get('Channel_name')}': "
                       + json.dumps(mt['transforms'], ensure_ascii=False, default=str))
    return out

def controller_view(pl, hardware_records, instances):
    """Dati strutturati per la GUI, indipendenti dalle etichette del report testuale."""
    data = pl if isinstance(pl, dict) else {}
    patch = data.get('patch') if isinstance(data.get('patch'), dict) else {}
    assignments = {r['control']: r for r in hardware_records}
    view = {"mappings": [], "transforms": [], "screen_controls": [], "devices": []}
    pm = deep_decode(patch.get('patchMappings') or {})
    for identity, values in (pm.items() if isinstance(pm, dict) else []):
        control = str(identity).removeprefix('\x01IDENTITY:')
        for index, blob in (values.items() if isinstance(values, dict) else [('0', values)]):
            targets = []
            def walk(obj):
                if isinstance(obj, dict):
                    if 'kGInstIDKey' in obj or 'actionIndex' in obj:
                        ident, action = obj.get('kGInstIDKey'), obj.get('actionIndex')
                        name = (f'Azione MainStage {action}' if ident == 0 and action is not None
                                else instances.get(ident, f'Channel strip non risolto (instID {ident})'))
                        targets.append({"name": str(name), "action": action if isinstance(action, int) else None})
                    for val in obj.values(): walk(val)
                elif isinstance(obj, list):
                    for val in obj: walk(val)
            walk(blob)
            low, high = find_key(blob, 'rangeLow'), find_key(blob, 'rangeHigh')
            view['mappings'].append({"control": control, "hardware": assignments.get(control),
                                     "targets": targets, "index": str(index).removeprefix('\x01NUMBER:'),
                                     "range_low": low[0] if low and isinstance(low[0], (int, float)) else None,
                                     "range_high": high[0] if high and isinstance(high[0], (int, float)) else None,
                                     "details": json.dumps(blob, ensure_ascii=False, default=str, indent=2)})
    engine = patch.get('engineNode') if isinstance(patch.get('engineNode'), dict) else {}
    ui = engine.get('uiPluginDataDict') or {}
    for key, value in (ui.items() if isinstance(ui, dict) else []):
        if isinstance(value, dict) and any(value.get(k) for k in ('storeDict', 'overrideDict', 'containsDictionary')):
            identity = str(value.get('identity', key)).removeprefix('\x01IDENTITY:')
            view['screen_controls'].append(identity)
    for channel in data.get('channels') or []:
        if not isinstance(channel, dict): continue
        transform = channel.get('MIDITransform')
        if not isinstance(transform, dict) or not isinstance(transform.get('transforms'), list): continue
        rules = []
        for rule in transform['transforms']:
            if not isinstance(rule, dict): continue
            def code(key):
                value = rule.get(key)
                return str(value) if value is not None else None
            rules.append({"input": code('in'), "output": code('out'), "filtered": rule.get('filter') is True,
                          "details": json.dumps(rule, ensure_ascii=False, default=str, indent=2)})
        if rules:
            view['transforms'].append({"strip": channel.get('Channel_name') or 'Senza nome', "rules": rules})
    devices = {}
    for record in hardware_records:
        devices.setdefault(record['device'], []).append(record)
    def natural(name):
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', name)]
    view['devices'] = [{"name": name, "controls": sorted(controls, key=lambda r: natural(r['control']))}
                       for name, controls in sorted(devices.items())]
    view['mappings'].sort(key=lambda item: natural(item['control']))
    view['screen_controls'] = sorted(set(view['screen_controls']), key=natural)
    return view


def scan_patch(dirpath, hardware_map=None, instance_names=None, seen=None, hardware_records=None):
    seen = set() if seen is None else seen
    real = os.path.realpath(dirpath)
    if real in seen:
        raise ValueError(f"Cartella patch già visitata (possibile collegamento ciclico): {dirpath}")
    seen.add(real)
    pl = read_plist(os.path.join(dirpath, "data.plist"))
    warnings = []
    if not isinstance(pl, dict):
        warnings.append("data.plist mancante, illeggibile o non supportato: analisi parziale.")
        pl = None
    data = pl or {}
    if not isinstance(data.get("channels", []), list):
        warnings.append("channels non è una lista: metadati channel strip non disponibili.")
        data = dict(data, channels=[])
    if not isinstance(data.get("patch", {}), dict):
        warnings.append("patch non è un dizionario: mapping non disponibili.")
        data = dict(data, patch={})
    available = sorted(d for d in os.listdir(dirpath)
                       if d.endswith(".patch") and os.path.isdir(os.path.join(dirpath, d)))
    saved = data.get("nodes")
    subs = []
    if isinstance(saved, list):
        for name in saved:
            if not isinstance(name, str) or name not in available:
                warnings.append(f"Nodo salvato mancante o non valido: {name!r}")
            elif name in subs:
                warnings.append(f"Nodo duplicato: {name}")
            else:
                subs.append(name)
        for name in available:
            if name not in subs:
                warnings.append(f"Cartella non elencata in nodes, aggiunta in coda: {name}")
                subs.append(name)
    else:
        subs = available
        if subs:
            warnings.append("Ordine nodes non disponibile: usato ordine alfabetico.")
    kind = "Set" if subs or isinstance(saved, list) else "Patch"
    if saved == []:
        warnings.append("Set vuoto dedotto dalla presenza di nodes=[]; da validare in MainStage.")
    instances = dict(instance_names or {})
    channels = [c for c in data.get("channels", []) if isinstance(c, dict)]
    instances.update({c.get("Channel_instID"): c.get("Channel_name") for c in channels})
    node = {"kind": kind, "name": clean(os.path.basename(dirpath)), "path": os.path.abspath(dirpath),
            "plist": pl, "strips": [], "controllers": [],
            "children": [], "warnings": warnings}
    try:
        node['controller_view'] = controller_view(data, hardware_records or [], instances)
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        node['controller_view'] = {"mappings": [], "transforms": [], "screen_controls": [], "devices": []}
        warnings.append(f"Dati grafici controller non interpretabili: {exc}")
    try:
        node["controllers"] = patch_controllers(data, hardware_map, instances)
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        warnings.append(f"Mapping non interpretabili: {exc}")
    # L'array channels conserva nomi e ordine. I file non referenziati restano visibili.
    used = set()
    for channel in channels:
        filename = channel.get("Filename")
        strip = None
        if isinstance(filename, str) and os.path.basename(filename) == filename:
            used.add(filename)
            try:
                strip = strip_info(os.path.join(dirpath, filename))
            except Exception as exc:
                warnings.append(f"Channel strip {filename}: {type(exc).__name__}: {exc}")
        else:
            warnings.append(f"Filename del channel strip mancante o non valido: {filename!r}")
        if strip is None:
            strip = {"file": filename, "plugins": [], "plugin_records": [], "plist": None,
                     "strings": [], "warnings": ["File .cst non disponibile: plugin non determinabili."]}
        strip.update({"name": channel.get("Channel_name") or clean(filename or "Senza nome"),
                      "metadata": channel, "is_alias": bool(channel.get("isAlias")),
                      "alias_uuid": channel.get("aliasUUID"), "uuid": channel.get("UUID")})
        node["strips"].append(strip)
    for filename in sorted(os.listdir(dirpath)):
        if filename.endswith(".cst") and filename not in used:
            try:
                strip = strip_info(os.path.join(dirpath, filename))
                strip.update({"metadata": {}, "is_alias": False, "uuid": None})
                node["strips"].append(strip)
                warnings.append(f"File .cst non referenziato in channels: {filename}")
            except Exception as exc:
                warnings.append(f"Channel strip {filename}: {type(exc).__name__}: {exc}")
    node["extra_plugins"] = find_plugins(pl) if pl else []
    for sub in subs:
        child_path = os.path.join(dirpath, sub)
        try:
            node["children"].append(scan_patch(child_path, hardware_map, instances, seen, hardware_records))
        except (OSError, ValueError) as exc:
            warnings.append(f"Scansione incompleta di {sub}: {exc}")
    return node


def resolve_aliases(tree):
    originals = {}
    for node in _all(tree):
        for strip in node["strips"]:
            if strip.get("uuid") and not strip.get("is_alias"):
                originals.setdefault(strip["uuid"], []).append((node, strip))
    for node in _all(tree):
        for strip in node["strips"]:
            if not strip.get("is_alias"):
                continue
            candidates = originals.get(strip.get("alias_uuid"), [])
            if len(candidates) == 1:
                owner, source = candidates[0]
                strip["alias_target"] = {"node": owner["name"], "path": owner["path"],
                                         "strip": source["name"], "uuid": source["uuid"]}
                # L'elenco dell'originale è un riferimento, non una nuova istanza.
                strip["plugins"] = list(source["plugins"])
                strip["plugin_records"] = [dict(r) for r in source["plugin_records"]]
            else:
                strip["warnings"].append("Alias non risolto: " +
                                         ("originale assente." if not candidates else "UUID ambiguo."))


def scan_concert(path):
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    root = os.path.join(path, "Concert.patch")
    if not (os.path.isdir(root) and os.path.isfile(os.path.join(root, "data.plist"))):
        raise ValueError("Pacchetto concerto non valido: richiesto Concert.patch/data.plist.")
    hardware_map = {}
    hardware_records = []
    lay = os.path.join(path, "workspace.layout", "setupZ.layout")
    pl = read_plist(lay, deep=True)
    hw_raw = pl.get("HardwareSetup") if isinstance(pl, dict) else None
    hardware_warning = None
    try:
        devs, lines = parse_hardware(hw_raw, hardware_map, hardware_records)
    except (ValueError, TypeError, AttributeError) as exc:
        devs, lines = [], []
        hardware_map.clear()
        hardware_records.clear()
        hardware_warning = f"HardwareSetup non interpretabile: {exc}"
    hw = [f"DISPOSITIVO ASSEGNATO: {d}" for d in devs] + lines
    tree = scan_patch(root, hardware_map, hardware_records=hardware_records)
    tree["kind"], tree["name"] = "Concert", os.path.basename(path)
    tree["hw_raw"], tree["hardware"] = hw_raw, hw
    tree["warnings"].append("Le assegnazioni salvate non attestano che l'hardware sia collegato.")
    tree["warnings"].append("Strip e mapping sono mostrati al livello di origine; ereditarietà e override non sono risolti.")
    if not isinstance(hw_raw, dict):
        tree["warnings"].append("HardwareSetup assente o illeggibile: assegnazioni hardware non disponibili.")
    if hardware_warning:
        tree["warnings"].append(hardware_warning)
    resolve_aliases(tree)
    from midi_inputs import resolve_midi_inputs
    resolve_midi_inputs(tree, pl)
    from concert_features import enrich
    enrich(tree)
    return tree, hw


def strip_label(strip):
    target = strip.get("alias_target")
    if target:
        return f"{strip['name']} [alias → {target['node']} / {target['strip']}]"
    return strip["name"] + (" [alias non risolto]" if strip.get("is_alias") else "")


def render_text(n, lvl=0):
    p = "  " * lvl
    out = [f"{p}{n['kind']}: {n['name']}"]
    if lvl == 0:
        out += [f"  Hardware: {h}" for h in n.get("hardware", [])]
    out += [f"{p}  Avviso: {w}" for w in n.get("warnings", [])]
    for s in n["strips"]:
        out.append(f"{p}  Channel strip: {strip_label(s)}")
        out += [f"{p}    Plugin: {x}" for x in s["plugins"]] or [f"{p}    (stringhe: {' | '.join(s['strings'][:8])})"]
        out += [f"{p}    Candidato da plist incorporato: {x}" for x in s.get("plist_plugin_candidates", [])]
        out += [f"{p}    Avviso: {w}" for w in s.get("warnings", [])]
    out += [f"{p}  Plugin (data.plist): {x}" for x in n["extra_plugins"]]
    out += [f"{p}  {c}" for c in n["controllers"]]
    for c in n["children"]: out += render_text(c, lvl + 1)
    return out

def _all(n):
    yield n
    for c in n["children"]: yield from _all(c)

def first_leaf(n):
    return n if not n["children"] else first_leaf(n["children"][0])

def diag(tree):
    lf = first_leaf(tree)
    print(f"mainstage_inspector {VERSION}")
    print(f"=== DIAGNOSTICA: patch '{lf['name']}' ===")
    print(json.dumps(lf["plist"], indent=1, default=str, ensure_ascii=False)[:7000])
    for s in lf["strips"][:2]:
        print(f"\n=== strip '{s['name']}': plist incorporato={s['plist'] is not None} ===")
        print(" | ".join(s["strings"]))
        print("AU trovati:", s["plugins"]); print("AU installati noti:", len(au_names()))
    print("\n=== HardwareSetup (workspace.layout) ===")
    print(json.dumps(tree.get("hw_raw"), indent=1, default=str, ensure_ascii=False)[:6000])
    for n in _all(tree):
        pm = (n["plist"] or {}).get("patch", {}).get("patchMappings") if isinstance(n["plist"], dict) else None
        if pm:
            print(f"\n=== patchMappings di '{n['name']}' ==="); print(json.dumps(pm, indent=1, default=str)[:4000]); break


def run_native(initial=None):
    from pathlib import Path
    import subprocess
    app = Path(__file__).resolve().parent / "MainStage Inspector.app"
    if not (app / "Contents/MacOS/MainStageInspector").is_file():
        from build_mac_app import build
        app = build()
    command = ["open", "-a", str(app)]
    if initial:
        command += ["--args", os.path.abspath(os.path.expanduser(initial))]
    subprocess.run(command, check=True)


# --------------------------------- GUI ---------------------------------
def run_gui(initial=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk(); root.title("MainStage Concert Inspector"); root.geometry("1100x720")
    top = ttk.Frame(root); top.pack(fill="x", padx=8, pady=6)
    lbl = ttk.Label(top, text="Nessun concerto caricato"); lbl.pack(side="left", padx=8)
    nb = ttk.Notebook(root); nb.pack(fill="both", expand=True, padx=8, pady=4)
    def mk(parent, cols):
        fr = ttk.Frame(parent); sb = ttk.Scrollbar(fr)
        t = ttk.Treeview(fr, columns=cols, yscrollcommand=sb.set); sb.config(command=t.yview)
        sb.pack(side="right", fill="y"); t.pack(fill="both", expand=True); return fr, t
    f1, tree = mk(nb, ("tipo",)); tree.heading("#0", text="Elemento"); tree.heading("tipo", text="Tipo"); tree.column("#0", width=750)
    nb.add(f1, text="Set / Patch")
    f2, ct = mk(nb, ()); ct.heading("#0", text="Controller / hardware (workspace.layout)"); nb.add(f2, text="Controller")
    f3 = ttk.Frame(nb); txt = tk.Text(f3, wrap="none"); txt.pack(fill="both", expand=True); nb.add(f3, text="Dettagli (data.plist)")
    state, nodes = {}, {}

    def fill(n, parent=""):
        iid = tree.insert(parent, "end", text=n["name"], values=(n["kind"],), open=n["kind"] != "Patch"); nodes[iid] = n
        for s in n["strips"]:
            sid = tree.insert(iid, "end", text=strip_label(s), values=("Channel strip",))
            for p in s["plugins"]: tree.insert(sid, "end", text=p, values=("Plugin",))
            for p in s.get("plist_plugin_candidates", []): tree.insert(sid, "end", text=p, values=("Candidato plist",))
            if not s["plugins"]:
                for x in s["strings"][:12]: tree.insert(sid, "end", text=x, values=("stringa (.cst)",))
            for w in s.get("warnings", []): tree.insert(sid, "end", text=w, values=("Avviso",))
        for p in n["extra_plugins"]: tree.insert(iid, "end", text=p, values=("Plugin",))
        for c in n["controllers"]: tree.insert(iid, "end", text=c, values=("Controllo / mapping",))
        for w in n.get("warnings", []): tree.insert(iid, "end", text=w, values=("Avviso",))
        for ch in n["children"]: fill(ch, iid)

    def on_sel(_):
        s = tree.selection()
        if s and s[0] in nodes:
            txt.delete("1.0", "end")
            txt.insert("1.0", json.dumps(nodes[s[0]]["plist"], indent=1, default=str, ensure_ascii=False)[:200000])
    tree.bind("<<TreeviewSelect>>", on_sel)

    def load(path):
        try: t, hw = scan_concert(path)
        except Exception as e: messagebox.showerror("Errore", str(e)); return
        tree.delete(*tree.get_children()); ct.delete(*ct.get_children()); nodes.clear()
        fill(t)
        for h in hw: ct.insert("", "end", text=h)
        state["t"] = t; lbl.config(text=os.path.basename(path))
    def export():
        if "t" not in state: return
        p = filedialog.asksaveasfilename(defaultextension=".txt")
        if p: open(p, "w", encoding="utf-8").write("\n".join(render_text(state["t"])))
    ttk.Button(top, text="Apri .concert…", command=lambda: (lambda p: p and load(p))(filedialog.askdirectory(title="Seleziona il pacchetto .concert"))).pack(side="left")
    ttk.Button(top, text="Esporta testo…", command=export).pack(side="left", padx=6)
    if initial: load(initial)
    root.mainloop()


# ------------------------------- Web UI -------------------------------
def _h(x): 
    import html; return html.escape(str(x))

def html_node(n):
    open_ = " open" if n["kind"] != "Patch" else ""
    out = [f'<details{open_}><summary><span class="k">{_h(n["kind"])}</span> {_h(n["name"])}</summary><div class="in">']
    for st in n["strips"]:
        out.append(f'<details><summary><span class="k">Channel strip</span> {_h(strip_label(st))}</summary><ul>')
        for pl in st["plugins"]: out.append(f'<li><span class="p">Plugin</span> {_h(pl)}</li>')
        for pl in st.get("plist_plugin_candidates", []): out.append(f'<li>Candidato da plist incorporato: {_h(pl)}</li>')
        if not st["plugins"]:
            for x in st["strings"][:10]: out.append(f'<li class="m">{_h(x)}</li>')
        out += [f'<li class="m">Avviso: {_h(w)}</li>' for w in st.get("warnings", [])]
        out.append("</ul></details>")
    if n["extra_plugins"] or n["controllers"]:
        out.append("<ul>")
        out += [f'<li><span class="p">Plugin</span> {_h(x)}</li>' for x in n["extra_plugins"]]
        out += [f'<li class="c">{_h(x)}</li>' for x in n["controllers"]]
        out.append("</ul>")
    out += [f'<p class="m">Avviso: {_h(w)}</p>' for w in n.get("warnings", [])]
    out += [html_node(c) for c in n["children"]]
    out.append("</div></details>")
    return "".join(out)

def render_page(path):
    body = ""
    if path:
        try:
            t, hw = scan_concert(os.path.expanduser(path.strip().strip("'\"")))
            body = ("<h2>Assegnazioni hardware salvate (workspace)</h2><ul>" + "".join(f"<li>{_h(h)}</li>" for h in hw) + "</ul>"
                    "<h2>Set / Patch</h2>" + html_node(t))
        except Exception as e:
            body = f'<p class="err">Errore: {_h(e)}</p>'
    return f"""<!doctype html><meta charset="utf-8"><title>MainStage Inspector</title>
<style>body{{font:14px -apple-system,sans-serif;margin:24px;max-width:1000px}}
input[type=text]{{width:70%;padding:6px}}summary{{cursor:pointer;padding:2px 0}}
.in{{margin-left:18px;border-left:1px solid #ccc;padding-left:10px}}ul{{margin:2px 0 6px 18px;padding:0}}
.k{{font-size:11px;background:#e8eaf6;border-radius:4px;padding:1px 5px;margin-right:4px}}
.p{{color:#0a6;font-weight:600}}.c{{color:#b50;font-weight:600}}.m{{color:#888}}.err{{color:#c00}}</style>
<h1>MainStage Inspector <small style="font-weight:normal;color:#888">{VERSION}</small></h1>
<form><input type="text" name="path" value="{_h(path or '')}" placeholder="/percorso/Example.concert">
<button>Analizza</button></form>{body or '<p>Inserisci il percorso del file .concert (trascina la cartella nel Terminale per ottenerlo).</p>'}"""

def run_web(path=None, port=8765):
    import http.server, urllib.parse, webbrowser
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            data = render_page((q.get("path") or [path or ""])[0]).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"Apri {url}  (Ctrl+C per uscire)"); webbrowser.open(url)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Analizza un pacchetto MainStage senza modificarlo.")
    parser.add_argument("path", nargs="?", help="Percorso del pacchetto .concert")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli", action="store_true", help="Report di testo")
    mode.add_argument("--diag", action="store_true", help="Diagnostica del formato")
    mode.add_argument("--html", action="store_true", help="Report HTML stampabile")
    mode.add_argument("--json", action="store_true", help="Report strutturato JSON")
    mode.add_argument("--gui", action="store_true", help="App nativa macOS (predefinita)")
    mode.add_argument("--web", action="store_true", help="Interfaccia web alternativa")
    mode.add_argument("--tk", action="store_true", help="Interfaccia Tk alternativa")
    parser.add_argument("--no-au-scan", action="store_true", help="Non interrogare gli Audio Unit installati")
    args = parser.parse_args(argv)
    if (args.cli or args.diag or args.json or args.html) and not args.path:
        parser.error("specificare il percorso del pacchetto .concert")
    if args.no_au_scan:
        global _AU
        _AU = {}
    try:
        if args.cli or args.diag or args.json or args.html:
            tree, _ = scan_concert(args.path)
            if args.diag:
                diag(tree)
            elif args.html:
                print(tree["printable_report"])
            elif args.json:
                print(json.dumps(tree, ensure_ascii=False, indent=2, default=str))
            else:
                print("\n".join(render_text(tree)))
        elif args.web:
            run_web(args.path)
        elif args.tk:
            run_gui(args.path)
        else:
            run_native(args.path)
    except (OSError, ValueError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
