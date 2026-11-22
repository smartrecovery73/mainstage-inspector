# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Collega layer MIDI .cst, tastiere del layout e assegnazioni hardware salvate."""
import ast
import re


def identity_name(value):
    if isinstance(value, dict):
        return value.get('uuidString')
    if isinstance(value, str):
        if value.startswith('{'):
            try:
                return identity_name(ast.literal_eval(value))
            except (ValueError, SyntaxError):
                return value
        return value.removeprefix('\x01IDENTITY:')
    return None


def read_keyboard_layer(data, decode):
    layers = []
    for match in re.finditer(b'bplist00', data):
        offset = match.start()
        if offset < 4:
            continue
        size = int.from_bytes(data[offset - 4:offset], 'little')
        if not 8 <= size <= min(len(data) - offset, 16 * 1024 * 1024):
            continue
        try:
            parsed = decode(data[offset:offset + size])
            dictionary = parsed.get('dictionary') if isinstance(parsed, dict) else None
            layer = dictionary.get('layer') if isinstance(dictionary, dict) else None
            if isinstance(layer, dict) and 'keyboardIndex' in layer:
                layers.append(layer)
        except (ValueError, TypeError, IndexError, KeyError, RecursionError):
            continue
    # Più layer non vengono arbitrariamente fusi o assegnati al primo trovato.
    return layers[0] if len(layers) == 1 else None


def resolve_midi_inputs(tree, layout):
    layout = layout if isinstance(layout, dict) else {}
    hardware = layout.get('HardwareSetup') or {}
    hardware = hardware if isinstance(hardware, dict) else {}
    identities = hardware.get('keyboardIdentities') or []
    identities = identities if isinstance(identities, list) else []
    cm = hardware.get('controllerMapping') or {}
    assignments = {identity_name(key): value for key, value in cm.items()} if isinstance(cm, dict) else {}
    objects = layout.get('OnScreenObjects') or {}
    models = objects.get('PluginModels', []) if isinstance(objects, dict) else []
    models = models if isinstance(models, list) else []
    labels = {identity_name(model.get('pluginIdentity')): model.get('name')
              for model in models if isinstance(model, dict)}

    def resolve(index, midi_channel=None):
        result = {'keyboard_index': index, 'keyboard': None, 'device': None, 'port': None,
                  'channel': None, 'part_channel': midi_channel, 'status': 'non risolto'}
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(identities):
            return result
        identity = identity_name(identities[index])
        if not identity:
            return result
        result['identity'] = identity
        result['keyboard'] = labels.get(identity) or identity
        assignment = assignments.get(identity)
        if not isinstance(assignment, dict):
            result['status'] = 'tastiera risolta; hardware non assegnato o non ricavabile'
            return result
        port = assignment.get('MIDIPort')
        if not isinstance(port, dict):
            return result
        maker, model = port.get('manufacturer'), port.get('model')
        if isinstance(model, str) and model:
            device = model if not maker or model.casefold().startswith(str(maker).casefold()) else f'{maker} {model}'
        else:
            device = port.get('name')
        result.update(device=device, port=port.get('name'), channel=assignment.get('channelID'),
                      status='risolto' if device else 'hardware non ricavabile')
        return result

    def visit(node):
        for strip in node['strips']:
            layer = strip.get('keyboard_layer')
            if not isinstance(layer, dict):
                if any(record.get('type') == 'aumu' for record in strip.get('plugin_records', [])):
                    strip['midi_input'] = {'assignments': [], 'status': 'Ingresso MIDI non ricavabile dal file .cst'}
                continue
            settings = layer.get('multitimbralSettings')
            if layer.get('multitimbralEnabled') and isinstance(settings, list):
                inputs = [resolve(item.get('keyboardIndex'), item.get('channel'))
                          for item in settings if isinstance(item, dict)]
            else:
                inputs = [resolve(layer.get('keyboardIndex'))]
            strip['midi_input'] = {'assignments': inputs, 'status': 'Assegnazione salvata',
                                   'source': 'WsKeyboardLayer.keyboardIndex → HardwareSetup.keyboardIdentities → controllerMapping'}
        for child in node['children']:
            visit(child)
    visit(tree)
