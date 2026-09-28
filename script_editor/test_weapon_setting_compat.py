"""Text patches and the Save Editor's weapon tool must preserve each other's edits."""
import copy
from pathlib import Path
import sys
import unittest

from core import Corpus
from fixed_data import parse_fixed, structure_hash, structure_matches
from patcher import compile_entry

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT/'save_editor'))
from weapon_editor.weapon_data import WeaponSettings, prepare_weapons, read_weapons


class WeaponSettingCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/WeaponData.dat').read_bytes()
        cls.fixed = parse_fixed(cls.source)
        cls.start = cls.fixed.chunks[b'DATA'][0] + 12
        corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        cls.rows = corpus.load('06_Game_data/Weapon_names')[0]['rows']
        cls.row = next(r for r in cls.rows if r['id'] == 'WeaponData_name:0366')
        # Use the actual weapon tool to exercise every editable record and the
        # storage boundaries, including zero power/cost/ammo and range 255.
        cls.updates = {k:WeaponSettings(65535 if k % 2 else 0, 1 if k % 2 else 255,
                                       255, k % 256, 255-k % 256)
                       for k in read_weapons(cls.source)}
        cls.modified, _ = prepare_weapons(cls.source, cls.updates)

    def assert_rejected(self, source, row=None):
        with self.assertRaisesRegex(ValueError, 'Fixed (game records differ|record mapping changed)'):
            compile_entry(bytes(source), [dict(row=row or self.row, edits={'en':'Weapon test'})], 'en')

    def test_repeated_name_edits_preserve_all_custom_settings_and_other_records(self):
        source = self.modified
        before = parse_fixed(source)
        self.assertNotEqual(structure_hash(before, 'WeaponData'), self.row['fixed_structure_sha256'])
        selected = [r for r in self.rows if r['fixed_record'] in (1, self.row['fixed_record'], 855)]
        self.assertEqual({r['fixed_record'] for r in selected}, {1, self.row['fixed_record'], 855})
        allowed = {r['fixed_record'] for r in selected}
        for language, prefix in [('en', 'Weapon'), ('jp', '確認'), ('en', 'Revised')]:
            items = [dict(row=r, edits={language:prefix+' '+r['id']}) for r in selected]
            source, review = compile_entry(source, items, language)
            after = parse_fixed(source)
            self.assertEqual(len(review), len(items))
            self.assertEqual(after.logical_indices, before.logical_indices)
            self.assertEqual(len(after.records), len(before.records))
            for record, (old, new) in enumerate(zip(before.records, after.records)):
                if record in allowed:
                    self.assertEqual(old[:4]+old[6:], new[:4]+new[6:])
                else:
                    self.assertEqual(old, new)
            weapons = read_weapons(source)
            self.assertEqual({k:w.settings for k, w in weapons.items()}, self.updates)
            for item in items:
                self.assertEqual(weapons[item['row']['fixed_record']].installed_name, item['edits'][language])

    def test_weapon_defaults_restore_preserves_renamed_text(self):
        source, _ = compile_entry(self.modified, [dict(row=self.row, edits={'en':'Renamed weapon'})], 'en')
        restored, _ = prepare_weapons(source, {k:w.settings for k, w in read_weapons(self.source).items()})
        self.assertEqual(structure_hash(parse_fixed(restored), 'WeaponData'), self.row['fixed_structure_sha256'])
        self.assertEqual(read_weapons(restored)[self.row['fixed_record']].installed_name, 'Renamed weapon')
        self.assertEqual(parse_fixed(source).strings, parse_fixed(restored).strings)

    def test_unrelated_fields_and_dummy_record_remain_guarded(self):
        for record in (0, 5):
            for offset in range(84):
                if offset in (4, 5) or (record and offset in (12, 13, 14, 15, 20, 21)):
                    continue
                with self.subTest(record=record, offset=offset):
                    raw = bytearray(self.modified)
                    raw[self.start+record*84+offset] ^= 1
                    self.assert_rejected(raw)

    def test_zero_and_reversed_ranges_are_rejected(self):
        for record in (1, 855):
            for low, high in ((0, 1), (1, 0), (0, 0), (2, 1), (255, 254)):
                with self.subTest(record=record, low=low, high=high):
                    raw = bytearray(self.modified); off = self.start+record*84+14
                    raw[off:off+2] = bytes((low, high))
                    self.assert_rejected(raw)

    def test_mapping_count_unknown_fingerprint_and_row_mapping_are_rejected(self):
        # WeaponData uses implicit indices rather than a DOFS chunk.
        fixed = parse_fixed(self.modified)
        fixed.logical_indices[self.row['fixed_logical']] = self.row['fixed_record']+1
        self.assertFalse(structure_matches(fixed, 'WeaponData', self.row['fixed_structure_sha256']))
        fixed = parse_fixed(self.modified); fixed.records.append(fixed.records[-1])
        self.assertFalse(structure_matches(fixed, 'WeaponData', self.row['fixed_structure_sha256']))
        for field, value in [('fixed_structure_sha256', '0'*64),
                             ('fixed_record', self.row['fixed_record']+1)]:
            row = copy.deepcopy(self.row); row[field] = value
            self.assert_rejected(self.modified, row)


if __name__ == '__main__':
    unittest.main()
