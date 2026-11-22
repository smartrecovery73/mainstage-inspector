# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
import unittest
from concert_features import enrich
from plugin_state import saved_bypass


def strip(name='Piano', alias=False):
    return {'name': name, 'is_alias': alias, 'metadata': {'Channel_isMuted': True, 'Channel_isSolo': False},
            'keyboard_layer': {'lowNote': 48, 'highNote': 72, 'lowVelocity': 1, 'highVelocity': 100, 'transpose': -12},
            'plugin_records': [{'name': '<Synth & Co>', 'source': 'test', 'presets': [{'name': 'A&B', 'role': 'Preset'}]}]}


class ConcertFeaturesTests(unittest.TestCase):
    def test_alias_counts_and_escaped_report(self):
        tree = {'name': 'Concert <1>', 'kind': 'Concert', 'strips': [strip(), strip('Alias', True)], 'children': []}
        enrich(tree)
        self.assertEqual(tree['summary']['plugins'][0]['instances'], 1)
        self.assertEqual(tree['summary']['plugins'][0]['references'], 2)
        self.assertEqual(tree['summary']['alias_count'], 1)
        self.assertNotIn('<Synth & Co>', tree['printable_report'])
        self.assertIn('&lt;Synth &amp; Co&gt;', tree['printable_report'])
        self.assertIn('A&amp;B', tree['printable_report'])
        self.assertIn('MUTE', tree['printable_report'])
        self.assertEqual(tree['strips'][0]['zone']['transpose'], -12)

    def test_invalid_zones_not_normalized_to_invented_range(self):
        item = strip(); item['keyboard_layer'].update(lowNote=90, highNote=10, lowVelocity=-1)
        tree = {'name': 'Concert', 'kind': 'Concert', 'strips': [item], 'children': []}
        enrich(tree)
        self.assertIsNone(item['zone']['low'])
        self.assertIsNone(item['zone']['high'])
        self.assertIsNone(item['zone']['velocity_low'])

    def test_bypass_guard_and_au_offset(self):
        prefix = bytearray(b'OCuA\x06\x00\x0e\x00' + bytes(40))
        prefix[40] = 1; prefix[46:48] = b'\2\2'
        data = bytes(prefix) + b'ValhallaS\0\0\0' + b'ODinxfuasMas'
        self.assertTrue(saved_bypass(data, {'offset': 60, 'type': 'aufx'}))
        self.assertTrue(saved_bypass(data, {'offset': 48}))
        self.assertIsNone(saved_bypass(b'XXXX' + data[4:], {'offset': 48}))
        prefix[40] = 3
        self.assertIsNone(saved_bypass(bytes(prefix) + data[48:], {'offset': 48}))


if __name__ == '__main__':
    unittest.main()
