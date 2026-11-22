# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
import unittest
import mainstage_inspector as inspector


class ControllerViewTests(unittest.TestCase):
    def test_target_range_and_assignment_belong_to_same_mapping(self):
        data = {'patch': {'patchMappings': {'\x01IDENTITY:Knob 1': {'\x01NUMBER:0': {
            'root': {'kGInstIDKey': 42, 'rangeLow': -10, 'rangeHigh': 10}}}}}, 'channels': []}
        hardware = [{'control': 'Knob 1', 'device': 'Keyboard', 'port': 'Port A', 'channel': 2,
                     'message_type': 5, 'controller_id': 11}]
        view = inspector.controller_view(data, hardware, {42: 'Lead'})
        mapping = view['mappings'][0]
        self.assertEqual(mapping['targets'][0]['name'], 'Lead')
        self.assertEqual(mapping['range_low'], -10)
        self.assertEqual(mapping['range_high'], 10)
        self.assertEqual(mapping['hardware']['port'], 'Port A')
        self.assertIsNone(inspector.controller_view(data, [], {})['mappings'][0]['hardware'])

    def test_rule_values_and_omitted_output_are_preserved(self):
        view = inspector.controller_view({'channels': [{'Channel_name': 'Lead', 'MIDITransform': {
            'transforms': [{'in': 0}, {'in': -7, 'filter': True}, {'in': 11, 'out': 1}]}}]}, [], {})
        rules = view['transforms'][0]['rules']
        self.assertEqual(rules[0]['input'], '0')
        self.assertIsNone(rules[0]['output'])
        self.assertFalse(rules[0]['filtered'])
        self.assertTrue(rules[1]['filtered'])
        self.assertEqual(rules[2]['output'], '1')

    def test_action_target_and_natural_order(self):
        mappings = {name: {'0': {'root': {'kGInstIDKey': 0, 'actionIndex': 3}}}
                    for name in ['Knob 10', 'Knob 2', 'Knob 1']}
        view = inspector.controller_view({'patch': {'patchMappings': mappings}}, [], {})
        self.assertEqual([m['control'] for m in view['mappings']], ['Knob 1', 'Knob 2', 'Knob 10'])
        self.assertEqual(view['mappings'][0]['targets'][0]['name'], 'Azione MainStage 3')


if __name__ == '__main__':
    unittest.main()
