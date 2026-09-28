from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import zlib
import pilot_patch as core
import will_save as saves
from fixed_data import parse_fixed
from app import App, SPIRIT_LABELS, PROFILE_LABELS
from ui_dialogs import ReviewDialog
import will_behavior as behavior

ROOT = Path(__file__).resolve().parent.parent
FIXED = ROOT/'work/extracted/ps3_logic/Dat/FixedData'
PILOT = (FIXED/'PilotData.dat').read_bytes()
SPIRIT = (FIXED/'SpiritData.dat').read_bytes()
REAL_SAVE = Path('local_data/rpcs3/dev_hdd0/home/00000001/savedata/BLJS10335_OMI-SCN_EXAMPLE')


def make_archive(path):
    names = [core.PILOT_ENTRY, core.SPIRIT_ENTRY, '/unchanged.txt']
    payloads = ['\n'.join(names).encode(), PILOT, SPIRIT, b'Unrelated content\x00preserved']
    names = ['__manifest__']+names
    segments = [[zlib.compress(data[o:o+65536], 9) for o in range(0,len(data),65536)] for data in payloads]
    segments[0][0] += bytes(8192)
    count = sum(len(s) for s in segments)
    offset = 32+len(names)*30+count*2
    header = b'PSAR'+struct.pack('>HH4s5I', 1,4,b'zlib',offset,30,len(names),65536,0)
    toc, blocks, index = [], [], 0
    for name, data, segment in zip(names,payloads,segments):
        toc.append(hashlib.md5(name.encode()).digest()+struct.pack('>I',index)+len(data).to_bytes(5,'big')+offset.to_bytes(5,'big'))
        offset += sum(map(len,segment)); index += len(segment); blocks.extend(segment)
    path.write_bytes(header+b''.join(toc)+b''.join(len(b).to_bytes(2,'big') for b in blocks)+b''.join(blocks))
    return path


def changed(pilot, command=3):
    slots = list(pilot.settings.spirits)
    existing = {s.command for s in slots[1:5]}
    while command in existing:
        command += 1
    slots[0] = core.SpiritSlot(command, 15, 1, slots[0].flag if slots[0].command else 0)
    return core.PilotSettings((pilot.settings.personality+1)%12, tuple(slots))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.target = make_archive(self.folder/'Logic.psarc')

    def read(self):
        s = core.Session(self.target); self.addCleanup(s.close); return s

    def test_full_corpus_and_last_pilot_intended_bytes(self):
        s = self.read(); self.assertEqual(len(s.pilots),218)
        self.assertTrue(all(p.settings==p.defaults for p in s.pilots.values()))
        pids = (97,max(s.pilots)); updates = {pid:changed(s.pilots[pid]) for pid in pids}
        output, rows = core.prepare_pilot(PILOT,updates); f=parse_fixed(PILOT)
        allowed={f.chunks[b'DATA'][0]+12+f.logical_indices[pid]*336+off for pid in pids for off in core.EDIT_OFFSETS}
        actual={i for i,(a,b) in enumerate(zip(PILOT,output)) if a!=b}
        self.assertTrue(actual); self.assertLessEqual(actual,allowed); self.assertEqual(len(rows),2)

    def test_all_native_defaults_remain_restorable(self):
        s=self.read()
        updates={pid:replace(p.settings,personality=(p.settings.personality+1)%12) for pid,p in s.pilots.items()}
        output,_=core.prepare_pilot(PILOT,updates)
        restored,_=core.prepare_pilot(output,s.defaults())
        self.assertEqual(restored,PILOT)

    def test_invalid_values_rejected_without_writing(self):
        s=self.read(); p=s.pilots[97]; v=changed(p); bad=[]
        for personality in (12,-1,True,'1'):
            bad.append(replace(v,personality=personality))
        for cmd,cost,level in [(1,10,1),(255,10,1),(3,-1,1),(3,1000,1),(3,10,0),(3,10,100),(True,10,1)]:
            bad.append(replace(v,spirits=(core.SpiritSlot(cmd,cost,level),)+v.spirits[1:]))
        bad.append(replace(v,spirits=v.spirits[:4]))
        bad.append(replace(v,spirits=(v.spirits[1],)+v.spirits[1:]))
        original=core.snapshot(self.target)
        for value in bad:
            with self.subTest(value=value),self.assertRaises(core.PatchError):s.install({97:value})
        self.assertEqual(core.snapshot(self.target),original)
        self.assertFalse((self.folder/'_pilot_settings_backups').exists())

    def test_empty_and_twin_slots_roundtrip(self):
        s=self.read(); p=s.pilots[97]
        value=replace(p.settings,spirits=(core.SpiritSlot(0,65535,-1,-1),)+p.settings.spirits[1:5]+(core.SpiritSlot(43,10,1),))
        out,_=core.prepare_pilot(PILOT,{97:value})
        self.assertEqual(core.read_pilots(out)[97].settings,value)
        restore,_=core.prepare_pilot(out,{97:p.defaults}); self.assertEqual(restore,PILOT)

    def test_unknown_unlock_flag_is_preserved(self):
        s=self.read(); p=s.pilots[59]; slots=list(p.settings.spirits)
        slots[4]=replace(slots[4],cost=60)
        out,_=core.prepare_pilot(PILOT,{59:replace(p.settings,spirits=tuple(slots))})
        self.assertEqual(core.read_pilots(out)[59].settings.spirits[4].flag,-1)

    def test_wrong_game_layout_truncation_and_stats_rejected(self):
        f=parse_fixed(PILOT); b=bytearray(PILOT); b[f.chunks[b'DATA'][0]+12+336+0x15]^=1
        for raw in (b,PILOT[:-5],b'bad'):
            with self.subTest(size=len(raw)),self.assertRaises(core.PatchError):core.read_pilots(raw)

    def test_install_restore_defaults_preserve_size_timestamp_and_entries(self):
        s=self.read(); original=core.snapshot(self.target)
        receipt=s.install({97:changed(s.pilots[97])})
        self.assertEqual(core.snapshot(Path(receipt['backup'])),original)
        modified=self.read(); self.assertEqual(modified.original['size'],original['size'])
        self.assertEqual(modified.original['mtime_ns'],original['mtime_ns'])
        a,b=core.Psarc(s.plain),core.Psarc(modified.plain)
        differences=[x.name for x,y in zip(a.entries,b.entries) if a._read_file(x)!=b._read_file(y)]
        self.assertEqual(differences,[core.PILOT_ENTRY])
        modified.install(modified.defaults()); self.assertEqual(self.read().pilot,PILOT)

    def test_exact_backup_restore_and_newer_change_guard(self):
        s=self.read(); initial=core.snapshot(self.target)
        receipt=s.install({97:changed(s.pilots[97])}); modified=self.read()
        modified.restore_backup(receipt['manifest']); self.assertEqual(core.snapshot(self.target),initial)
        latest=self.read()
        with self.assertRaisesRegex(core.PatchError,'changed since'):latest.restore_backup(receipt['manifest'])

    def test_stale_source_lock_and_noop(self):
        s=self.read()
        with self.assertRaisesRegex(core.PatchError,'no pilot changes'):s.install(s.defaults())
        with core.target_lock(self.target),self.assertRaises(core.PatchError):s.install({97:changed(s.pilots[97])})
        with self.target.open('ab') as out:out.write(b'x')
        with self.assertRaisesRegex(core.PatchError,'changed after'):s.install({97:changed(s.pilots[97])})
        self.assertFalse((self.folder/'_pilot_settings_backups').exists())

    def test_write_failure_rolls_back(self):
        s=self.read(); before=core.snapshot(self.target); original=core.atomic_copy
        def fail(source,target,expected):
            original(source,target,expected)
            if target==self.target and expected!=before:raise OSError('injected readback error')
        with patch.object(core,'atomic_copy',side_effect=fail),self.assertRaises(OSError):s.install({97:changed(s.pilots[97])})
        self.assertEqual(core.snapshot(self.target),before)


class WillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.slot=Path(self.temp.name)/REAL_SAVE.name; shutil.copytree(REAL_SAVE,self.slot)

    def test_only_will_changes_full_backup_and_restore(self):
        before=saves.snapshot_slot(self.slot); raw=(self.slot/'PARMDAT.SAV').read_bytes(); pilots=saves.load_will(self.slot)
        updates={p.pilot.pilot_id:150 if p.will!=150 else 100 for p in (pilots[0],pilots[-1])}
        result=saves.write_will(self.slot,updates,expected_snapshot=before)
        self.assertEqual(saves.snapshot_slot(result.backup_path),before)
        allowed={saves.PILOT_RECORD_BASE+p.pilot.slot_index*saves.PILOT_RECORD_STRIDE+saves.WILL_OFFSET for p in (pilots[0],pilots[-1])}
        self.assertEqual({i for i,(a,b) in enumerate(zip(raw,(self.slot/'PARMDAT.SAV').read_bytes())) if a!=b},allowed)
        self.assertEqual({k for k in before if before[k]!=result.snapshot[k]},{'PARMDAT.SAV'})
        restored=saves.backup_will_updates(self.slot,result.backup_path)
        saves.write_will(self.slot,restored,expected_snapshot=result.snapshot)
        self.assertEqual(saves.snapshot_slot(self.slot),before)

    def test_last_record_255(self):
        data=bytearray((self.slot/'PARMDAT.SAV').read_bytes()); p=saves.load_will(self.slot)[0]
        source=saves.PILOT_RECORD_BASE+12+p.pilot.slot_index*72; dest=saves.PILOT_RECORD_BASE+12+255*72
        data[dest:dest+72]=data[source:source+72]; data[source:source+72]=bytes(72)
        (self.slot/'PARMDAT.SAV').write_bytes(data)
        result=saves.write_will(self.slot,{p.pilot.pilot_id:150})
        edited=next(x for x in result.pilots if x.pilot.pilot_id==p.pilot.pilot_id)
        self.assertEqual((edited.pilot.slot_index,edited.will),(255,150))

    def test_invalid_values_no_backup(self):
        p=saves.load_will(self.slot)[0]; before=saves.snapshot_slot(self.slot)
        for updates in ({p.pilot.pilot_id:49},{p.pilot.pilot_id:201},{p.pilot.pilot_id:True},{p.pilot.pilot_id:1.5},{9999:150},{}, {p.pilot.pilot_id:p.will}):
            with self.subTest(updates=updates),self.assertRaises(ValueError):saves.write_will(self.slot,updates)
        self.assertEqual(saves.snapshot_slot(self.slot),before)
        self.assertFalse((self.slot.parent/'_save_editor_backups').exists())

    def test_stale_unrelated_file_rejected(self):
        before=saves.snapshot_slot(self.slot); (self.slot/'SYSFLAG.SAV').write_bytes(b'newer progress')
        with self.assertRaisesRegex(ValueError,'changed after'):saves.write_will(self.slot,{97:150},expected_snapshot=before)

    def test_wrong_version_and_system_save_rejected(self):
        p=self.slot/'PARMDAT.SAV'; data=bytearray(p.read_bytes()); data[0x1bc2c]^=1; p.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'version'):saves.load_will(self.slot)
        bad=self.slot.with_name('BLJS10335_OMI-SYS'); self.slot.rename(bad)
        with self.assertRaises(ValueError):saves.load_will(bad)

    def test_readback_failure_rolls_back(self):
        before=saves.snapshot_slot(self.slot); original=saves.load_will; calls=0
        def fail(slot):
            nonlocal calls
            calls+=1
            if calls==2:raise ValueError('injected readback failure')
            return original(slot)
        with patch.object(saves,'load_will',side_effect=fail),self.assertRaisesRegex(ValueError,'injected'):
            saves.write_will(self.slot,{97:150})
        self.assertEqual(saves.snapshot_slot(self.slot),before)


class GuiTests(unittest.TestCase):
    def app_root(self):
        root=tk.Tk()
        def cleanup():
            for job in root.tk.call('after','info'):
                root.after_cancel(job)
            root.destroy()
        self.addCleanup(cleanup)
        return root

    def test_review_footer_visible_and_actions_guarded(self):
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(display_scale=scale):
                root=tk.Tk()
                try:
                    root.tk.call('tk', 'scaling', scale*96/72)
                    root.geometry('1080x740'); root.update()
                    called=[]
                    for label in ('Write archive changes', 'Save current Will', 'Restore archive backup'):
                        dialog=ReviewDialog(root, 'Review', 'A long review\n'*250, lambda:called.append(label), label)
                        for size in ('880x520', '620x340'):
                            dialog.geometry(size); root.update()
                            for widget in (dialog.checkbox, dialog.hint, dialog.write_button, dialog.cancel_button):
                                x=widget.winfo_rootx()-dialog.winfo_rootx()
                                y=widget.winfo_rooty()-dialog.winfo_rooty()
                                self.assertGreaterEqual(x,0); self.assertGreaterEqual(y,0)
                                self.assertLessEqual(x+widget.winfo_width(),dialog.winfo_width())
                                self.assertLessEqual(y+widget.winfo_height(),dialog.winfo_height())
                                self.assertGreaterEqual(widget.winfo_height(),widget.winfo_reqheight())
                                self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth())
                            self.assertLess(dialog.body.yview()[1],1, 'Long reviews must scroll')
                        self.assertTrue(dialog.write_button.instate(['disabled']))
                        dialog.write_button.invoke(); self.assertEqual(called,[])
                        dialog.checkbox.invoke(); self.assertTrue(dialog.write_button.instate(['!disabled']))
                        dialog.checkbox.invoke(); self.assertTrue(dialog.write_button.instate(['disabled']))
                        dialog.checkbox.invoke(); dialog.cancel_button.invoke(); self.assertEqual(called,[])
                    dialog=ReviewDialog(root,'Review','Safe callback test',lambda:called.append('confirmed'))
                    dialog.checkbox.invoke(); dialog.write_button.invoke()
                    self.assertEqual(called,['confirmed'])
                finally:
                    root.destroy()

    def test_profile_explanations_follow_selection_without_staging(self):
        root=self.app_root()
        app=App(root)
        for pid in core.PERSONALITIES:
            app.profile_var.set(PROFILE_LABELS[pid])
            self.assertEqual(app.profile_description.get(),behavior.summary(pid))
            self.assertTrue(behavior.EXPLANATIONS[pid])
        self.assertFalse(app.pending)
        guide=app.compare_profiles(); root.update(); guide.destroy()
        self.assertEqual(app.profile_var.get(),PROFILE_LABELS[11])

    def test_staging_selection_search_defaults_and_save(self):
        root=self.app_root()
        with tempfile.TemporaryDirectory() as temp:
            target=make_archive(Path(temp)/'Logic.psarc'); session=core.Session(target); self.addCleanup(session.close)
            app=App(root); app.loaded_archive(session); root.update()
            for pid in session.pilots:
                app.pilot_tree.selection_set(str(pid)); app.select_pilot()
            self.assertTrue(app.stage_archive())
            self.assertFalse(app.pending, 'Browsing pilots must not stage hidden native fields')
            app.pilot_tree.selection_set('97'); app.select_pilot(); root.update()
            app.cost_vars[0].set('15'); app.profile_var.set(PROFILE_LABELS[7])
            app.pilot_tree.selection_set('98'); app.select_pilot(); root.update()
            self.assertEqual(app.pending[97].spirits[0].cost,15)
            self.assertEqual(app.pending[97].personality,7)
            app.query.set('Akimi'); root.update(); self.assertEqual(app.pilot_tree.get_children(),('97',))
            app.query.set(''); app.pilot_tree.selection_set('97'); app.select_pilot(); app.defaults_selected()
            self.assertNotIn(97,app.pending)
            slot=Path(temp)/REAL_SAVE.name; shutil.copytree(REAL_SAVE,slot)
            app.save_var.set(str(slot)); app.read_save(); app.set_will(150)
            self.assertTrue(app.will_pending)
            before=saves.snapshot_slot(slot)
            with patch('app.messagebox.showinfo'):
                result=saves.write_will(slot,app.will_pending,expected_snapshot=app.save_snapshot); app.written_will(result)
            self.assertFalse(app.will_pending); self.assertNotEqual(before,app.save_snapshot)
            root.update()
            self.assertLessEqual(app.detail.winfo_y()+app.detail.winfo_height(),app.archive_tab.winfo_height())


if __name__=='__main__':unittest.main(verbosity=2)
