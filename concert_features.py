# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Zone, stato salvato, riepilogo ed esportazione stampabile del concerto."""
from collections import defaultdict
from html import escape


def nodes(tree):
    yield tree
    for child in tree['children']:
        yield from nodes(child)


def valid_int(value, low, high):
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def enrich(tree):
    plugins = {}
    devices = defaultdict(lambda: {'keyboards': set(), 'patches': set()})
    aliases = []
    for node in nodes(tree):
        for strip in node['strips']:
            layer = strip.get('keyboard_layer') or {}
            low, high = valid_int(layer.get('lowNote'), 0, 127), valid_int(layer.get('highNote'), 0, 127)
            vlow, vhigh = valid_int(layer.get('lowVelocity'), 0, 127), valid_int(layer.get('highVelocity'), 0, 127)
            strip['zone'] = {'low': low, 'high': high, 'velocity_low': vlow, 'velocity_high': vhigh,
                             'transpose': valid_int(layer.get('transpose'), -127, 127),
                             'override_parent': layer.get('overrideParentsKeyZone') is True,
                             'unpitched': layer.get('noTranspose') is True}
            if low is not None and high is not None and low > high:
                strip['zone'].update(low=None, high=None)
            if vlow is not None and vhigh is not None and vlow > vhigh:
                strip['zone'].update(velocity_low=None, velocity_high=None)
            metadata = strip.get('metadata') or {}
            strip['muted'] = metadata.get('Channel_isMuted') if isinstance(metadata.get('Channel_isMuted'), bool) else None
            strip['solo'] = metadata.get('Channel_isSolo') if isinstance(metadata.get('Channel_isSolo'), bool) else None
            strip['layer_bypassed'] = layer.get('bypass') if isinstance(layer.get('bypass'), bool) else None
            for assignment in strip.get('midi_input', {}).get('assignments', []):
                if assignment.get('device'):
                    device = devices[assignment['device']]
                    device['keyboards'].add(assignment.get('keyboard') or '?')
                    device['patches'].add(node['name'])
            if strip.get('is_alias'):
                target = strip.get('alias_target')
                aliases.append({'strip': strip['name'], 'node': node['name'],
                                'target': f"{target['node']} / {target['strip']}" if target else 'Non risolto'})
            for record in strip['plugin_records']:
                key = tuple(record.get(k) for k in ('type', 'subtype', 'manufacturer')) if record.get('type') else ('native', record['name'])
                item = plugins.setdefault(key, {'name': record['name'], 'instances': 0, 'references': 0, 'patches': set()})
                item['references'] += 1
                item['instances'] += not strip.get('is_alias', False)
                item['patches'].add(node['name'])
    all_nodes = list(nodes(tree))
    tree['summary'] = {'sets': sum(n['kind'] == 'Set' for n in all_nodes),
                       'patches': sum(n['kind'] == 'Patch' for n in all_nodes),
                       'strips': sum(len(n['strips']) for n in all_nodes), 'alias_count': len(aliases),
                       'plugins': [dict(item, patches=sorted(item['patches'])) for item in sorted(plugins.values(), key=lambda i: i['name'].casefold())],
                       'devices': [dict(name=name, keyboards=sorted(info['keyboards']), patches=sorted(info['patches'])) for name, info in sorted(devices.items())],
                       'aliases': aliases}
    tree['printable_report'] = readable_report(tree)


def note(number):
    # Convenzione esplicita: MIDI 60 = C4.
    return ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'][number % 12] + str(number // 12 - 1)


def readable_report(tree):
    h = lambda value: escape(str(value), quote=True)
    summary = tree['summary']
    body = [f"<h1>{h(tree['name'])}</h1><p>{summary['sets']} Set · {summary['patches']} Patch · {summary['strips']} channel strip · {summary['alias_count']} alias</p>",
            '<p>Configurazione salvata. Zone locali; override dei livelli superiori non risolti. Convenzione note: MIDI 60 = C4. Bypass letto per il formato CST riconosciuto; negli altri casi resta non determinato.</p>', '<h2>Plugin richiesti</h2><table><thead><tr><th>Plugin</th><th>Istanze senza alias</th><th>Riferimenti</th></tr></thead><tbody>']
    for item in summary['plugins']:
        body.append(f"<tr><td>{h(item['name'])}</td><td>{item['instances']}</td><td>{item['references']}</td></tr>")
    body.append('</tbody></table><h2>Tastiere assegnate agli strip</h2>')
    for device in summary['devices']:
        body.append(f"<p><b>{h(device['name'])}</b> · {h(', '.join(device['keyboards']))}</p>")
    for n in nodes(tree):
        body.append(f"<h2>{h(n['kind'])} · {h(n['name'])}</h2>")
        if not n['strips']:
            body.append('<p>Nessun channel strip locale.</p>')
        for strip in n['strips']:
            state = ' · MUTE' if strip.get('muted') else ''
            state += ' · SOLO' if strip.get('solo') else ''
            state += ' · Layer disattivato' if strip.get('layer_bypassed') else ''
            body.append(f"<section><h3>{h(strip['name'])}{state}</h3>")
            if strip.get('alias_target'):
                target = strip['alias_target']
                body.append(f"<p>Alias di {h(target['node'])} / {h(target['strip'])}</p>")
            for assignment in strip.get('midi_input', {}).get('assignments', []):
                body.append(f"<p>Keyboard: {h(assignment.get('keyboard') or 'Non ricavabile')} → {h(assignment.get('device') or 'Non ricavabile')}; porta: {h(assignment.get('port') or 'Non specificata')}</p>")
            zone = strip.get('zone', {})
            if zone.get('low') is not None and zone.get('high') is not None:
                body.append(f"<p>Note: {note(zone['low'])}–{note(zone['high'])} (MIDI {zone['low']}–{zone['high']}) · Velocity: {zone.get('velocity_low')}–{zone.get('velocity_high')} · Trasposizione: {zone.get('transpose')} semitoni</p>")
            body.append('<ul>')
            for plugin in strip['plugin_records']:
                presets = '; '.join(f"{p['role']}: {p['name']}" + (' (modificato)' if p.get('modified') else '') for p in plugin.get('presets', []))
                preset = presets or plugin.get('setting_name') or 'Preset non ricavabile'
                bypass = ' · BYPASS' if plugin.get('bypass') is True else ' · attivo' if plugin.get('bypass') is False else ' · stato non ricavabile'
                body.append(f"<li><b>{h(plugin['name'])}</b> — {h(preset)}{bypass}</li>")
            body.append('</ul></section>')
    return '''<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Report MainStage</title><style>
body{font:14px system-ui,sans-serif;color:#263443;max-width:980px;margin:40px auto;padding:0 24px}h1{color:#3e5d77}h2{margin-top:30px;border-bottom:1px solid #d8dfe5;padding-bottom:8px}h3{color:#705d41}section{border:1px solid #e1e5e8;border-radius:8px;padding:0 16px;margin:12px 0;break-inside:avoid}p,li{line-height:1.5}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}thead{display:table-header-group}@media print{body{margin:0;max-width:none;font-size:10pt}h2{break-after:avoid}section{box-shadow:none}}
</style></head><body>''' + ''.join(body) + '</body></html>'
