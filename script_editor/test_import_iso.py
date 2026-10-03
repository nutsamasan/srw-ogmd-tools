import copy
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from core import Corpus,EditProject,atomic_json,sha
from script_import import ScriptImporter
from iso_image import DiscImage
from iso_patcher import write_patched_iso
from archive_patch import digest
from PySide6.QtWidgets import QApplication
from app import Editor,STYLE,load_ui_fonts
from import_dialog import ImportDialog
from dialogs import PatchDialog

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan).iso'

def mini_iso(path,logic_payload=None):
    logic_payload=logic_payload if logic_payload is not None else b'NPD\0'.ljust(64,b'L')
    assert len(logic_payload)<=10*2048
    def record(name,sector,size,directory=False,multi=False):
        name=name if isinstance(name,bytes) else name.encode();n=33+len(name)+(len(name)%2==0);rec=bytearray(n);rec[0]=n
        struct.pack_into('<I',rec,2,sector);struct.pack_into('>I',rec,6,sector);struct.pack_into('<I',rec,10,size);struct.pack_into('>I',rec,14,size)
        rec[25]=(2 if directory else 0)|(128 if multi else 0);rec[28:32]=b'\1\0\0\1';rec[32]=len(name);rec[33:33+len(name)]=name;return rec
    data=bytearray(160*2048);pvd=bytearray(2048);pvd[:7]=b'\1CD001\1';struct.pack_into('<I',pvd,80,160);struct.pack_into('>I',pvd,84,160);pvd[128:132]=b'\0\x08\x08\0';pvd[156:190]=record(b'\0',24,2048,True);data[16*2048:17*2048]=pvd;data[17*2048:17*2048+7]=b'\xffCD001\1'
    for sector,records in [(24,[record('PS3_GAME',25,2048,True)]),(25,[record('PARAM.SFO;1',100,32),record('USRDIR',26,2048,True)]),(26,[record('PSARC',27,2048,True)]),(27,[record('LOGIC_PSARC.SDAT;1',110,len(logic_payload)),record('BATTLE_PSARC.SDAT;1',120,2048,multi=True),record('BATTLE_PSARC.SDAT;1',124,256)])]:
        content=b''.join(records);data[sector*2048:sector*2048+len(content)]=content
    data[100*2048:100*2048+32]=b'\0PSFBLJS10335'.ljust(32,b'\0');data[110*2048:110*2048+len(logic_payload)]=logic_payload
    data[120*2048:121*2048]=b'NPD\0'.ljust(2048,b'B');data[124*2048:124*2048+256]=b'C'*256
    path.write_bytes(data)

class ImportIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908');cls.key=cls.corpus.collections[0]['key'];cls.row=cls.corpus.load(cls.key)[0]['rows'][0]
        cls.app=QApplication.instance() or QApplication([]);load_ui_fonts();cls.app.setStyleSheet(STYLE)

    def test_full_corpus_original_json_and_text_are_noops(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json');imp=ScriptImporter(project)
            for fmt in ('script.json','EN.txt','JP.txt','Bilingual.txt'):
                result=imp.preview(self.corpus.root,fmt);self.assertEqual(result['files'],len(self.corpus.collections));self.assertEqual(result['plan'],[],fmt)
            self.assertFalse(project.path.exists())

    def test_export_import_both_languages_speakers_and_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);project=EditProject(self.corpus,tmp/'input.json')
            for field,text in [('en','Line one\n\nLine three\n'),('jp','確認\n次の行'),('speaker_en','Irm'),('speaker_jp','イルム')]:project.set(self.key,self.row,field,text)
            project.save();project.export(tmp/'export')
            for selection in [tmp/'export',tmp/'export'/'edits.json',tmp/'export'/self.key/'script.json',tmp/'export'/self.key/'Bilingual.txt']:
                imported=EditProject(self.corpus,tmp/'unused.json');imp=ScriptImporter(imported);plan=imp.preview(selection)['plan']
                self.assertEqual(len(plan),4,str(selection));imported.apply_replacements(plan);self.assertEqual(imported.data,project.data)
                imported.apply_replacements(plan,undo=True);self.assertEqual(imported.count(),0)
            for lang in ['EN','JP']:
                imported=EditProject(self.corpus,tmp/'unused.json');plan=ScriptImporter(imported).preview(tmp/'export',lang+'.txt')['plan']
                self.assertEqual({r['field'] for r in plan},{lang.lower(),'speaker_'+lang.lower()})

    def test_conflicts_source_reset_duplicate_metadata_and_stale_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);incoming=copy.deepcopy(self.corpus.load(self.key)[0]);incoming['rows']=incoming['rows'][:1];incoming['rows'][0]['en']='Imported text';atomic_json(tmp/'script.json',incoming)
            project=EditProject(self.corpus,tmp/'project.json');project.set(self.key,self.row,'en','Local edit');project.set(self.key,self.row,'jp','手動編集')
            imp=ScriptImporter(project);result=imp.preview(tmp/'script.json');self.assertEqual(len(result['plan']),1);self.assertEqual(result['conflicts'],1)
            resets=imp.preview(tmp/'script.json',include_source=True)['plan'];self.assertEqual(len(resets),2)
            snapshot=copy.deepcopy(project.data);project.apply_replacements(result['plan']);self.assertEqual(project.values(self.key,self.row)['jp'],'手動編集');project.apply_replacements(result['plan'],undo=True);self.assertEqual(project.data,snapshot)
            project.set(self.key,self.row,'en','Later edit');before=copy.deepcopy(project.data)
            with self.assertRaises(ValueError):project.apply_replacements(result['plan'])
            self.assertEqual(project.data,before)
            for mutation in ['unknown','duplicate','metadata','nul']:
                doc=copy.deepcopy(incoming)
                if mutation=='unknown':doc['rows'][0]['id']='BAD:999999'
                if mutation=='duplicate':doc['rows'].append(copy.deepcopy(doc['rows'][0]))
                if mutation=='metadata':doc['rows'][0]['command_offset']+=4
                if mutation=='nul':doc['rows'][0]['en']='bad\0text'
                atomic_json(tmp/'script.json',doc)
                with self.assertRaises(ValueError,msg=mutation):imp.preview(tmp/'script.json')
                self.assertEqual(project.data,before)
            (tmp/'duplicate.json').write_text('{"rows":[],"rows":[]}',encoding='utf8')
            with self.assertRaises(ValueError):imp.preview(tmp/'duplicate.json')

    def test_import_crlf_source_undo_restores_exact_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=next(k for k in self.corpus.by_key if 'S034_' in k);doc=copy.deepcopy(self.corpus.load(key)[0]);row=next(r for r in doc['rows'] if '\r' in (r.get('en') or ''))
            doc['rows']=[copy.deepcopy(row)];doc['rows'][0]['en']='Changed newline text';tmp=Path(tmp);atomic_json(tmp/'script.json',doc)
            p=EditProject(self.corpus,tmp/'project.json');plan=ScriptImporter(p).preview(tmp/'script.json')['plan'];p.apply_replacements(plan);p.apply_replacements(plan,undo=True)
            self.assertEqual(p.count(),0);self.assertEqual(p.values(key,row)['en'],row['en'])

    def test_iso_multi_extent_copy_and_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source.iso';mini_iso(source);original=source.read_bytes();native=tmp/'native';native.mkdir()
            payload=native/'Battle.psarc.sdat';payload.write_bytes(b'NPD\0'+b'X'*2300)
            with DiscImage(source) as iso:
                item=iso.file('/PS3_GAME/USRDIR/PSARC/Battle.psarc.sdat');self.assertEqual(len(item.extents),2);before=iso.checksum(item);extents=item.extents
            doc=dict(version=1,kind='ogmd-iso',status='ready',source=str(source),source_corpus=str(tmp/'corpus'),source_size=len(original),source_mtime_ns=source.stat().st_mtime_ns,source_sha256=digest(source),views=['ISO9660'],archives=[dict(name='Battle',file='native/Battle.psarc.sdat',before=before,after=digest(payload),size=2304)])
            manifest=tmp/'iso_patch.json';atomic_json(manifest,doc);output=tmp/'edited.iso';result=write_patched_iso(manifest,output)
            self.assertEqual(source.read_bytes(),original);expected=bytearray(original);at=0
            for offset,n in extents:expected[offset:offset+n]=payload.read_bytes()[at:at+n];at+=n
            self.assertEqual(output.read_bytes(),expected);self.assertTrue(result['outside_archive_bytes_unchanged'])
            for forbidden in [source,output]:
                with self.assertRaises(ValueError):write_patched_iso(manifest,forbidden)
            doc['source_sha256']='0'*64;atomic_json(manifest,doc)
            with self.assertRaises(ValueError):write_patched_iso(manifest,tmp/'invalid.iso')
            self.assertFalse((tmp/'invalid.iso').exists());self.assertFalse(list(tmp.glob('*.partial')))
            doc['source_sha256']=sha(original);atomic_json(manifest,doc);payload.write_bytes(b'bad')
            with self.assertRaises(ValueError):write_patched_iso(manifest,tmp/'invalid.iso')
            self.assertEqual(source.read_bytes(),original)

    def test_real_iso_all_views_and_udf_crc_guard(self):
        with DiscImage(SOURCE) as iso:
            self.assertEqual(set(iso.views),{'ISO9660','Joliet','UDF','UDF mirror'})
            items=[iso.file('/PS3_GAME/USRDIR/PSARC/'+a+'.psarc.sdat') for a in ('Logic','Common','Battle')];iso.check_patch_files(items)
            self.assertEqual(len(items[-1].extents),2)
        read=DiscImage.read
        def corrupt(obj,offset,size):
            b=read(obj,offset,size)
            if offset==352*2048 and size==2048:b=b[:56]+bytes([b[56]^1])+b[57:]
            return b
        with patch.object(DiscImage,'read',corrupt):
            with self.assertRaisesRegex(ValueError,'CRC'):DiscImage(SOURCE)

    def test_gui_import_merge_undo_and_iso_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);editor=Editor(self.corpus,tmp/'project.json');editor.show();self.app.processEvents()
            source=EditProject(self.corpus,tmp/'input.json');source.set(self.key,self.row,'en','GUI imported text');source.save()
            dialog=ImportDialog(editor);dialog.path.setText(str(source.path));dialog.previewed(ScriptImporter(editor.project).preview(source.path));self.assertTrue(dialog.apply.isEnabled())
            dialog.apply_import();self.assertEqual(editor.project.values(self.key,self.row)['en'],'GUI imported text');self.assertEqual(editor.editors['en'].toPlainText(),'GUI imported text')
            dialog.undo_import();self.assertEqual(editor.project.count(),0);dialog.close()
            patcher=PatchDialog(editor,tmp);patcher.mode.setCurrentIndex(1);patcher.show();self.app.processEvents()
            self.assertTrue(patcher.iso_group.isVisible());self.assertFalse(patcher.folder_group.isVisible());self.assertEqual(patcher.install.text(),'Create patched ISO');self.assertFalse(patcher.install.isEnabled())
            out=ROOT/'script_editor/qa';out.mkdir(exist_ok=True);patcher.grab().save(str(out/'iso_dialog_v3.png'));patcher.close();editor.close()

if __name__=='__main__':unittest.main()
