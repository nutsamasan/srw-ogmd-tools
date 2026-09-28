"""Full-corpus mapping checks and isolated patch/install/restore regressions."""
import copy
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from core import Corpus,EditProject,atomic_json,sha
from patcher import collect_changes,compile_entry,install_patch,prepare_patch,default_targets
from target_selection import installed_target
from archive_patch import repack,digest
from vendor.psarc import Psarc
from native_formats import parse_ldbi_table,read_cstring,parse_bmd,parse_csb
from PySide6.QtWidgets import QApplication
from app import Editor,STYLE,load_ui_fonts
from dialogs import SearchDialog,PatchDialog

ROOT=Path(__file__).resolve().parents[1]
CORPUS=ROOT/'script_export/OGMD_EN_JP_20260908'
BASE=ROOT/'work/poc/full_english_20260906/archives'


def mini_archive(path):
    names=['/one','/two','/alias'];values=['\n'.join(names).encode(),b'Original text',b'Other asset '*300]
    raw=[zlib.compress(x) for x in values];raw[1]+=bytes(200)
    toc=32+4*30+3*2;offset=toc;headers=[]
    for i,value in enumerate(values):
        headers.append(bytes(16)+struct.pack('>I',i)+len(value).to_bytes(5,'big')+offset.to_bytes(5,'big'));offset+=len(raw[i])
    headers.append(headers[2])
    path.write_bytes(b'PSAR'+struct.pack('>HH',1,4)+b'zlib'+struct.pack('>5I',toc,30,4,65536,0)+b''.join(headers)+b''.join(len(x).to_bytes(2,'big') for x in raw)+b''.join(raw))


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=Corpus(CORPUS)
        cls.app=QApplication.instance() or QApplication([]);load_ui_fonts();cls.app.setStyleSheet(STYLE)

    def test_bulk_full_corpus_literal_undo_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json')
            plan=project.find_all('E-Selda',r'New\name',('en','jp'),True,True)
            self.assertGreater(len({x['key'] for x in plan}),1)
            before=copy.deepcopy(project.data);project.apply_replacements(plan)
            self.assertGreater(project.count(),0);self.assertTrue(any(r'New\name' in x['after'] for x in plan))
            reopened=EditProject(self.corpus,project.path);self.assertEqual(project.data,reopened.data)
            project.apply_replacements(plan,undo=True);self.assertEqual(project.data,before)
            self.assertGreater(len(list((Path(tmp)/'backups').glob('*.json'))),0)
            item=plan[0];row=next(r for r in self.corpus.load(item['key'])[0]['rows'] if r['id']==item['id'])
            project.set(item['key'],row,item['field'],'Later manual edit');state=copy.deepcopy(project.data)
            with self.assertRaises(ValueError):project.apply_replacements(plan)
            self.assertEqual(project.data,state)
            jp=project.find_all(row['speaker_jp'],'確認',('jp',),True);self.assertGreater(len(jp),0)
            both=project.find_all('a','b',('en','jp'),False)
            self.assertTrue(all(not x['field'].startswith('speaker') for x in both))
            self.assertLessEqual(len(project.find_all('the','x',('en',),False,False,True)),len(project.find_all('the','x',('en',),False,False,False)))

    def test_every_collection_maps_into_existing_native_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json')
            for collection in self.corpus.collections:
                doc,_=self.corpus.load(collection['key'])
                row=next((r for r in doc['rows'] if not r.get('null_text')),None)
                if row is None:continue
                project.set(collection['key'],row,'en',(row.get('en') or '')+' [QA]')
                if 'speaker_en' in row:project.set(collection['key'],row,'speaker_en','QA speaker')
            groups=collect_changes(project,'en');archives={a:Psarc(BASE/(a+'.psarc')) for a in {a for a,e in groups}}
            indices={a:{e.name:e for e in arc.entries} for a,arc in archives.items()};counts={}
            for (a,entry),items in groups.items():
                source=archives[a]._read_file(indices[a][entry])
                try:result,review=compile_entry(source,items,'en',None)
                except Exception as exc:raise AssertionError(entry+': '+str(exc)) from exc
                self.assertNotEqual(result,source);self.assertTrue(review);counts[a]=counts.get(a,0)+1
                if source[:4]==b'CSB ':
                    old=parse_csb(source)[2];new=parse_csb(result)[2]
                    for k,(x,y) in enumerate(zip(old,new)):
                        if k not in {i['row']['command_index'] for i in items}:self.assertEqual(x['arguments'],y['arguments'])
                elif source[:2]==b'\x03\0':
                    old=parse_bmd(source)[3];new=parse_bmd(result)[3]
                    for k,(x,y) in enumerate(zip(old,new)):
                        if k not in {i['row']['message_index'] for i in items}:self.assertEqual(x,y)
            self.assertEqual(counts['Battle'],263);self.assertEqual(counts['Common'],5)
            self.assertGreater(counts['Logic'],100)

    def test_dialogue_shared_names_do_not_change_other_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json');key=next(c['key'] for c in self.corpus.collections if c['meta'].get('script_id')=='S000')
            doc,_=self.corpus.load(key);row=doc['rows'][0];project.set(key,row,'speaker_en','Different speaker');project.set(key,row,'en','Two lines\nVerified.')
            groups=collect_changes(project,'en');arc=Psarc(BASE/'Logic.psarc');entry='/'+doc['metadata']['native_entry'];source=arc._read_file(next(e for e in arc.entries if e.name==entry))
            result,_=compile_entry(source,groups['Logic',entry],'en');old=parse_ldbi_table(source)[2];new=parse_ldbi_table(result)[2]
            count,start=struct.unpack_from('>II',source,0x20)
            for k in range(count):
                at=start+k*196
                if struct.unpack_from('>I',source,at)[0]!=0 or k==row['command_index']:continue
                for offset in (12,16):
                    index=struct.unpack_from('>I',source,at+offset)[0]
                    if index>=len(old):continue
                    actual=struct.unpack_from('>I',result,at+offset)[0];self.assertEqual(read_cstring(source,old[index]),read_cstring(result,new[actual]))

    def test_patch_language_selection_and_japanese_line_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json');key=self.corpus.collections[0]['key'];doc,_=self.corpus.load(key);row=doc['rows'][0]
            project.set(key,row,'en','Edited English.');project.set(key,row,'jp','確認。\n次の行。')
            arc=Psarc(BASE/'Logic.psarc');entry='/'+doc['metadata']['native_entry'];source=arc._read_file(next(e for e in arc.entries if e.name==entry))
            for language,expected in [('en','Edited English.'),('jp','確認。@次の行。')]:
                groups=collect_changes(project,language);result,review=compile_entry(source,groups['Logic',entry],language)
                pointers=parse_ldbi_table(result)[2];index=struct.unpack_from('>I',result,row['command_offset']+16)[0]
                self.assertEqual(read_cstring(result,pointers[index]),expected);self.assertEqual([r['field'] for r in review],[language])

    def test_stream_archive_aliases_exact_size_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.psarc';target=Path(tmp)/'patched.psarc';mini_archive(source)
            replacement=b'More text and line breaks @ '+bytes(range(32,120));report=repack(source,target,{'/one':replacement})
            self.assertTrue(report['all_entries_verified']);self.assertEqual(source.stat().st_size,target.stat().st_size)
            arc=Psarc(target);by_name={e.name:e for e in arc.entries}
            self.assertEqual(arc._read_file(by_name['/one']),replacement)
            self.assertEqual(by_name['/two'].offset,by_name['/alias'].offset)
            self.assertEqual(arc._read_file(by_name['/two']),b'Other asset '*300)

    def test_large_bulk_change_reuses_native_text_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=EditProject(self.corpus,Path(tmp)/'project.json')
            plan=project.find_all('the','THE',('en',),False,True,True);project.apply_replacements(plan)
            groups=collect_changes(project,'en');arc=Psarc(BASE/'Logic.psarc');entries={e.name:e for e in arc.entries};checked=0
            for (archive,entry),items in groups.items():
                if archive=='Logic' and '/talk/' in entry:
                    source=arc._read_file(entries[entry]);result,_=compile_entry(source,items,'en')
                    self.assertEqual(len(result),len(source));checked+=1
            self.assertGreater(checked,60)

    def test_install_restore_and_failure_recovery_only_in_temp_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);targets=[];before=b'original archive bytes';after=b'new game archive bytes';self.assertEqual(len(before),len(after));stamp=1700000000000000000
            for name in ['disc','hdd']:
                target=root/name/'USRDIR/PSARC';target.mkdir(parents=True);(target.parent.parent/'PARAM.SFO').write_bytes(b'\0PSF\0BLJS10335\0')
                path=target/'Logic.psarc.sdat';path.write_bytes(before);os.utime(path,ns=(stamp,stamp));targets.append(target)
                (target/'Common.psarc.sdat').write_bytes(b'unrelated archive')
            build=root/'build';build.mkdir();(build/'Logic.psarc.sdat').write_bytes(after)
            doc=dict(version=1,status='ready',source_corpus=str(CORPUS),targets=[str(t) for t in targets],archives=[dict(name='Logic',file='Logic.psarc.sdat',before=sha(before),after=sha(after),size=len(before),mtime_ns=stamp)])
            manifest=build/'patch.json';atomic_json(manifest,doc)
            self.assertEqual(install_patch(manifest,closed_check=lambda:None)['status'],'installed')
            for target in targets:
                self.assertEqual((target/'Logic.psarc.sdat').read_bytes(),after);self.assertEqual((target/'Logic.psarc.sdat').stat().st_mtime_ns,stamp)
            self.assertEqual(install_patch(manifest,restore=True,closed_check=lambda:None)['status'],'restored')
            for target in targets:self.assertEqual((target/'Logic.psarc.sdat').read_bytes(),before);self.assertEqual((target/'Common.psarc.sdat').read_bytes(),b'unrelated archive')
            broken=root/'failure';broken.mkdir();(broken/'Logic.psarc.sdat').write_bytes(after);atomic_json(broken/'patch.json',doc)
            from patcher import atomic_copy
            failed=[False]
            def fail_after_second_write(source,target,expected,mtime):
                atomic_copy(source,target,expected,mtime)
                if Path(target)==targets[1]/'Logic.psarc.sdat' and expected==sha(after) and not failed[0]:failed[0]=True;raise OSError('Simulated second-copy write failure')
            with patch('patcher.atomic_copy',side_effect=fail_after_second_write):
                with self.assertRaises(OSError):install_patch(broken/'patch.json',closed_check=lambda:None)
            for target in targets:self.assertEqual((target/'Logic.psarc.sdat').read_bytes(),before)
            self.assertEqual(json.loads((broken/'installation.json').read_text())['status'],'recovered')
            # Simulate power loss after one target replacement. The persisted
            # journal and backups must restore a mixture of old/new copies.
            interrupted=root/'interrupted';(interrupted/'backups').mkdir(parents=True)
            (interrupted/'Logic.psarc.sdat').write_bytes(after);(interrupted/'backups/Logic.psarc.sdat').write_bytes(before)
            atomic_json(interrupted/'patch.json',doc);atomic_json(interrupted/'installation.json',dict(status='installing'))
            (targets[0]/'Logic.psarc.sdat').write_bytes(after);os.utime(targets[0]/'Logic.psarc.sdat',ns=(stamp,stamp))
            self.assertEqual(install_patch(interrupted/'patch.json',restore=True,closed_check=lambda:None)['status'],'restored')
            for target in targets:self.assertEqual((target/'Logic.psarc.sdat').read_bytes(),before)

    def test_gui_bulk_preview_replace_undo_and_patch_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            editor=Editor(self.corpus,Path(tmp)/'project.json');editor.show();dialog=SearchDialog(editor);dialog.show()
            dialog.find.setPlainText('E-Selda');dialog.replacement.setPlainText('QA Name');dialog.search();self.app.processEvents()
            self.assertGreater(dialog.model.rowCount(),0);self.assertTrue(dialog.replace.isEnabled());dialog.replace_all()
            self.assertGreater(editor.project.count(),0);dialog.undo_replace();self.assertEqual(editor.project.count(),0)
            dialog.search();dialog.grab().save(str(ROOT/'script_editor/qa/global_search.png'));dialog.accept()
            patch_dialog=PatchDialog(editor,Path(tmp));patch_dialog.show();self.app.processEvents();self.assertFalse(patch_dialog.install.isEnabled())
            patch_dialog.grab().save(str(ROOT/'script_editor/qa/patch_dialog.png'));patch_dialog.accept();editor.close()

    def test_select_installed_data_clears_stale_second_copy_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);runtime=home/'rpcs3';runtime.mkdir();(runtime/'rpcs3.exe').write_bytes(b'fixture')
            target=runtime/'dev_hdd0/game/BLJS10335/USRDIR/PSARC';target.mkdir(parents=True)
            (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335');(target/'Logic.psarc.sdat').write_bytes(b'fixture')
            editor=Editor(self.corpus,home/'project.json');dialog=PatchDialog(editor,home)
            self.assertEqual(default_targets(self.corpus),[])
            dialog.mode.setCurrentIndex(1);dialog.paths[0].setText(str(home/'old_disc'));dialog.paths[1].setText(str(home/'old_hdd'))
            dialog.runtime.setText(str(runtime));dialog.select_installed()
            self.assertEqual(dialog.paths[0].text(),str(target));self.assertEqual(dialog.paths[1].text(),'')
            self.assertEqual(dialog.mode.currentIndex(),0)
            config=json.loads((home/'patch_settings.json').read_text())
            self.assertEqual(config['targets'],[str(target)]);self.assertEqual(config['runtime'],str(runtime))
            dialog.close();reopened=PatchDialog(editor,home)
            self.assertEqual(reopened.paths[0].text(),str(target));self.assertEqual(reopened.paths[1].text(),'')
            self.assertEqual(reopened.runtime.text(),str(runtime));reopened.close();editor.close()

    def test_installed_target_respects_selected_runtime_vfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime=root/'rpcs3';(runtime/'config').mkdir(parents=True);(runtime/'rpcs3.exe').write_bytes(b'fixture')
            import yaml
            redirected=root/'relocated_hdd';target=redirected/'game/BLJS10335/USRDIR/PSARC';target.mkdir(parents=True)
            (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335');(target/'Logic.psarc.sdat').write_bytes(b'fixture')
            (runtime/'config/vfs.yml').write_text(yaml.safe_dump({'/dev_hdd0/':str(redirected)}))
            self.assertEqual(installed_target(runtime),target)
            (target.parent.parent/'PARAM.SFO').write_bytes(b'WRONG GAME')
            with self.assertRaises(ValueError):installed_target(runtime)

    def test_mismatched_game_copies_are_still_blocked_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);targets=[]
            for i in range(2):
                target=root/str(i)/'USRDIR/PSARC';target.mkdir(parents=True)
                (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335')
                (target/'Logic.psarc.sdat').write_bytes(b'fixture')
                (target/'Battle.psarc.sdat').write_bytes(bytes([i])*100);targets.append(target)
            project=EditProject(self.corpus,root/'project.json')
            before=[(p/'Battle.psarc.sdat').read_bytes() for p in targets]
            with patch('patcher.collect_changes',return_value={('Battle','/fixture'):[]}):
                with self.assertRaisesRegex(ValueError,'Use installed game data'):
                    prepare_patch(project,'en',targets,root/'build',backlog=False)
            self.assertEqual(before,[(p/'Battle.psarc.sdat').read_bytes() for p in targets])


if __name__=='__main__':unittest.main(verbosity=2)
