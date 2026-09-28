"""Text patches must preserve supported built-in skill edits without weakening layout guards."""
import copy
import struct
import unittest
from pathlib import Path

from core import Corpus
from fixed_data import parse_fixed, structure_hash
from patcher import compile_entry

ROOT = Path(__file__).resolve().parents[1]


class UnitSkillCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/UnitData.dat').read_bytes()
        cls.fixed = parse_fixed(cls.source)
        corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        cls.rows = corpus.load('06_Game_data/Mech_names')[0]['rows']
        cls.row = next(r for r in cls.rows if r['id'] == 'UnitData_name:0140')
        cls.start = cls.fixed.chunks[b'DATA'][0] + 12

    def modified_skills(self):
        raw = bytearray(self.source)
        # Exercise every supported ID (including empty) in every slot, including
        # records unrelated to the name being edited. The guard covers the table.
        for record in range(1, len(self.fixed.records)):
            for slot in range(5):
                raw[self.start + record*216 + 0x46 + slot] = (record + slot) % 48
        return bytes(raw)

    def test_name_edits_preserve_all_custom_skills_and_other_records(self):
        source = self.modified_skills()
        before = parse_fixed(source)
        self.assertNotEqual(structure_hash(before, 'UnitData'), self.row['fixed_structure_sha256'])
        for language, text in [('en', 'Hagane'), ('jp', 'ハガネ'), ('en', 'Hagane revised')]:
            source, review = compile_entry(source, [dict(row=self.row, edits={language:text})], language)
            after = parse_fixed(source)
            self.assertEqual(len(review), 1)
            self.assertEqual(after.logical_indices, before.logical_indices)
            for record, (old, new) in enumerate(zip(before.records, after.records)):
                if record == self.row['fixed_record']:
                    self.assertEqual(old[:2] + old[4:], new[:2] + new[4:])
                else:
                    self.assertEqual(old, new)
            name = int.from_bytes(after.records[self.row['fixed_record']][2:4], 'big')
            self.assertEqual(after.strings[name], text)

    def test_other_record_bytes_remain_guarded_with_custom_skills(self):
        source = self.modified_skills()
        for offset in range(216):
            if offset in (2, 3, 6, 7) or 0x46 <= offset < 0x4B:
                continue
            with self.subTest(offset=offset):
                raw = bytearray(source)
                raw[self.start + 5*216 + offset] ^= 1
                with self.assertRaisesRegex(ValueError, 'Fixed game records differ'):
                    compile_entry(bytes(raw), [dict(row=self.row, edits={'en':'Hagane'})], 'en')

    def test_invalid_skills_and_changed_mapping_are_rejected(self):
        source = self.modified_skills()
        for value in (48, 255):
            for slot in range(5):
                raw = bytearray(source)
                raw[self.start + 5*216 + 0x46 + slot] = value
                with self.subTest(value=value, slot=slot), self.assertRaisesRegex(ValueError, 'Fixed game records differ'):
                    compile_entry(bytes(raw), [dict(row=self.row, edits={'en':'Hagane'})], 'en')
        raw = bytearray(source)
        offset = self.fixed.chunks[b'DOFS'][0] + 8 + 4*self.row['fixed_logical']
        struct.pack_into('>I', raw, offset, self.row['fixed_record'] + 1)
        with self.assertRaisesRegex(ValueError, 'Fixed game records differ'):
            compile_entry(bytes(raw), [dict(row=self.row, edits={'en':'Hagane'})], 'en')

    def test_unknown_corpus_fingerprint_and_row_mapping_are_rejected(self):
        for field, value in [('fixed_structure_sha256', '0'*64),
                             ('fixed_record', self.row['fixed_record'] + 1)]:
            row = copy.deepcopy(self.row)
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Fixed (game records differ|record mapping changed)'):
                compile_entry(self.modified_skills(), [dict(row=row, edits={'en':'Hagane'})], 'en')


if __name__ == '__main__':
    unittest.main()
