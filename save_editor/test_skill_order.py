"""Reordering must preserve skill levels, growth, flags and unrelated save data."""
from dataclasses import replace
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import ogmd_save as core
import skill_progress as skill
import test_gui
import test_skill_progress


def kai_slots():
    return tuple(skill.SkillSlot(*pair) for pair in
                 ((11, 0), (17, 0), (41, 0), (23, 1), (22, 1), (10, 9)))


class SkillOrderTests(test_skill_progress.SkillProgressTests):
    # Reuse only setup; inherited tests are already run in their own class.
    pass


class OrderTests(unittest.TestCase):
    setUp = test_skill_progress.SkillProgressTests.setUp

    def pilot(self, level=11):
        return replace(core.load_pilots(self.slot)[0], pilot_id=29, experience=(level-1)*500)

    def totals(self, item, level):
        pilot = replace(item.pilot, experience=(level-1)*500)
        return {s.skill_id: s.learned_levels + skill.natural_levels(pilot, i, s.skill_id,
                disabled=bool(item.natural_disabled & (1 << i)))
                for i, s in enumerate(item.slots) if s.skill_id > 1 and skill.SKILLS[s.skill_id]['has_levels']}

    def test_kai_example_groups_sp_regen_without_changing_growth(self):
        original = skill.PilotSkills(self.pilot(), kai_slots(), 0b101000)
        moved = skill.move_skill(original, 4, 2)
        self.assertEqual([s.skill_id for s in moved.slots], [11, 17, 22, 41, 23, 10])
        self.assertEqual(moved.slots[-1], skill.SkillSlot(10, 9))
        for level in range(11, 100):
            self.assertEqual(self.totals(original, level), self.totals(moved, level))

    def test_ongoing_natural_growth_cannot_silently_disappear(self):
        original = skill.PilotSkills(self.pilot(), kai_slots(), 0b101000)
        with self.assertRaisesRegex(core.SaveFormatError, 'Commander.*future growth'):
            skill.move_skill(original, 0, 5)

    def test_finished_natural_growth_becomes_training_when_needed(self):
        original = skill.PilotSkills(self.pilot(35), kai_slots(), 0b101000)
        moved = skill.move_skill(original, 0, 5)
        self.assertEqual(moved.slots[5], skill.SkillSlot(11, 3))
        self.assertTrue(moved.natural_disabled & (1 << 5))
        for level in range(35, 100):
            self.assertEqual(self.totals(original, level), self.totals(moved, level))

    def test_saved_flag_controls_growth_even_for_replaced_id(self):
        pilot = self.pilot()
        self.assertEqual(skill.natural_levels(pilot, 0, 10, disabled=False), 1)
        self.assertEqual(skill.natural_levels(pilot, 0, 11, disabled=True), 0)

    def test_flag_only_write_preserves_other_bits_and_every_other_file(self):
        path = self.slot / core.PARMDAT_NAME
        payload = bytearray(path.read_bytes())
        start = core.PILOT_RECORD_BASE
        slots = (skill.SkillSlot(10, 9),) + (skill.SkillSlot(0, 0),) * 5
        payload[start+0x35:start+0x41] = bytes(v for s in slots for v in (s.skill_id, s.learned_levels))
        struct.pack_into('>I', payload, start+0x50, 0x01A5B680)
        path.write_bytes(payload)
        before = core.snapshot_slot(self.slot)
        result = skill.write_pilot_skills(self.slot, {0x35: slots}, natural_disabled_updates={0x35: 1}, expected_snapshot=before)
        self.assertEqual({i for i, (a, b) in enumerate(zip(payload, path.read_bytes())) if a != b}, {start+0x50})
        self.assertEqual(struct.unpack_from('>I', path.read_bytes(), start+0x50)[0], 0x05A5B680)
        self.assertEqual(core.snapshot_slot(result.backup_path), before)
        self.assertEqual(result.pilots[0].natural_disabled, 1)
        self.assertEqual({k: v for k, v in before.items() if k != core.PARMDAT_NAME},
                         {k: v for k, v in result.snapshot.items() if k != core.PARMDAT_NAME})

    def test_invalid_flags_do_not_write(self):
        before = core.snapshot_slot(self.slot)
        slots = skill.load_pilot_skills(self.slot)[0].slots
        for mask in (-1, 64, True, '1'):
            with self.subTest(mask=mask), self.assertRaises(core.SaveFormatError):
                skill.write_pilot_skills(self.slot, {0x35: slots}, natural_disabled_updates={0x35: mask})
        self.assertEqual(core.snapshot_slot(self.slot), before)


class OrderGuiTests(unittest.TestCase):
    setUp = test_gui.GuiTests.setUp
    close_root = test_gui.GuiTests.close_root

    def prepare(self):
        path = self.slot / core.PARMDAT_NAME
        payload = bytearray(path.read_bytes())
        struct.pack_into('>H', payload, core.PILOT_RECORD_BASE+0x0C, 29)
        struct.pack_into('>H', payload, core.PILOT_RECORD_BASE+0x14, 5000)
        start = core.PILOT_RECORD_BASE+0x35
        payload[start:start+12] = bytes(v for s in kai_slots() for v in (s.skill_id, s.learned_levels))
        struct.pack_into('>I', payload, core.PILOT_RECORD_BASE+0x50, 0xA0000080)
        path.write_bytes(payload)
        self.ui.load_selected()
        self.ui.notebook.select(4)
        self.ui.skill_tree.selection_set('29')
        self.root.deiconify()
        self.root.update()

    def drag(self, source, target):
        handle = self.ui.skill_handles[source]
        dest = self.ui.skill_boxes[target]
        handle.event_generate('<ButtonPress-1>', x=5, y=5)
        self.root.update()
        x, y = dest.winfo_rootx()+10, dest.winfo_rooty()+dest.winfo_height()//2
        handle.event_generate('<B1-Motion>', x=x-handle.winfo_rootx(), y=y-handle.winfo_rooty())
        handle.event_generate('<ButtonRelease-1>', x=x-handle.winfo_rootx(), y=y-handle.winfo_rooty())
        self.root.update()

    def test_actual_drag_stages_and_saves_in_order_with_training(self):
        self.prepare()
        before = core.snapshot_slot(self.slot)
        self.drag(4, 2)
        expected = [11, 17, 22, 41, 23, 10]
        self.assertEqual([s.skill_id for s in self.ui.pending_skills[29]], expected)
        self.assertEqual(core.snapshot_slot(self.slot), before)
        self.ui.search_var.set('SP Regen')
        self.root.update()
        self.assertIn(29, self.ui.pending_skills)
        with patch('skill_progress_ui.messagebox.askyesno', return_value=True), patch('skill_progress_ui.messagebox.showinfo'):
            self.ui.save_skills()
        after = skill.load_pilot_skills(self.slot)[0]
        self.assertEqual([s.skill_id for s in after.slots], expected)
        self.assertEqual(after.slots[-1].learned_levels, 9)
        self.assertEqual(self.ui.loaded_snapshot, core.snapshot_slot(self.slot))

    def test_drag_down_and_discard_restore_form_and_flags(self):
        self.prepare()
        self.drag(3, 5)
        self.assertEqual([s.skill_id for s in self.ui.pending_skills[29]], [11, 17, 41, 22, 10, 23])
        self.ui.discard_skills()
        self.root.update()
        self.assertFalse(self.ui.pending_skills)
        self.assertFalse(self.ui.pending_skill_masks)
        self.assertEqual(self.ui.skill_form_mask, 0b101000)
        self.assertEqual(self.ui.skill_vars[3].get(), skill.SKILLS[23]['name'])

    def test_blocked_drag_leaves_form_pending_and_save_unchanged(self):
        self.prepare()
        before = core.snapshot_slot(self.slot)
        with patch('skill_progress_ui.messagebox.showerror') as error:
            self.drag(0, 5)
        self.assertIn('future growth', error.call_args.args[1])
        self.assertFalse(self.ui.pending_skills)
        self.assertEqual(self.ui.skill_vars[0].get(), 'Commander')
        self.assertEqual(core.snapshot_slot(self.slot), before)

    def test_cancel_and_outside_drop_do_not_stage(self):
        self.prepare()
        handle = self.ui.skill_handles[4]
        handle.event_generate('<ButtonPress-1>', x=5, y=5)
        self.ui.cancel_skill_drag()
        handle.event_generate('<ButtonRelease-1>', x=5, y=-50)
        self.root.update()
        self.assertFalse(self.ui.pending_skills)
        handle.event_generate('<ButtonPress-1>', x=5, y=5)
        handle.event_generate('<ButtonRelease-1>', x=-100, y=5)
        self.root.update()
        self.assertFalse(self.ui.pending_skills)


if __name__ == '__main__':
    unittest.main()
