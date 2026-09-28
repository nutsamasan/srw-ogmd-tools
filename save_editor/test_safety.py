"""Regression tests for Moon Dwellers widths and failure handling."""
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch
import ogmd_save as save
from test_ogmd_save import _make_slot


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = _make_slot(Path(self.temp.name))
        (self.slot / "SYSFLAG.SAV").write_bytes(b"preserve flags")
        (self.slot / "ICON0.PNG").write_bytes(b"preserve icon")

    def test_ability_unlock_and_16_bit_values_preserve_neighbor_bytes(self):
        path = self.slot / "SYSDATA.SAV"
        b = bytearray(path.read_bytes())
        for offset in (save.ABILITY_AVAILABLE_OFFSET, save.ABILITY_TOTAL_OFFSET):
            struct.pack_into(">H", b, offset, 0xFFFF)
        path.write_bytes(b)
        self.assertTrue(save.load_abilities(self.slot)[0].locked)
        before = save.snapshot_slot(self.slot)
        result = save.write_abilities(self.slot, {1: 12345}, expected_snapshot=before)
        self.assertEqual(save.snapshot_slot(result.backup_path), before)
        first = result.abilities[0]
        self.assertEqual((first.available, first.total_owned, first.equipped, first.locked), (12345, 12345, 0, False))
        changed = {i for i, (a, c) in enumerate(zip(b, path.read_bytes())) if a != c}
        self.assertEqual(changed, {0x56A, 0x56B, 0x68E, 0x68F})
        for offset in (save.ABILITY_AVAILABLE_OFFSET, save.ABILITY_TOTAL_OFFSET):
            self.assertEqual(path.read_bytes()[offset:offset+2], b"09")

    def test_inconsistent_locked_ability_rejected(self):
        path = self.slot / "SYSDATA.SAV"
        b = bytearray(path.read_bytes())
        struct.pack_into(">H", b, save.ABILITY_AVAILABLE_OFFSET, 0xFFFF)
        path.write_bytes(b)
        before = save.snapshot_slot(self.slot)
        with self.assertRaisesRegex(save.SaveFormatError, "mismatched"):
            save.write_abilities(self.slot, {1: 99})
        self.assertEqual(save.snapshot_slot(self.slot), before)

    def test_absent_sfo_funds_text_is_preserved(self):
        path = self.slot / "PARAM.SFO"
        doc = save._SfoDocument(path.read_bytes())
        doc.set_string("DETAIL", "●Route：Space")
        path.write_bytes(doc.to_bytes())
        before = save.snapshot_slot(self.slot)
        result = save.write_funds(self.slot, 1_000_000)
        after = save.snapshot_slot(self.slot)
        self.assertEqual(result.save.funds, 1_000_000)
        self.assertEqual({key for key in before if before[key] != after[key]}, {"SYSDATA.SAV"})
        self.assertEqual(save.snapshot_slot(result.backup_path), before)

    def test_stale_unrelated_file_blocks_write(self):
        expected = save.snapshot_slot(self.slot)
        (self.slot / "SYSFLAG.SAV").write_bytes(b"new game progress")
        before = save.snapshot_slot(self.slot)
        with self.assertRaisesRegex(save.SaveFormatError, "changed after"):
            save.write_funds(self.slot, 999999, expected_snapshot=expected)
        self.assertEqual(save.snapshot_slot(self.slot), before)
        self.assertFalse((self.slot.parent / "_save_editor_backups").exists())

    def test_save_changing_during_backup_is_not_edited(self):
        original_copy = save.shutil.copytree
        def mutate_during_copy(source, target):
            result = original_copy(source, target)
            (self.slot / "SYSFLAG.SAV").write_bytes(b"new game progress")
            return result
        original_sys = (self.slot / "SYSDATA.SAV").read_bytes()
        with patch.object(save.shutil, "copytree", side_effect=mutate_during_copy):
            with self.assertRaisesRegex(save.SaveFormatError, "during backup"):
                save.write_funds(self.slot, 999999)
        self.assertEqual((self.slot / "SYSDATA.SAV").read_bytes(), original_sys)

    def test_second_file_failure_rolls_back_first(self):
        before = save.snapshot_slot(self.slot)
        original_replace = save._atomic_replace
        injected = False
        def fail_once(path, payload):
            nonlocal injected
            if path.name == "PARAM.SFO" and not injected:
                injected = True
                raise OSError("simulated write failure")
            return original_replace(path, payload)
        with patch.object(save, "_atomic_replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated"):
                save.write_funds(self.slot, 999999)
        self.assertEqual(save.snapshot_slot(self.slot), before)
        backups = list((self.slot.parent / "_save_editor_backups").glob("*/" + self.slot.name))
        self.assertEqual(len(backups), 1)
        self.assertEqual(save.snapshot_slot(backups[0]), before)

    def test_lock_prevents_second_editor_write(self):
        lock = self.slot.parent / ("." + self.slot.name + ".editor-lock")
        lock.write_text("", encoding="utf8")
        before = save.snapshot_slot(self.slot)
        with self.assertRaisesRegex(save.SaveFormatError, "Another editor"):
            save.write_funds(self.slot, 999999)
        self.assertEqual(save.snapshot_slot(self.slot), before)

    def test_wrong_sizes_and_unknown_pilot_are_rejected(self):
        path = self.slot / "PARMDAT.SAV"
        original = path.read_bytes()
        path.write_bytes(original[:-1])
        with self.assertRaisesRegex(save.SaveFormatError, "137624"):
            save.write_pilot_stats(self.slot, pp_updates={0x35: 999})
        b = bytearray(original)
        struct.pack_into(">H", b, save.PILOT_RECORD_BASE + save.PILOT_ID_IN_RECORD, 0xFFFF)
        path.write_bytes(b)
        with self.assertRaisesRegex(save.SaveFormatError, "Unknown pilot"):
            save.load_pilots(self.slot)

    def test_all_moon_dwellers_weapon_types_and_high_upgrade_are_preserved(self):
        path = self.slot / "PARMDAT.SAV"
        b = bytearray(path.read_bytes())
        b[save.WEAPON_SLOT_BASE+1] = 0xF8
        path.write_bytes(b)
        before = save.load_weapons(self.slot)
        self.assertEqual(len(before), 53)
        result = save.write_weapon_totals(self.slot, {51: 4, 52: 4, 53: 4, 54: 4})
        by_id = {w.weapon_id: w for w in result.weapons}
        self.assertEqual(by_id[51].name, "Blade Railgun L")
        self.assertTrue(all(by_id[i].total_owned == 4 for i in range(51,55)))
        self.assertEqual(path.read_bytes()[save.WEAPON_SLOT_BASE:save.WEAPON_SLOT_BASE+9], b[save.WEAPON_SLOT_BASE:save.WEAPON_SLOT_BASE+9])


if __name__ == "__main__":
    unittest.main()
