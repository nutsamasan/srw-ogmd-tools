"""Pilot name patches preserve supported gameplay edits and reject unrelated changes."""
import copy
import struct
import unittest
from pathlib import Path

from core import Corpus
from fixed_data import parse_fixed, structure_hash, SCHEMAS
from patcher import compile_entry

ROOT = Path(__file__).resolve().parents[1]


class PilotSettingCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/PilotData.dat').read_bytes()
        cls.fixed = parse_fixed(cls.source)
        cls.start = cls.fixed.chunks[b'DATA'][0] + 12
        corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        cls.rows = corpus.load('06_Game_data/Pilot_names')[0]['rows']
        cls.row = next(r for r in cls.rows if r['id'] == 'PilotData_short_name:0010')

    def modified_settings(self):
        raw = bytearray(self.source)
        # Exercise every profile and named command, empty slots, Twin commands,
        # both cost bytes, unlock boundaries, and the final physical record.
        for record in range(1, len(self.fixed.records)):
            base = self.start + record*336
            raw[base+0x13] = record % 12
            for slot in range(6):
                off = base + 0x72 + slot*6
                command = (record + slot) % 44
                if command < 2:
                    raw[off] = 0
                    raw[off+2:off+6] = b'\xff'*4
                else:
                    raw[off] = command
                    raw[off+2:off+4] = (999 if slot % 2 else 0).to_bytes(2, 'big')
                    raw[off+4] = 99 if slot % 2 else 1
                    raw[off+5] = 0
        return bytes(raw)

    def test_all_name_fields_preserve_gameplay_and_other_records_on_repeated_edits(self):
        source = self.modified_settings()
        before = parse_fixed(source)
        self.assertNotEqual(structure_hash(before, 'PilotData'), self.row['fixed_structure_sha256'])
        selected = [r for r in self.rows if r['fixed_logical'] == 10
                    or r['fixed_record'] == len(before.records)-1]
        self.assertEqual({r['fixed_field'] for r in selected}, set(SCHEMAS['PilotData'][1]))
        allowed = {(r['fixed_record'], i) for r in selected
                   for o, w in [SCHEMAS['PilotData'][1][r['fixed_field']]] for i in range(o, o+w)}
        for language, prefix in [('en', 'Pilot'), ('jp', '確認'), ('en', 'Revised')]:
            items = [dict(row=r, edits={language:prefix+' '+r['id']}) for r in selected]
            source, review = compile_entry(source, items, language)
            after = parse_fixed(source)
            self.assertEqual(len(review), len(items))
            self.assertEqual(after.logical_indices, before.logical_indices)
            self.assertEqual(len(after.records), len(before.records))
            for record, (old, new) in enumerate(zip(before.records, after.records)):
                for i, (a, b) in enumerate(zip(old, new)):
                    if (record, i) not in allowed:
                        self.assertEqual(a, b, (record, i))
            for item in items:
                r = item['row']; off, width = SCHEMAS['PilotData'][1][r['fixed_field']]
                index = int.from_bytes(after.records[r['fixed_record']][off:off+width], 'big')
                self.assertEqual(after.strings[index], item['edits'][language])

    def assert_rejected(self, source, row=None):
        with self.assertRaisesRegex(ValueError, 'Fixed (game records differ|record mapping changed)'):
            compile_entry(bytes(source), [dict(row=row or self.row, edits={'en':'Yung test'})], 'en')

    def test_other_fields_reserved_bytes_and_dummy_remain_guarded(self):
        source = self.modified_settings()
        text = {2, 3, 6, 7, 12, 13, 14, 15, 306, 307}
        settings = {0x13} | {o+i for o in range(0x72, 0x96, 6) for i in (0, 2, 3, 4, 5)}
        for record in (0, 5):
            for offset in range(336):
                if offset in text or (record and offset in settings):
                    continue
                with self.subTest(record=record, offset=offset):
                    raw = bytearray(source)
                    raw[self.start+record*336+offset] ^= 1
                    self.assert_rejected(raw)

    def test_invalid_profile_command_cost_level_and_condition_are_rejected(self):
        source = self.modified_settings()
        base = self.start + 5*336
        for value in (12, 255):
            raw = bytearray(source); raw[base+0x13] = value
            self.assert_rejected(raw)
        invalid = [(0, b'\x01'), (0, b'\x2c'), (0, b'\xff'), (0, b'\x00'),
                   (2, (1000).to_bytes(2, 'big')), (2, b'\xff\xff'),
                   (4, b'\x00'), (4, b'\x64'), (4, b'\xff'), (5, b'\x01'), (5, b'\xfe')]
        for slot in range(6):
            for offset, data in invalid:
                with self.subTest(slot=slot, offset=offset, data=data):
                    raw = bytearray(source); off = base+0x72+slot*6+offset
                    raw[off:off+len(data)] = data
                    self.assert_rejected(raw)

    def test_malformed_empty_slots_are_rejected(self):
        source = self.modified_settings()
        for slot in range(6):
            for relative in (2, 3, 4, 5):
                raw = bytearray(source); off = self.start+5*336+0x72+slot*6
                raw[off] = 0; raw[off+2:off+6] = b'\xff'*4
                raw[off+relative] = 0
                with self.subTest(slot=slot, relative=relative):
                    self.assert_rejected(raw)

    def test_native_conditions_and_defaults_survive_other_pilot_changes(self):
        # Stock has three populated command slots with condition -1.
        raw = bytearray(self.source)
        raw[self.start+5*336+0x13] = (raw[self.start+5*336+0x13]+1) % 12
        result, _ = compile_entry(bytes(raw), [dict(row=self.row, edits={'en':'Yung test'})], 'en')
        before, after = parse_fixed(raw), parse_fixed(result)
        self.assertEqual([r[0x13:] for r in before.records], [r[0x13:] for r in after.records])

    def test_mapping_count_unknown_fingerprint_and_row_mapping_are_rejected(self):
        source = self.modified_settings()
        raw = bytearray(source)
        offset = self.fixed.chunks[b'DOFS'][0]+8+4*self.row['fixed_logical']
        struct.pack_into('>I', raw, offset, self.row['fixed_record']+1)
        self.assert_rejected(raw)
        from fixed_data import structure_matches
        fixed = parse_fixed(source); fixed.records.append(fixed.records[-1])
        self.assertFalse(structure_matches(fixed, 'PilotData', self.row['fixed_structure_sha256']))
        for field, value in [('fixed_structure_sha256', '0'*64),
                             ('fixed_record', self.row['fixed_record']+1)]:
            row = copy.deepcopy(self.row); row[field] = value
            self.assert_rejected(source, row)


if __name__ == '__main__':
    unittest.main()
