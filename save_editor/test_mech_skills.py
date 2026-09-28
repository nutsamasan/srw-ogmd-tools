"""Native shared-form behavior, inventory accounting, and multi-file recovery."""
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import ogmd_save as core
import mech_skills as feature
from save_editor import SaveEditor
from test_ogmd_save import _make_slot


def make_mechs(slot):
    path = slot/core.PARMDAT_NAME
    data = bytearray(path.read_bytes())
    data[8:12] = bytes.fromhex('40400000')
    for index, uid, equipment in [(0, 1, (1, 1, 2)), (255, 2, (1, 1, 2)), (1, 9, (3, 0, 0))]:
        word = feature.UNIT_MASK+index//32*4
        struct.pack_into('>I', data, word, struct.unpack_from('>I',data,word)[0] | (1 << (index%32)))
        base = feature.UNIT_BASE+index*feature.UNIT_STRIDE
        struct.pack_into('>H', data, base, uid)
        for j in range(3):
            struct.pack_into('>Hh', data, base+0x12+4*j, 0, -1)
        if index in (0,255):
            struct.pack_into('>Hh', data, base+0x12, 8, 255 if index==0 else 0)
        data[base+feature.EQUIPPED_OFFSET:base+feature.EQUIPPED_OFFSET+3] = bytes(equipment)
        struct.pack_into('>I', data, base+feature.FLAGS_OFFSET, 0xA5A50FDF)
    data[core.PILOT_RECORD_BASE+feature.PILOT_EQUIPPED_OFFSET] = 4
    path.write_bytes(data)
    path = slot/core.SYSDATA_NAME
    data = bytearray(path.read_bytes())
    counts = {1:2, 2:1, 3:1, 4:1}
    for aid in range(1,22):
        struct.pack_into('>H', data, core.ABILITY_AVAILABLE_OFFSET+(aid-1)*2, 5)
        struct.pack_into('>H', data, core.ABILITY_TOTAL_OFFSET+(aid-1)*2, 5+counts.get(aid,0))
    path.write_bytes(data)
    return slot


class MechSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = make_mechs(_make_slot(Path(self.temp.name)))

    def test_last_record_linked_forms_and_two_file_byte_boundaries(self):
        before = core.snapshot_slot(self.slot)
        original = {p.name:p.read_bytes() for p in self.slot.iterdir()}
        result = feature.write_mech_changes(self.slot, {255:(2,2,2)}, expected_snapshot=before)
        self.assertEqual(core.snapshot_slot(result.backup_path), before)
        allowed = {feature.UNIT_BASE+i*feature.UNIT_STRIDE+o for i in (0,255) for o in range(0x23,0x26)}
        data=(self.slot/core.PARMDAT_NAME).read_bytes()
        changed={i for i,(a,b) in enumerate(zip(original[core.PARMDAT_NAME],data)) if a!=b}
        self.assertTrue(changed)
        self.assertLessEqual(changed,allowed)
        self.assertEqual([m.equipped for m in result.mechs if m.slot_index in (0,255)],[(2,2,2)]*2)
        self.assertEqual(result.abilities[0].available,7)
        self.assertEqual(result.abilities[1].available,3)
        self.assertEqual([a.total_owned for a in result.abilities], [7,6,6,6]+[5]*17)
        allowed=set(range(core.ABILITY_AVAILABLE_OFFSET,core.ABILITY_AVAILABLE_OFFSET+4))
        data=(self.slot/core.SYSDATA_NAME).read_bytes()
        self.assertLessEqual({i for i,(a,b) in enumerate(zip(original[core.SYSDATA_NAME],data)) if a!=b},allowed)
        for name in original.keys()-{core.SYSDATA_NAME,core.PARMDAT_NAME}:
            self.assertEqual((self.slot/name).read_bytes(),original[name])

    def test_builtin_switch_preserves_other_bits_and_inventory(self):
        original=(self.slot/core.PARMDAT_NAME).read_bytes()
        before=core.snapshot_slot(self.slot)
        mech=next(m for m in feature.load_mechs(self.slot) if m.unit_id==9)
        self.assertEqual(mech.builtins,(7,0,0,0,0))
        enabled=(False,)+mech.enabled[1:]
        result=feature.write_mech_changes(self.slot,builtin_updates={1:enabled})
        actual=(self.slot/core.PARMDAT_NAME).read_bytes()
        off=feature.UNIT_BASE+feature.UNIT_STRIDE+feature.FLAGS_OFFSET
        self.assertEqual(struct.unpack_from('>I',actual,off)[0],0xA5A50F5F)
        self.assertEqual(actual[:off],original[:off])
        self.assertEqual(actual[off+4:],original[off+4:])
        self.assertEqual(result.snapshot[core.SYSDATA_NAME],before[core.SYSDATA_NAME])

    def test_invalid_requests_rejected_before_backup(self):
        before=core.snapshot_slot(self.slot)
        for updates in ({0:(22,0,0)}, {0:(True,0,0)}, {0:(1,2)}, {2:(1,2,3)}, {True:(1,2,3)}, {0:(2,2,2),255:(3,3,3)}):
            with self.subTest(updates=updates), self.assertRaises(core.SaveFormatError):
                feature.write_mech_changes(self.slot,updates)
        for switches in ((False,False,True,True,True), (0,True,True,True,True), (True,True)):
            with self.assertRaises(core.SaveFormatError):
                feature.write_mech_changes(self.slot,builtin_updates={1:switches})
        self.assertEqual(core.snapshot_slot(self.slot),before)
        self.assertFalse((self.slot.parent/'_save_editor_backups').exists())

    def test_insufficient_stock_and_inconsistent_inventory_rejected(self):
        path=self.slot/core.SYSDATA_NAME
        data=bytearray(path.read_bytes())
        struct.pack_into('>H',data,core.ABILITY_AVAILABLE_OFFSET+4,0)
        struct.pack_into('>H',data,core.ABILITY_TOTAL_OFFSET+4,1)
        path.write_bytes(data)
        before=core.snapshot_slot(self.slot)
        with self.assertRaisesRegex(core.SaveFormatError,'Not enough'):
            feature.write_mech_changes(self.slot,{0:(3,3,3)})
        self.assertEqual(core.snapshot_slot(self.slot),before)
        struct.pack_into('>H',data,core.ABILITY_TOTAL_OFFSET+4,2)
        path.write_bytes(data)
        with self.assertRaisesRegex(core.SaveFormatError,'do not match'):
            feature.write_mech_changes(self.slot,{0:(2,2,2)})

    def test_batch_transfer_uses_released_stock(self):
        path=self.slot/core.SYSDATA_NAME
        data=bytearray(path.read_bytes())
        for aid,count in {1:2,2:1,3:1,4:1}.items():
            struct.pack_into('>H',data,core.ABILITY_AVAILABLE_OFFSET+(aid-1)*2,0)
            struct.pack_into('>H',data,core.ABILITY_TOTAL_OFFSET+(aid-1)*2,count)
        path.write_bytes(data)
        result=feature.write_mech_changes(self.slot,{0:(3,0,0),1:(1,1,2)})
        self.assertEqual([a.available for a in result.abilities[:4]],[0]*4)

    def test_stale_snapshot_and_bad_links_rejected(self):
        before=core.snapshot_slot(self.slot)
        (self.slot/'SYSFLAG.SAV').write_bytes(b'external change')
        with self.assertRaisesRegex(core.SaveFormatError,'changed after'):
            feature.write_mech_changes(self.slot,{0:(2,2,2)},expected_snapshot=before)
        path=self.slot/core.PARMDAT_NAME
        data=bytearray(path.read_bytes())
        struct.pack_into('>h',data,feature.UNIT_BASE+0x14,254)
        path.write_bytes(data)
        with self.assertRaisesRegex(core.SaveFormatError,'unavailable form'):
            feature.load_mechs(self.slot)

    def test_rollback_after_second_file_write(self):
        before=core.snapshot_slot(self.slot)
        atomic=core._atomic_replace
        failed=False
        def fail_once(path,payload):
            nonlocal failed
            atomic(path,payload)
            if path.name==core.SYSDATA_NAME and not failed:
                failed=True
                raise OSError('simulated second-file readback failure')
        with patch('ogmd_save._atomic_replace',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'simulated'):
                feature.write_mech_changes(self.slot,{0:(2,2,2)})
        self.assertEqual(core.snapshot_slot(self.slot),before)

    def test_unknown_version_only_disables_mech_tab(self):
        path=self.slot/core.PARMDAT_NAME
        data=bytearray(path.read_bytes());data[8:12]=bytes(4);path.write_bytes(data)
        root=tk.Tk();root.withdraw()
        try:
            ui=SaveEditor(root);ui.folder_var.set(str(self.slot));ui.load_selected()
            self.assertEqual(ui.current_slot,self.slot)
            self.assertEqual(ui.mechs,{})
            self.assertIn('Unsupported mech record version',ui.mech_notice.get())
            self.assertTrue(ui.skill_pilots)
        finally:
            root.update();root.destroy()

    def test_gui_search_staging_shared_forms_save_and_inventory_refresh(self):
        root=tk.Tk();root.withdraw()
        try:
            ui=SaveEditor(root);ui.folder_var.set(str(self.slot));ui.load_selected();ui.notebook.select(6)
            ui.search_var.set('Beam Coat');root.update()
            self.assertEqual(ui.mech_tree.get_children(),('1',))
            ui.mech_tree.selection_set('1');ui.mech_selected()
            ui.mech_builtin_vars[0].set(False);ui.stage_mech_skills()
            ui.search_var.set('');root.update()
            ui.mech_tree.selection_set('255');ui.mech_selected()
            for v in ui.mech_ability_vars:v.set('Ranged')
            ui.stage_mech_skills()
            self.assertEqual(ui.pending_mech_equipped,{0:(2,2,2)})
            self.assertIn('*',ui.mech_tree.item('0','values')[0])
            with patch('mech_skills_ui.messagebox.askyesno',return_value=True), patch('mech_skills_ui.messagebox.showinfo'):
                ui.save_mech_skills()
            self.assertFalse(ui.pending_mech_equipped)
            self.assertFalse(ui.pending_mech_builtins)
            self.assertEqual(ui.abilities[1].available,7)
            self.assertEqual(ui.loaded_snapshot,core.snapshot_slot(self.slot))
            self.assertFalse(ui.mechs[1].enabled[0])
        finally:
            root.update();root.destroy()


if __name__=='__main__':
    unittest.main()
