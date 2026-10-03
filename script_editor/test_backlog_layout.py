"""Real WTD regression, encrypted folder install/restore and ISO integration."""
import json,os,struct,tempfile,unittest,zlib
from pathlib import Path
from core import Corpus,EditProject
from backlog_layout import ENTRY,patch_backlog
from archive_patch import digest
from patcher import prepare_patch,install_patch
from iso_patcher import prepare_iso_patch,write_patched_iso
from vendor import sdat
from vendor.psarc import Psarc
from test_import_iso import mini_iso
from test_patch_features import mini_archive

ROOT=Path(__file__).resolve().parents[1]
TESTED=ROOT/'work/poc/backlog_margin_20260913'
TEMPLATE=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/General2d.psarc.sdat'


def layout_archive(path,layout):
    names=[ENTRY,'/unrelated'];values=['\n'.join(names).encode(),layout,b'preserved asset']
    blocks=[[zlib.compress(v[i:i+65536],9) for i in range(0,len(v),65536)] for v in values]
    blocks[0][0]+=bytes(4096)
    toc=32+len(values)*30+sum(map(len,blocks))*2;offset=toc;index=0;headers=[]
    for value,parts in zip(values,blocks):
        headers.append(bytes(16)+struct.pack('>I',index)+len(value).to_bytes(5,'big')+offset.to_bytes(5,'big'))
        index+=len(parts);offset+=sum(map(len,parts))
    flat=[b for parts in blocks for b in parts]
    path.write_bytes(b'PSAR'+struct.pack('>HH',1,4)+b'zlib'+struct.pack('>5I',toc,30,len(values),65536,0)+b''.join(headers)+b''.join(len(b).to_bytes(2,'big') for b in flat)+b''.join(flat))


def add_iso_archive(path,payload):
    raw=bytearray(path.read_bytes());name=b'GENERAL2D_PSARC.SDAT;1';n=33+len(name)+(len(name)%2==0);rec=bytearray(n);rec[0]=n
    sector=len(raw)//2048
    struct.pack_into('<I',rec,2,sector);struct.pack_into('>I',rec,6,sector)
    struct.pack_into('<I',rec,10,len(payload));struct.pack_into('>I',rec,14,len(payload))
    rec[18:25]=bytes([126,9,14,0,0,0,0]);rec[28:32]=b'\1\0\0\1';rec[32]=len(name);rec[33:33+len(name)]=name
    at=27*2048
    while raw[at]:at+=raw[at]
    raw[at:at+n]=rec;raw.extend(payload);raw.extend(bytes((-len(raw))%2048))
    struct.pack_into('<I',raw,16*2048+80,len(raw)//2048);struct.pack_into('>I',raw,16*2048+84,len(raw)//2048)
    path.write_bytes(raw)


class BacklogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=(TESTED/'windowdataMain.before.wtd').read_bytes()
        cls.after=(TESTED/'windowdataMain.wtd').read_bytes()
        cls.corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')

    def fixture(self,root):
        target=root/'game/USRDIR/PSARC';target.mkdir(parents=True)
        (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335')
        mini_archive(root/'logic.psarc')
        sdat.encrypt(root/'logic.psarc',target/'Logic.psarc.sdat',TEMPLATE,verbose=False)
        layout_archive(root/'layout.psarc',self.before)
        encrypted=target/'General2d.psarc.sdat';sdat.encrypt(root/'layout.psarc',encrypted,TEMPLATE,verbose=False)
        os.utime(encrypted,ns=(1461994388000000000,1461994388000000000))
        return target,EditProject(self.corpus,root/'project.json')

    def test_exact_user_tested_bytes_and_idempotence(self):
        actual,review=patch_backlog(self.before)
        self.assertEqual(actual,self.after);self.assertEqual(review['changed_widgets'],9)
        self.assertEqual(sum(a!=b for a,b in zip(self.before,actual)),9)
        self.assertEqual(patch_backlog(actual)[0],actual);self.assertTrue(patch_backlog(actual)[1]['already_applied'])
        native=ROOT/'work/poc/full_english_20260906/native_ui/General2d/Dat/Window/WindowToolData/windowdataMain.wtd'
        raw=native.read_bytes();patched,review=patch_backlog(raw)
        self.assertEqual(review['changed_widgets'],9);self.assertEqual(sum(a!=b for a,b in zip(raw,patched)),9)

    def test_unknown_geometry_version_and_truncation_rejected(self):
        _,review=patch_backlog(self.before);bad=bytearray(self.before)
        struct.pack_into('>H',bad,review['changes'][3]['offset'],700)
        for raw in (bytes(bad),b'BAD!'+self.before[4:],self.before[:910000]):
            with self.assertRaises(ValueError):patch_backlog(raw)

    def test_fix_only_folder_install_restore_and_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,project=self.fixture(root);archive=target/'General2d.psarc.sdat'
            before=digest(archive);stamp=archive.stat().st_mtime_ns;logic_before=digest(target/'Logic.psarc.sdat')
            manifest=prepare_patch(project,'en',[target],root/'build',keep_plain=True)
            doc=json.loads(manifest.read_text());self.assertEqual(doc['review'],[])
            self.assertEqual([a['name'] for a in doc['archives']],['General2d']);self.assertEqual(digest(archive),before)
            rebuilt=Psarc(root/'build/General2d.patched.psarc');entries={e.name:e for e in rebuilt.entries}
            self.assertEqual(rebuilt._read_file(entries[ENTRY]),self.after)
            self.assertEqual(rebuilt._read_file(entries['/unrelated']),b'preserved asset')
            install_patch(manifest,closed_check=lambda:None);self.assertEqual(archive.stat().st_mtime_ns,stamp)
            fixed=digest(archive);again=prepare_patch(project,'jp',[target],root/'again')
            self.assertEqual(json.loads(again.read_text())['archives'],[])
            with self.assertRaisesRegex(ValueError,'No game files'):install_patch(again,closed_check=lambda:None)
            self.assertEqual(digest(archive),fixed)
            install_patch(manifest,restore=True,closed_check=lambda:None)
            self.assertEqual(digest(archive),before);self.assertEqual(archive.stat().st_mtime_ns,stamp)
            self.assertEqual(digest(target/'Logic.psarc.sdat'),logic_before)
            self.assertFalse(project.path.exists())
            no_fix=prepare_patch(project,'en',[target],root/'disabled',backlog=False)
            self.assertEqual(json.loads(no_fix.read_text())['archives'],[])

    def test_fix_only_iso_and_no_changes_on_second_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,project=self.fixture(root);source=root/'source.iso';mini_iso(source,(target/'Logic.psarc.sdat').read_bytes())
            add_iso_archive(source,(target/'General2d.psarc.sdat').read_bytes());before=digest(source)
            manifest=prepare_iso_patch(project,'en',source,root/'build');output=root/'fixed.iso'
            result=write_patched_iso(manifest,output)
            self.assertTrue(result['source_preserved']);self.assertTrue(result['outside_archive_bytes_unchanged'])
            self.assertEqual(digest(source),before);self.assertEqual(source.stat().st_size,output.stat().st_size)
            again=prepare_iso_patch(project,'en',output,root/'again')
            self.assertTrue(json.loads(again.read_text())['layout_fixes'][0]['already_applied'])
            with self.assertRaisesRegex(ValueError,'no files'):write_patched_iso(again,root/'unused.iso')
            self.assertFalse((root/'unused.iso').exists())

    def test_editor_checkbox_persistence_review_and_already_fixed_state(self):
        from PySide6.QtWidgets import QApplication
        from app import Editor
        from dialogs import PatchDialog
        from core import atomic_json
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);editor=Editor(self.corpus,root/'project.json');dialog=PatchDialog(editor,root)
            self.assertTrue(dialog.backlog.isChecked());dialog.backlog.setChecked(False);dialog.save_settings();dialog.close()
            dialog=PatchDialog(editor,root);self.assertFalse(dialog.backlog.isChecked());dialog.backlog.setChecked(True)
            review=patch_backlog(self.after)[1]
            manifest=root/'patch.json';atomic_json(manifest,dict(archives=[],review=[],layout_fixes=[review]))
            dialog.built(manifest);dialog.busy(False)
            self.assertIsNone(dialog.manifest);self.assertFalse(dialog.install.isEnabled())
            self.assertEqual(dialog.model.rowCount(),1);self.assertIn('already applied',dialog.status.text())
            self.assertEqual(editor.project.count(),0);dialog.close();editor.close()


if __name__=='__main__':unittest.main()
