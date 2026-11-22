# Copyright (C) 2026 Luantani
# SPDX-License-Identifier: GPL-3.0-only
"""Regressioni del parser, eseguibili con python3 -m unittest -v."""
import contextlib
import io
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

import mainstage_inspector as inspector


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / 'Example.concert'
        self.root = self.package / 'Concert.patch'
        self.write_patch(self.root)
        self.registry = patch.object(inspector, '_AU', {})
        self.registry.start()
        self.addCleanup(self.registry.stop)

    def write_patch(self, directory, **data):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'data.plist').write_bytes(plistlib.dumps({'channels': [], 'patch': {}, **data}))

    def scan(self):
        return inspector.scan_concert(self.package)

    def test_saved_order_and_unlisted_folders(self):
        self.write_patch(self.root, nodes=['Z.patch', 'Missing.patch', 'A.patch', 'Z.patch'])
        for name in ['A.patch', 'Z.patch', 'Extra.patch']:
            self.write_patch(self.root / name)
        tree, _ = self.scan()
        self.assertEqual([n['name'] for n in tree['children']], ['Z', 'A', 'Extra'])
        warnings = '\n'.join(tree['warnings'])
        self.assertIn('Missing.patch', warnings)
        self.assertIn('duplicato', warnings)
        self.assertIn('aggiunta in coda', warnings)

    def test_empty_nodes_indicates_provisional_empty_set(self):
        self.write_patch(self.root, nodes=['Empty.patch'])
        self.write_patch(self.root / 'Empty.patch', nodes=[])
        child = self.scan()[0]['children'][0]
        self.assertEqual(child['kind'], 'Set')
        self.assertTrue(any('da validare' in w for w in child['warnings']))

    def test_arbitrary_directory_rejected(self):
        with self.assertRaises(ValueError):
            inspector.scan_concert(self.temp.name)

    def test_missing_and_corrupt_files_are_reported(self):
        self.write_patch(self.root, channels=[{'Filename': 'missing.cst', 'Channel_name': 'Piano'}],
                         nodes=['Broken.patch'])
        child = self.root / 'Broken.patch'
        child.mkdir()
        (child / 'data.plist').write_bytes(b'corrupt')
        tree, _ = self.scan()
        self.assertEqual(tree['strips'][0]['name'], 'Piano')
        self.assertTrue(tree['strips'][0]['warnings'])
        self.assertTrue(tree['children'][0]['warnings'])

    def test_channel_metadata_and_order(self):
        self.write_patch(self.root, channels=[
            {'Filename': 'Z.cst', 'Channel_name': 'First'},
            {'Filename': 'A.cst', 'Channel_name': 'Second'}])
        for filename in ['Z.cst', 'A.cst']:
            (self.root / filename).write_bytes(b'OCuA')
        self.assertEqual([s['name'] for s in self.scan()[0]['strips']], ['First', 'Second'])

    def test_hardware_never_leaks_between_concerts(self):
        layout = self.package / 'workspace.layout' / 'setupZ.layout'
        layout.parent.mkdir()
        layout.write_bytes(plistlib.dumps({'HardwareSetup': {'controllerMapping': {
            'Knob': {'MIDIPort': {'name': 'Unique Device'}, 'type': 5, 'controllerID': 11}
        }}}))
        tree, hardware = self.scan()
        self.assertIn('Unique Device', '\n'.join(hardware))
        second = Path(self.temp.name) / 'Second.concert'
        self.write_patch(second / 'Concert.patch', patch={'patchMappings': {'Knob': {'0': {}}}})
        tree, hardware = inspector.scan_concert(second)
        self.assertEqual(hardware, [])
        self.assertNotIn('Unique Device', '\n'.join(tree['controllers']))

    def test_internal_message_id_is_not_assumed_to_be_cc(self):
        _, lines = inspector.parse_hardware({'controllerMapping': {
            'Pad': {'type': 4, 'controllerID': 60, 'channelID': 0, 'MIDIPort': {'name': 'Keys'}}}})
        self.assertNotIn('CC 60', lines[0])
        self.assertIn('tipo MainStage 4', lines[0])
        self.assertIn('canale salvato 0', lines[0])

    def test_native_plugins_preserve_repeated_instances(self):
        record = b'\x02\x02Chan EQ\x00\x00\x00\x00\x00GAME\x00\x00\x00\x00'
        records = inspector.native_records(record + record)
        self.assertEqual([r['name'] for r in records], ['Channel EQ', 'Channel EQ'])
        self.assertLess(records[0]['offset'], records[1]['offset'])
        self.assertEqual(inspector.native_records(b'Preset with Chan EQ in its name'), [])

    def test_audio_units_preserve_repeated_instances(self):
        records = inspector.au_records(b'utrAumuafraF\x00' * 2)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['type'], 'aumu')
        self.assertEqual(records[0]['manufacturer'], 'Artu')

    def test_alias_resolves_to_original_in_other_patch(self):
        self.write_patch(self.root, nodes=['Original.patch', 'Alias.patch'])
        for name, is_alias in [('Original.patch', False), ('Alias.patch', True)]:
            self.write_patch(self.root / name, channels=[{
                'Filename': 'Instrument.cst', 'Channel_name': name, 'UUID': 'shared',
                'aliasUUID': 'shared', 'isAlias': is_alias}])
            (self.root / name / 'Instrument.cst').write_bytes(b'utrAumuafraF')
        tree, _ = self.scan()
        alias = tree['children'][1]['strips'][0]
        self.assertEqual(alias['alias_target']['node'], 'Original')
        self.assertEqual(len(alias['plugins']), 1)

    def test_unresolved_alias_is_reported(self):
        self.write_patch(self.root, channels=[{'Filename': 'A.cst', 'isAlias': True, 'aliasUUID': 'absent'}])
        strip = self.scan()[0]['strips'][0]
        self.assertTrue(any('Alias non risolto' in w for w in strip['warnings']))

    def test_keyed_archive_resolves_array_objects_and_rejects_invalid_uids(self):
        archive = {'$objects': ['$null', [plistlib.UID(2)], 'hello'], '$top': {'root': plistlib.UID(1)}}
        self.assertEqual(inspector.decode_keyed_archive(archive), {'root': ['hello']})
        archive['$top']['root'] = plistlib.UID(99)
        with self.assertRaises(ValueError):
            inspector.decode_keyed_archive(archive)

    def test_symlink_cycle_is_reported(self):
        (self.root / 'Loop.patch').symlink_to(self.root, target_is_directory=True)
        tree, _ = self.scan()
        self.assertTrue(any('ciclico' in w for w in tree['warnings']))

    def test_html_escapes_names_and_shows_warnings(self):
        self.write_patch(self.root, channels=[{'Filename': 'Missing.cst', 'Channel_name': '<script>bad</script>'}])
        html = inspector.render_page(str(self.package))
        self.assertNotIn('<script>bad</script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('File .cst non disponibile', html)

    def test_cli_failure_returns_nonzero(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            result = inspector.main([self.temp.name, '--cli', '--no-au-scan'])
        self.assertEqual(result, 1)
        self.assertIn('non valido', error.getvalue())

    def test_malformed_channel_metadata_keeps_node_visible(self):
        self.write_patch(self.root, channels='invalid')
        tree, _ = self.scan()
        self.assertTrue(any('channels non è una lista' in w for w in tree['warnings']))


if __name__ == '__main__':
    unittest.main()
