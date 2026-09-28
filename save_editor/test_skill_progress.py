"""Byte boundaries, native growth rules, and guarded writes for the new fields."""
from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import ogmd_save as core
import skill_progress as feature
from test_ogmd_save import _make_slot
import test_gui


class SkillProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = _make_slot(Path(self.temp.name))

    def changed_slots(self):
        return (feature.SkillSlot(10, 9), feature.SkillSlot(5, 4),
                feature.SkillSlot(16, 1), feature.SkillSlot(22, 1),
                feature.SkillSlot(43, 1), feature.SkillSlot(0, 0))

    def test_skills_at_final_pilot_record_preserve_every_other_byte(self):
        path = self.slot / core.PARMDAT_NAME
        payload = bytearray(path.read_bytes())
        first, last = core.PILOT_RECORD_BASE, core.PILOT_RECORD_BASE + 255*72
        payload[last:last+72] = payload[first:first+72]
        payload[first:first+72] = bytes(72)
        path.write_bytes(payload)
        before = core.snapshot_slot(self.slot)
        result = feature.write_pilot_skills(self.slot, {0x35: self.changed_slots()}, expected_snapshot=before)
        actual = path.read_bytes()
        changed = {i for i, (a,b) in enumerate(zip(payload, actual)) if a != b}
        self.assertTrue(changed)
        self.assertLessEqual(changed, set(range(last+0x35, last+0x41)) | {last+0x50})
        self.assertEqual(actual[last+0x50] & 3, payload[last+0x50] & 3)
        self.assertEqual(core.snapshot_slot(result.backup_path), before)
        self.assertEqual({k:v for k,v in result.snapshot.items() if k != core.PARMDAT_NAME}, {k:v for k,v in before.items() if k != core.PARMDAT_NAME})
        self.assertEqual(next(p for p in result.pilots if p.pilot.pilot_id == 0x35).slots, self.changed_slots())

    def test_natural_skills_keep_room_for_growth(self):
        pilot = replace(core.load_pilots(self.slot)[0], pilot_id=0x71, experience=19483)
        self.assertEqual(feature.natural_levels(pilot, 1, 4), 6)
        self.assertEqual(feature.learned_limit(pilot, 1, 4), 3)
        self.assertEqual(feature.natural_levels(pilot, 0, 4), 0)
        self.assertEqual(feature.learned_limit(pilot, 0, 4), 9)
        original = (feature.SkillSlot(15,0), feature.SkillSlot(4,0), feature.SkillSlot(21,0)) + (feature.SkillSlot(0,0),)*3
        with self.assertRaises(core.SaveFormatError):
            feature.validate_skill_changes(pilot, original, (original[0], feature.SkillSlot(4,4), *original[2:]))

    def test_invalid_skills_never_write(self):
        before = core.snapshot_slot(self.slot)
        for invalid in [feature.SkillSlot(45,1), feature.SkillSlot(1,0), feature.SkillSlot(10,10), feature.SkillSlot(10,0), feature.SkillSlot(True,1), feature.SkillSlot(0,1)]:
            slots = (invalid,) + (feature.SkillSlot(0,0),)*5
            with self.subTest(invalid=invalid), self.assertRaises(core.SaveFormatError):
                feature.write_pilot_skills(self.slot, {0x35:slots})
        with self.assertRaises(core.SaveFormatError):
            feature.write_pilot_skills(self.slot, {0x35:(feature.SkillSlot(16,1),)*6})
        with self.assertRaises(core.SaveFormatError):
            feature.write_pilot_skills(self.slot, {999:self.changed_slots()})
        self.assertEqual(core.snapshot_slot(self.slot), before)
        self.assertFalse((self.slot.parent / "_save_editor_backups").exists())

    def test_count_changes_only_four_bytes_and_preserves_clear_flag(self):
        path = self.slot / core.SYSDATA_NAME
        payload = bytearray(path.read_bytes())
        struct.pack_into(">I", payload, feature.CLEAR_SAVE_OFFSET, 1)
        path.write_bytes(payload)
        before = core.snapshot_slot(self.slot)
        result = feature.write_completed_games(self.slot, 3, expected_snapshot=before)
        self.assertEqual(result.progress, feature.GameProgress(3, True))
        changed = {i for i,(a,b) in enumerate(zip(payload, path.read_bytes())) if a != b}
        self.assertTrue(changed)
        self.assertLessEqual(changed, set(range(0x2AC, 0x2B0)))
        self.assertEqual(core.snapshot_slot(result.backup_path), before)
        for name in before:
            if name != core.SYSDATA_NAME:
                self.assertEqual(result.snapshot[name], before[name])

    def test_invalid_counts_and_counter_bank_rejected(self):
        before = core.snapshot_slot(self.slot)
        for value in (-1,100,True,1.5,"2"):
            with self.subTest(value=value), self.assertRaises(core.SaveFormatError):
                feature.write_completed_games(self.slot,value)
        self.assertEqual(core.snapshot_slot(self.slot),before)
        path=self.slot/core.SYSDATA_NAME
        payload=bytearray(path.read_bytes())
        struct.pack_into(">I",payload,feature.COUNTER_SELECTOR_OFFSET,1)
        path.write_bytes(payload)
        with self.assertRaises(core.SaveFormatError):
            feature.write_completed_games(self.slot,2)

    def add_lap_metadata(self):
        path=self.slot/core.PARAM_SFO_NAME
        doc=core._SfoDocument(path.read_bytes())
        doc.set_string("DETAIL",doc.get_string("DETAIL") + "●Game Mode（Laps）：Normal（2）\n")
        path.write_bytes(doc.to_bytes())

    def test_existing_lap_metadata_updated_without_touching_other_text(self):
        self.add_lap_metadata()
        before=core.load_save(self.slot).detail
        feature.write_completed_games(self.slot,3)
        self.assertEqual(core.load_save(self.slot).detail,before.replace("Normal（2）","Normal（4）"))
        path=self.slot/core.PARAM_SFO_NAME
        doc=core._SfoDocument(path.read_bytes())
        doc.set_string("DETAIL",doc.get_string("DETAIL").replace("Game Mode（Laps）","ゲームモード（Ｌａｐｓ）"))
        path.write_bytes(doc.to_bytes())
        feature.write_completed_games(self.slot,99)
        self.assertIn("ゲームモード（Ｌａｐｓ）：Normal（99）",core.load_save(self.slot).detail)
        feature.write_completed_games(self.slot,0)
        self.assertIn("Normal（1）",core.load_save(self.slot).detail)

    def test_metadata_failure_rolls_back_count(self):
        self.add_lap_metadata()
        before=core.snapshot_slot(self.slot)
        real=feature._atomic_replace
        failed=False
        def fail_once(path,payload):
            nonlocal failed
            if path.name==core.PARAM_SFO_NAME and not failed:
                failed=True
                raise OSError("simulated metadata failure")
            return real(path,payload)
        with patch.object(feature,"_atomic_replace",side_effect=fail_once), self.assertRaises(OSError):
            feature.write_completed_games(self.slot,3)
        self.assertEqual(core.snapshot_slot(self.slot),before)

    def test_both_writers_reject_stale_snapshot(self):
        before=core.snapshot_slot(self.slot)
        (self.slot/"SYSFLAG.SAV").write_bytes(b"game wrote a new file")
        now=core.snapshot_slot(self.slot)
        for writer,args in [(feature.write_completed_games,(2,)),(feature.write_pilot_skills,({0x35:self.changed_slots()},))]:
            with self.assertRaises(core.SaveFormatError):
                writer(self.slot,*args,expected_snapshot=before)
        self.assertEqual(core.snapshot_slot(self.slot),now)

    def test_failed_skill_validation_rolls_back_bytes(self):
        before=core.snapshot_slot(self.slot)
        real=feature.load_pilot_skills
        calls=0
        def fail_after(slot):
            nonlocal calls
            calls+=1
            if calls==2: raise core.SaveFormatError("simulated readback failure")
            return real(slot)
        with patch.object(feature,"load_pilot_skills",side_effect=fail_after), self.assertRaises(core.SaveFormatError):
            feature.write_pilot_skills(self.slot,{0x35:self.changed_slots()})
        self.assertEqual(core.snapshot_slot(self.slot),before)


class FeatureGuiTests(unittest.TestCase):
    setUp = test_gui.GuiTests.setUp
    close_root = test_gui.GuiTests.close_root

    def test_stage_filter_save_and_completed_games(self):
        self.ui.notebook.select(4)
        self.ui.skill_tree.selection_set("53")
        self.root.update()
        self.ui.skill_vars[0].set("SP Up")
        self.ui.skill_choice_changed(0)
        self.ui.skill_level_vars[0].set("9")
        self.ui.stage_skills()
        self.assertIn(0x35,self.ui.pending_skills)
        self.ui.search_var.set("SP Up")
        self.root.update()
        self.assertEqual(self.ui.skill_tree.get_children(),("53",))
        with patch("skill_progress_ui.messagebox.askyesno",return_value=True),patch("skill_progress_ui.messagebox.showinfo"):
            self.ui.save_skills()
            self.ui.completed_var.set("2")
            self.ui.save_completed_games()
        self.assertFalse(self.ui.pending_skills)
        self.assertEqual(feature.load_pilot_skills(self.slot)[0].slots[0],feature.SkillSlot(10,9))
        self.assertEqual(feature.load_progress(self.slot).completed_games,2)
        self.assertEqual(self.ui.loaded_snapshot,core.snapshot_slot(self.slot))


if __name__ == "__main__":
    unittest.main()
