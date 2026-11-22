# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
import plistlib
import unittest
from unittest.mock import patch

from plugin_state import arturia_title, embedded_au_states, enrich_records, preset_details, xml_state, zstd_state


class PluginStateTests(unittest.TestCase):
    def test_arturia_length_prefix_is_not_first_arbitrary_string(self):
        title = 'Factory Organ Sound'
        data = f'22 serialization::archive 10 0 7 0 7 {len(title)} {title} 7 Factory'.encode()
        self.assertEqual(arturia_title(data), title)
        self.assertIsNone(arturia_title(data.replace(str(len(title)).encode() + b' Factory', b'999 Rick')))
        self.assertIsNone(arturia_title(b'Preset named Factory Organ Sound'))

    def test_untitled_host_name_does_not_become_internal_preset(self):
        details = preset_details({'name': 'Untitled'}, 'Unknown', 'abcd')
        self.assertEqual(details['presets'], [])
        self.assertEqual(details['au_preset_name'], 'Untitled')

    def test_hammond_dirty_and_filename(self):
        details = preset_details({'jucePluginState': b'<State><CurrentPreset FileName="/bank/My Organ.b3xp" Dirty="1"/></State>'}, 'Ikmm', 'Hamm')
        self.assertEqual(details['presets'][0]['name'], 'My Organ')
        self.assertIs(details['presets'][0]['modified'], True)

    def test_omnisphere_part_is_not_a_nested_sample(self):
        xml = b'<SynthMaster><ENTRYDESCR name="Multi"/><SynthSubEngine><SynthEngine><SYNTHENG><ENTRYDESCR name="Choir"/><Sample><ENTRYDESCR name="Wrong sample"/></Sample></SYNTHENG></SynthEngine></SynthSubEngine></SynthMaster>\x00'
        details = preset_details({'data0': xml}, 'GOSW', 'Ambr')
        self.assertEqual([(p['role'], p['name']) for p in details['presets']], [('Multi', 'Multi'), ('Parte 1', 'Choir')])

    def test_juce_binary_header_and_preset(self):
        xml = b'<Echoes_Preset presetName="Timely Triple Delay"/>'
        binary = b'VC2!' + len(xml).to_bytes(4, 'little') + xml + b'\0'
        details = preset_details({'jucePluginState': binary}, 'AdTy', 'Er7e')
        self.assertEqual(details['presets'][0]['name'], 'Timely Triple Delay')
        self.assertIsNone(xml_state(b'VC2!\xff\xff\xff\xff' + xml))

    def test_vienna_current_preset_not_other_library_entries(self):
        with patch('plugin_state.zstd_state', return_value={'data': {'currentPreset': 'Bank/Space Organ', 'library': {'preset': 'Wrong'}}}):
            details = preset_details({'PluginState': b'opaque'}, 'VSLS', 'VIN0')
        self.assertEqual([p['name'] for p in details['presets']], ['Bank/Space Organ'])
        self.assertIsNone(zstd_state(b'not zstd'))
        self.assertIsNone(zstd_state(b'\x28\xb5\x2f\xfd' + b'corrupt'))

    def test_yamaha_performance_header_is_validated(self):
        body = b'CMAI' + b'padding' + b'DPFM' + (24).to_bytes(4, 'little') + b'\0\0\0\x15' + b'Space Organ'.ljust(20, b'\0')
        details = preset_details({'jucePluginState': body}, 'Ymau', 'anym')
        self.assertEqual(details['presets'][0]['name'], 'Space Organ')
        self.assertEqual(details['presets'][0]['role'], 'Performance')
        self.assertEqual(preset_details({'jucePluginState': body.replace(b'CMAI', b'XXXX')}, 'Ymau', 'anym')['presets'], [])

    def test_native_setting_does_not_claim_default_sound(self):
        record = {'name': 'Space Designer', 'source': 'record nativo GAME', 'offset': 106}
        data = b'Room.pst\0'.ljust(106, b'\0') + b'Space D'
        result = enrich_records(data, [record], {})[0]
        self.assertEqual(result['setting_name'], 'Room')
        self.assertEqual(result['presets'], [])
        data = b'#default.pst\0'.ljust(106, b'\0') + b'Space D'
        self.assertNotIn('setting_name', enrich_records(data, [record], {})[0])

    def test_association_requires_matching_au_identity_and_occurrence(self):
        def state(subtype, name):
            return plistlib.dumps({'type': int.from_bytes(b'aumu', 'big'), 'subtype': int.from_bytes(subtype, 'big'), 'manufacturer': int.from_bytes(b'Sopr', 'big'), 'SEPRESET': f'<Preset name="{name}"/>'})
        first = state(b'OPPU', 'First')
        second = state(b'OPPU', 'Second')
        data = b'ABCD' + first + b'EFGH' + second
        records = [dict(name='OP', source='firma AU', offset=0, type='aumu', subtype='OPPU', manufacturer='Sopr'), dict(name='OP', source='firma AU', offset=4+len(first), type='aumu', subtype='OPPU', manufacturer='Sopr')]
        result = enrich_records(data, records, {('aumu','OPPU','Sopr'): 'Full plugin name'})
        self.assertEqual([r['name'] for r in result], ['Full plugin name']*2)
        self.assertEqual([r['presets'][0]['name'] for r in result], ['First','Second'])
        records[1]['subtype']='WRNG'
        result = enrich_records(data, records, {})
        self.assertEqual(result[1]['presets'], [])
        self.assertEqual(len(list(embedded_au_states(data))),2)


if __name__ == '__main__':
    unittest.main()
