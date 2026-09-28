"""Weapon field, archive transaction, and UI regression checks on disposable files."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
from weapon_editor import weapon_patch as core
from weapon_editor import weapon_data as data
from weapon_editor.fixed_data import parse_fixed, rebuild_fixed

ROOT = Path(__file__).resolve().parent.parent
RAW = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/WeaponData.dat').read_bytes()
ENGLISH = (ROOT/'work/poc/full_english_20260906/fixed/WeaponData.dat').read_bytes()


def make_archive(path):
    names = [core.WEAPON_ENTRY, '/preserved/custom-pilot-skills.bin']
    payloads = ['\n'.join(names).encode(), RAW, bytes(range(256))*20]
    names = ['__manifest__']+names
    segments = [[zlib.compress(v[o:o+65536],9) for o in range(0,len(v),65536)] for v in payloads]
    segments[0][0] += bytes(8192)
    count = sum(len(s) for s in segments)
    offset = 32+len(names)*30+count*2
    header = b'PSAR'+struct.pack('>HH4s5I',1,4,b'zlib',offset,30,len(names),65536,0)
    toc,blocks,index=[],[],0
    for name,payload,segment in zip(names,payloads,segments):
        toc.append(hashlib.md5(name.encode()).digest()+struct.pack('>I',index)+len(payload).to_bytes(5,'big')+offset.to_bytes(5,'big'))
        offset+=sum(map(len,segment));index+=len(segment);blocks.extend(segment)
    path.write_bytes(header+b''.join(toc)+b''.join(len(b).to_bytes(2,'big') for b in blocks)+b''.join(blocks))
    return path


class WeaponFieldsTests(unittest.TestCase):
    def test_native_unsigned_load_instructions(self):
        raw=(ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0')
        # lhz r3,12(r3); lbz r3,14/15/20/21(r3), independently located native readers.
        for address,opcode in ((0x13b20c,0xa063000c),(0x13b068,0x8863000e),
                              (0x13b044,0x8863000f),(0x13b020,0x88630014),(0x13affc,0x88630015)):
            self.assertEqual(struct.unpack_from('>I',raw,address-0x10000)[0],opcode)

    def test_catalog_all_defaults_and_translations(self):
        weapons=data.read_weapons(RAW)
        self.assertEqual(len(weapons),855)
        self.assertEqual(sum(w.unit==0 for w in weapons.values()),53)
        self.assertTrue(all(w.settings==w.defaults for w in weapons.values()))
        translated=data.read_weapons(ENGLISH)
        self.assertEqual({k:w.settings for k,w in weapons.items()},{k:w.settings for k,w in translated.items()})
        self.assertEqual(translated[1].installed_name,'G Impact Stake')

    def test_boundary_fields_first_and_last_no_other_bytes(self):
        keys=(1,855)
        updates={1:data.WeaponSettings(65535,1,255,255,254),855:data.WeaponSettings(0,255,255,0,0)}
        result,changes=data.prepare_weapons(ENGLISH,updates)
        fixed=parse_fixed(ENGLISH);base=fixed.chunks[b'DATA'][0]+12
        allowed={base+k*84+o for k in keys for o in (12,13,14,15,20,21)}
        self.assertLessEqual({i for i,(a,b) in enumerate(zip(result,ENGLISH)) if a!=b},allowed)
        self.assertEqual(result[base+84+12:base+84+16],b'\xff\xff\x01\xff')
        self.assertEqual(result[base+84+20:base+84+22],b'\xfe\xff')
        self.assertEqual(len(changes),2)
        restored,_=data.prepare_weapons(result,{k:data.read_weapons(ENGLISH)[k].settings for k in keys})
        self.assertEqual(restored,ENGLISH)

    def test_invalid_values_and_dummy_rejected(self):
        valid=data.WeaponSettings(5000,1,7,0,20)
        for field,bad in [('power',-1),('power',65536),('minimum_range',0),('maximum_range',256),
                          ('en_cost',256),('ammo',-1),('ammo',True),('power',1.5),('power','4000'),('minimum_range',8)]:
            with self.subTest(field=field,bad=bad),self.assertRaises(data.PatchError):
                data.prepare_weapons(RAW,{1:replace(valid,**{field:bad})})
        for key in (0,-1,856,True,'1'):
            with self.subTest(key=key),self.assertRaises(data.PatchError):data.prepare_weapons(RAW,{key:valid})

    def test_all_defaults_restore_after_all_records_edited(self):
        weapons=data.read_weapons(RAW)
        changed,_=data.prepare_weapons(RAW,{k:data.WeaponSettings(60000,2,250,251,252) for k in weapons})
        restored,_=data.prepare_weapons(changed,{k:w.defaults for k,w in weapons.items()})
        self.assertEqual(restored,RAW)

    def test_strict_unrelated_bytes_and_layout(self):
        base=parse_fixed(RAW).chunks[b'DATA'][0]+12
        for offset in (0,2,8,10,16,18,22,27,50,83):
            raw=bytearray(RAW);raw[base+84+offset]^=1
            with self.subTest(offset=offset),self.assertRaises(data.PatchError):data.read_weapons(raw)
        for raw in (RAW[:-1],b'bad data'):
            with self.assertRaises(data.PatchError):data.read_weapons(raw)

    def test_custom_name_and_unrelated_text_are_preserved(self):
        f=parse_fixed(ENGLISH)
        raw=rebuild_fixed(f,{},[(1,4,2,'Custom G Impact Stake')])
        weapons=data.read_weapons(raw)
        out,_=data.prepare_weapons(raw,{1:replace(weapons[1].settings,power=54321)})
        self.assertEqual(data.read_weapons(out)[1].installed_name,'Custom G Impact Stake')
        self.assertEqual(parse_fixed(out).strings,parse_fixed(raw).strings)


class WeaponArchiveTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name);self.target=make_archive(self.folder/'Logic.psarc')

    def read(self):
        session=core.Session(self.target);self.addCleanup(session.close);return session

    def update(self,session):
        return {1:replace(session.weapons[1].settings,power=65000,en_cost=25,ammo=99)}

    def test_exact_backup_restore_size_timestamp_and_unrelated_entries(self):
        first=self.read();before=first.original
        receipt=first.install(self.update(first));modified=self.read()
        self.assertEqual(modified.weapons[1].settings,self.update(first)[1])
        self.assertEqual(core.snapshot(Path(receipt['backup'])),before)
        self.assertEqual(modified.original['size'],before['size'])
        self.assertEqual(modified.original['mtime_ns'],before['mtime_ns'])
        a,b=core.Psarc(first.plain),core.Psarc(modified.plain)
        self.assertEqual([x.name for x,y in zip(a.entries,b.entries) if a._read_file(x)!=b._read_file(y)],[core.WEAPON_ENTRY])
        modified.restore_backup(receipt['manifest']);self.assertEqual(core.snapshot(self.target),before)

    def test_defaults_restore_only_weapon_entry(self):
        first=self.read();first.install(self.update(first));modified=self.read()
        modified.install(modified.defaults());self.assertEqual(self.read().weapon,RAW)

    def test_stale_read_lock_noop_and_invalid_write(self):
        session=self.read();before=session.original
        with self.assertRaisesRegex(core.PatchError,'no weapon changes'):session.install(session.defaults())
        with core.target_lock(self.target),self.assertRaises(core.PatchError):session.install(self.update(session))
        with self.assertRaises(core.PatchError):session.install({1:data.WeaponSettings(100000,1,7,0,0)})
        self.assertEqual(core.snapshot(self.target),before)
        with self.target.open('ab') as out:out.write(b'x')
        with self.assertRaisesRegex(core.PatchError,'changed after'):session.install(self.update(session))
        self.assertFalse((self.folder/'_weapon_settings_backups').exists())

    def test_restore_refuses_newer_archive_or_wrong_target(self):
        first=self.read();receipt=first.install(self.update(first));second=self.read()
        second.install({2:replace(second.weapons[2].settings,en_cost=20)});latest=self.read()
        with self.assertRaisesRegex(core.PatchError,'changed since'):latest.restore_backup(receipt['manifest'])
        document=json.loads(Path(receipt['manifest']).read_text(encoding='utf8'))
        document['target']=str(self.folder/'elsewhere/Logic.psarc')
        fake=self.folder/'wrong.json';fake.write_text(json.dumps(document),encoding='utf8')
        with self.assertRaisesRegex(core.PatchError,'different archive'):latest.restore_backup(fake)

    def test_failure_after_replacement_rolls_back(self):
        session=self.read();before=session.original;original=core.atomic_copy
        def fail(source,target,expected):
            original(source,target,expected)
            if target==self.target and expected!=before:raise OSError('injected readback failure')
        with patch.object(core,'atomic_copy',side_effect=fail),self.assertRaises(OSError):session.install(self.update(session))
        self.assertEqual(core.snapshot(self.target),before)
        receipt=next((self.folder/'_weapon_settings_backups').glob('*/patch.json'))
        self.assertEqual(json.loads(receipt.read_text(encoding='utf8'))['status'],'rolled-back')


class WeaponUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from weapon_editor.ui import WeaponEditor
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.window=WeaponEditor(self.root)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        session=core.Session(make_archive(Path(temp.name)/'Logic.psarc'));self.addCleanup(session.close)
        # Avoid writing local preferences in unit tests.
        self.window.session=session;self.window.populate()

    def test_filter_edit_stage_and_review_guard(self):
        from weapon_editor.ui import SettingsDialog
        from weapon_editor.ui_dialogs import ReviewDialog
        window=self.window;window.filter.set('Equippable only')
        self.assertEqual(len(window.tree.get_children()),53)
        window.tree.selection_set('1');window.edit_selected()
        dialog=next(c for c in window.winfo_children() if isinstance(c,SettingsDialog))
        dialog.values['power'].set('65536');dialog.apply_button.invoke()
        self.assertTrue(dialog.winfo_exists());self.assertFalse(window.pending)
        dialog.values['power'].set('65000');dialog.values['en_cost'].set('0');dialog.apply_button.invoke()
        self.assertEqual(window.pending[1].power,65000)
        window.review();review=next(c for c in window.winfo_children() if isinstance(c,ReviewDialog))
        self.assertTrue(review.write_button.instate(['disabled']))
        self.assertIn('65,000',review.body.get('1.0','end'))
        review.stopped.set(True);review.update_ready();self.assertTrue(review.write_button.instate(['!disabled']))
        review.destroy();self.assertEqual(window.pending[1].power,65000)
        window.all_defaults();self.assertFalse(window.pending)

    def test_busy_window_cannot_close(self):
        self.window.busy=True
        with patch('weapon_editor.ui.messagebox.showinfo'):
            self.assertFalse(self.window.request_close())
        self.assertTrue(self.window.winfo_exists())


if __name__=='__main__':unittest.main()
