from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from test_ogmd_save import _make_slot
from ogmd_save import (SaveFormatError, snapshot_slot, write_pilot_stats, load_pilots,
                       PILOT_RECORD_BASE, PILOT_RECORD_STRIDE)
from pilot_status import (PilotStatus, load_status, natural_stats, totals, terrain_ratings,
                          from_totals, PROFILES, validate_status)
from save_editor import SaveEditor


def make_slot(root):
    slot = _make_slot(root)
    path = slot / 'PARMDAT.SAV'
    raw = bytearray(path.read_bytes())
    struct.pack_into('>f', raw, 0x1bc2c, 2.0)
    # Distinct neighboring bytes make overwrite errors visible.
    for index in (0, 1):
        start = PILOT_RECORD_BASE + index * PILOT_RECORD_STRIDE
        raw[start + 0x28:start + 0x2f] = bytes(range(7))
    path.write_bytes(raw)
    return slot


class StatusFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = make_slot(Path(self.temp.name))


class StatusTests(StatusFixture):
    def test_combined_write_only_changes_requested_fields_and_roundtrips(self):
        before = snapshot_slot(self.slot)
        raw = (self.slot / 'PARMDAT.SAV').read_bytes()
        statuses = load_status(self.slot)
        old = statuses[0x35]
        new = PilotStatus(49000, (21, 22, 23, 24, 25, 26), (1, 1, 2, 1))
        pilots = {p.pilot_id: p for p in load_pilots(self.slot)}
        result = write_pilot_stats(self.slot, status_updates={0x35: new}, pp_updates={0x36: 777},
                                   kill_updates={0x35: 999}, will_updates={0x36: 150}, expected_snapshot=before)
        self.assertEqual(load_status(self.slot)[0x35], new)
        self.assertEqual(load_status(self.slot)[0x36], statuses[0x36])
        self.assertEqual(snapshot_slot(result.backup_path), before)
        after = (self.slot / 'PARMDAT.SAV').read_bytes()
        start = PILOT_RECORD_BASE
        allowed = set(range(start + 0x12, start + 0x16)) | set(range(start + 0x18, start + 0x28))
        allowed |= {start + PILOT_RECORD_STRIDE + o for o in (0x16, 0x17, 0x2f)}
        self.assertTrue({i for i, (a, b) in enumerate(zip(raw, after)) if a != b} <= allowed)
        self.assertEqual({k:v for k,v in snapshot_slot(self.slot).items() if k != 'PARMDAT.SAV'},
                         {k:v for k,v in before.items() if k != 'PARMDAT.SAV'})
        write_pilot_stats(self.slot, status_updates={0x35: old}, pp_updates={0x36: pilots[0x36].pp},
                          kill_updates={0x35: pilots[0x35].kills}, will_updates={0x36: pilots[0x36].will})
        self.assertEqual(snapshot_slot(self.slot), before)

    def test_last_record_and_level_boundaries(self):
        path = self.slot / 'PARMDAT.SAV'
        raw = bytearray(path.read_bytes())
        start = PILOT_RECORD_BASE + 255 * PILOT_RECORD_STRIDE
        struct.pack_into('>H', raw, start + 0x0c, 0x3a)
        path.write_bytes(raw)
        for exp, level in ((0, 1), (499, 1), (500, 2), (48999, 98), (49000, 99), (65535, 99)):
            value = PilotStatus(exp, (0, 1, 2, 3, 4, 400), (0, 1, 2, 1))
            write_pilot_stats(self.slot, status_updates={0x3a: value})
            self.assertEqual(load_status(self.slot)[0x3a], value)
            self.assertEqual(value.level, level)

    def test_invalid_batches_rejected_before_backup(self):
        old = load_status(self.slot)[0x35]
        before = snapshot_slot(self.slot)
        for pid, value in [(0x35, replace(old, experience=-1)), (0x35, replace(old, experience=65536)),
            (0x35, replace(old, experience=True)), (0x35, replace(old, training=(0,) * 5)),
            (0x35, replace(old, training=(401,) * 6)), (0x35, replace(old, terrain_training=(-1,) * 4)),
            (0x35, replace(old, terrain_training=(True,) * 4)), (0x3a, old), (True, old)]:
            with self.subTest(pid=pid, value=value), self.assertRaises(SaveFormatError):
                write_pilot_stats(self.slot, status_updates={pid: value}, pp_updates={0x36: 999})
            self.assertEqual(snapshot_slot(self.slot), before)
        self.assertFalse((self.slot.parent / '_save_editor_backups').exists())

    def test_stale_save_and_rollback(self):
        old = load_status(self.slot)[0x35]
        snap = snapshot_slot(self.slot)
        (self.slot / 'extra.bin').write_bytes(b'changed')
        with self.assertRaises(SaveFormatError):
            write_pilot_stats(self.slot, status_updates={0x35: replace(old, experience=0)}, expected_snapshot=snap)
        snap = snapshot_slot(self.slot)
        with patch('pilot_status.load_status', side_effect=SaveFormatError('readback failure')):
            with self.assertRaisesRegex(SaveFormatError, 'readback failure'):
                write_pilot_stats(self.slot, status_updates={0x35: replace(old, experience=0)})
        self.assertEqual(snapshot_slot(self.slot), snap)

    def test_unknown_layout_blocks_status_without_blocking_pp(self):
        old = load_status(self.slot)[0x35]
        path = self.slot / 'PARMDAT.SAV'
        raw = bytearray(path.read_bytes())
        struct.pack_into('>f', raw, 0x1bc2c, 1.0)
        path.write_bytes(raw)
        with self.assertRaisesRegex(SaveFormatError, '2.0'):
            write_pilot_stats(self.slot, status_updates={0x35: old})
        write_pilot_stats(self.slot, pp_updates={0x35: 900})
        self.assertEqual(load_pilots(self.slot)[0].pp, 900)

    def test_totals_and_terrain_conversion_preserve_capped_training(self):
        old = PilotStatus(49000, (400,) * 6, (5,) * 4)
        same = from_totals(0x35, old, totals(0x35, old), terrain_ratings(0x35, old))
        self.assertEqual(old, same)
        fresh = load_status(self.slot)[0x35]
        new = from_totals(0x35, fresh, (400,) * 6, (5,) * 4)
        self.assertEqual(totals(0x35, new), (400,) * 6)
        self.assertEqual(terrain_ratings(0x35, new), (5,) * 4)
        self.assertEqual(new.terrain_training, (1, 1, 2, 1))
        with self.assertRaises(SaveFormatError):
            from_totals(0x35, fresh, (0,) * 6, (5,) * 4)
        with self.assertRaises(SaveFormatError):
            from_totals(0x35, fresh, totals(0x35, fresh), (0,) * 4)

    def test_all_catalog_curves_and_signed_growth_correction(self):
        for pid in PROFILES:
            last = natural_stats(int(pid), 49000)
            self.assertTrue(all(0 <= v <= 400 for v in last))
            for level in (1, 20, 50, 99):
                self.assertEqual(len(natural_stats(int(pid), (level-1)*500)), 6)
        data = {'stats': [{'base': 100, 'curve': [3] + [12] * 98, 'correction': -5}] * 6}
        with patch.dict(PROFILES, {'999': data}):
            self.assertEqual(natural_stats(999, 0), (101,) * 6)
            self.assertEqual(natural_stats(999, 49000), (107,) * 6)


class StatusGuiTests(StatusFixture):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.ui = SaveEditor(self.root)
        self.ui.folder_var.set(str(self.slot))
        self.ui.load_selected()
        self.ui.pilot_tree.selection_set('53')

    def test_dialog_level_sync_staging_search_write_and_skills_refresh(self):
        old = load_status(self.slot)[0x35]
        dialog = self.ui.edit_pilot_status()
        dialog.combat_vars[0].set(str(totals(0x35, old)[0] + 15))
        dialog.level_var.set('99')
        self.assertEqual(dialog.exp_var.get(), '49000')
        self.assertEqual(dialog.value.training[0], 15)
        dialog.exp_var.set('1000')
        self.assertEqual(dialog.level_var.get(), '3')
        dialog.max_terrain()
        dialog.apply()
        self.assertEqual(load_status(self.slot)[0x35], old)
        self.assertEqual(self.ui.pending_status[0x35].experience, 1000)
        self.ui.search_var.set('no match')
        self.root.update()
        self.ui.clear_search()
        self.root.update()
        self.assertIn('*', self.ui.pilot_tree.item('53', 'values')[0])
        self.ui.pending_pp[0x35] = 777
        with patch('save_editor.messagebox.askyesno', return_value=True), patch('save_editor.messagebox.showinfo'):
            self.ui.save_pilot_changes()
        self.assertEqual(load_status(self.slot)[0x35].experience, 1000)
        self.assertEqual(load_pilots(self.slot)[0].pp, 777)
        self.assertEqual(self.ui.skill_pilots[0x35].pilot.experience, 1000)
        self.assertFalse(self.ui.pending_status)
        self.assertEqual(self.ui.loaded_snapshot, snapshot_slot(self.slot))

    def test_invalid_input_cancel_discard_and_failed_reload(self):
        before = snapshot_slot(self.slot)
        dialog = self.ui.edit_pilot_status()
        dialog.exp_var.set('99999')
        dialog.apply()
        self.assertTrue(dialog.winfo_exists())
        self.assertFalse(self.ui.pending_status)
        dialog.destroy()
        self.ui.stage_status(0x35, replace(self.ui.pilot_status[0x35], experience=500))
        self.ui.discard_pending_pilots()
        self.assertFalse(self.ui.pending_status)
        self.ui.stage_status(0x35, replace(self.ui.pilot_status[0x35], experience=500))
        self.ui.pending_will[0x35] = 150
        self.ui.folder_var.set(str(self.slot / 'missing'))
        with patch('save_editor.messagebox.showerror'):
            self.ui.load_selected()
        self.assertFalse(self.ui.pending_status)
        self.assertFalse(self.ui.pending_will)
        self.assertFalse(self.ui.pilot_status)
        self.assertEqual(snapshot_slot(self.slot), before)


if __name__ == '__main__':
    unittest.main()
