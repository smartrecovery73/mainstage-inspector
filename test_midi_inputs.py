# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
import plistlib
import unittest
from midi_inputs import read_keyboard_layer, resolve_midi_inputs
import mainstage_inspector as inspector


class MIDIInputTests(unittest.TestCase):
    def layout(self):
        return {'HardwareSetup': {'keyboardIdentities': [{'uuidString': 'Piano'}, {'uuidString': 'Keyboard 1'}],
                                 'controllerMapping': {"{'uuidString': 'Keyboard 1'}": {'MIDIPort': {
                                     'manufacturer': 'Example', 'model': 'Example Keyboard', 'name': 'Example Keyboard'}, 'channelID': 0}}},
                'OnScreenObjects': {'PluginModels': [{'pluginIdentity': {'uuidString': 'Keyboard 1'}, 'name': 'KEYBOARD'}]}}

    def resolve(self, layer, layout=None):
        strip = {'name': 'Hammond (Main)', 'keyboard_layer': layer}
        tree = {'strips': [strip], 'children': []}
        resolve_midi_inputs(tree, self.layout() if layout is None else layout)
        return strip['midi_input']['assignments']

    def test_index_identity_and_hardware_chain(self):
        item = self.resolve({'keyboardIndex': 1})[0]
        self.assertEqual(item['keyboard'], 'KEYBOARD')
        self.assertEqual(item['device'], 'Example Keyboard')
        self.assertEqual(item['port'], 'Example Keyboard')
        self.assertEqual(item['channel'], 0)

    def test_unknown_and_negative_index_do_not_select_last_keyboard(self):
        for index in [-1, 200, True]:
            item = self.resolve({'keyboardIndex': index})[0]
            self.assertIsNone(item['device'])
            self.assertIsNone(item['keyboard'])
        self.assertIsNone(self.resolve({'keyboardIndex': 1}, {})[0]['keyboard'])

    def test_multitimbral_assignments_and_alias_local_layer(self):
        inputs = self.resolve({'keyboardIndex': 0, 'multitimbralEnabled': True,
                               'multitimbralSettings': [{'channel': 3, 'keyboardIndex': 1}]})
        self.assertEqual(inputs[0]['part_channel'], 3)
        self.assertEqual(inputs[0]['keyboard'], 'KEYBOARD')
        tree = {'strips': [{'name': 'Original', 'keyboard_layer': {'keyboardIndex': 0}},
                           {'name': 'Alias', 'is_alias': True, 'keyboard_layer': {'keyboardIndex': 1}}], 'children': []}
        resolve_midi_inputs(tree, self.layout())
        self.assertIsNone(tree['strips'][0]['midi_input']['assignments'][0]['device'])
        self.assertEqual(tree['strips'][1]['midi_input']['assignments'][0]['device'], 'Example Keyboard')

    def test_bounded_embedded_archive_with_trailing_cst_data(self):
        payload = plistlib.dumps({'dictionary': {'layer': {'keyboardIndex': 1}}}, fmt=plistlib.FMT_BINARY)
        blob = b'CST header' + len(payload).to_bytes(4, 'little') + payload + b'trailing data'
        self.assertEqual(read_keyboard_layer(blob, inspector.parse_plist_bytes)['keyboardIndex'], 1)
        self.assertIsNone(read_keyboard_layer(b'CST' + (999999).to_bytes(4, 'little') + payload, inspector.parse_plist_bytes))
        self.assertIsNone(read_keyboard_layer(blob + blob, inspector.parse_plist_bytes))


if __name__ == '__main__':
    unittest.main()
