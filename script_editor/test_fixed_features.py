import copy,json,os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from core import Corpus,EditProject,atomic_json
from fixed_data import parse_fixed,SCHEMAS,structure_hash
from patcher import collect_changes,compile_entry
from script_import import ScriptImporter
from edit_bundle import export_bundle,read_bundle,checksum
from glossary import rename_plan,resolve,keywords,rich_lines
from vendor.psarc import Psarc

ROOT=Path(__file__).resolve().parents[1]

class FixedFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        arc=Psarc(ROOT/'work/poc/full_release_20260909/Logic.psarc')
        cls.sources={table:arc._read_file(next(e for e in arc.entries if e.name=='/Dat/FixedData/'+table+'.dat')) for table in SCHEMAS}

    def test_every_field_mapping_both_languages_and_shared_strings(self):
        for c in self.corpus.collections:
            if not c['key'].startswith('06_Game_data/'):continue
            rows=self.corpus.load(c['key'])[0]['rows'];table=rows[0]['fixed_table'];source=self.sources[table];before=parse_fixed(source)
            for lang in ('en','jp'):
                items=[dict(row=r,edits={lang:r[lang]}) for r in rows]
                result,review=compile_entry(source,items,lang)
                actual=parse_fixed(result)
                self.assertEqual(structure_hash(actual,table),structure_hash(before,table))
                for row in rows:
                    o,w=SCHEMAS[table][1][row['fixed_field']];index=int.from_bytes(actual.records[row['fixed_record']][o:o+w],'big')
                    self.assertEqual(actual.strings[index],row[lang])
                self.assertEqual(len(review),len(rows))
            # One user's pointer changes; all other users and their text stay intact.
            target=next(r for r in rows if r['en'] and r['fixed_record']>0)
            result,_=compile_entry(source,[dict(row=target,edits={'en':'Unique QA text'})],'en')
            after=parse_fixed(result);o,w=SCHEMAS[table][1][target['fixed_field']]
            for i,(a,b) in enumerate(zip(before.records,after.records)):
                self.assertEqual(a[:o],b[:o]) if i==target['fixed_record'] else self.assertEqual(a,b)
                if i==target['fixed_record']:self.assertEqual(a[o+w:],b[o+w:])
            for r in rows:
                if r['id']==target['id']:continue
                off,width=SCHEMAS[table][1][r['fixed_field']]
                self.assertEqual(before.strings[int.from_bytes(before.records[r['fixed_record']][off:off+width],'big')],
                    after.strings[int.from_bytes(after.records[r['fixed_record']][off:off+width],'big')])

    def test_fixed_import_export_search_and_metadata_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=EditProject(self.corpus,Path(tmp)/'project.json')
            for key in self.corpus.fixed_hashes:
                rows=self.corpus.load(key)[0]['rows'];r=next(r for r in rows if r['fixed_record']>0)
                p.set(key,r,'en','QA name');p.set(key,r,'jp','確認')
            p.save();p.export(Path(tmp)/'export')
            for fmt in ('script.json','EN.txt','JP.txt','Bilingual.txt'):
                q=EditProject(self.corpus,Path(tmp)/'import.json');plan=ScriptImporter(q).preview(Path(tmp)/'export',fmt)['plan']
                self.assertEqual(len(plan),len(self.corpus.fixed_hashes)*(1 if fmt in ('EN.txt','JP.txt') else 2))
            hits=p.find_all('QA name','Updated QA');self.assertEqual(len(hits),len(self.corpus.fixed_hashes))
            p.apply_replacements(hits);p.apply_replacements(hits,undo=True)
            key=next(iter(self.corpus.fixed_hashes));bad=copy.deepcopy(self.corpus.load(key)[0]);bad['rows']=bad['rows'][:1];bad['rows'][0]['fixed_record']+=1
            atomic_json(Path(tmp)/'script.json',bad)
            with self.assertRaisesRegex(ValueError,'metadata'):ScriptImporter(p).preview(Path(tmp)/'script.json')

    def test_glossary_rename_updates_wrapped_links_and_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=EditProject(self.corpus,Path(tmp)/'project.json');key,row=resolve(p,'The Steel Dragon Squad','en')[0]
            plan=rename_plan(p,key,row,'en','Steel Dragons');self.assertGreater(len(plan),20)
            self.assertTrue(any('\n' in t for change in plan for t in keywords(change['before'])))
            p.apply_replacements(plan);self.assertEqual(len(resolve(p,'Steel Dragons','en')),1)
            for c in self.corpus.collections:
                for r in self.corpus.load(c['key'])[0]['rows']:
                    from glossary import key as canonical
                    self.assertNotIn(canonical('The Steel Dragon Squad'),[canonical(t) for t in keywords(p.values(c['key'],r).get('en') or '')])
            p.apply_replacements(plan,undo=True);self.assertEqual(p.count(),0)
            self.assertEqual(keywords('<I=92><C=red><Cross Gate></C>'),['Cross Gate'])
            self.assertEqual([[x[0] for x in line] for line in rich_lines('A<C=red>B</C><CD>@E')],[list('ABCD'),['E']])

    def test_portable_bundle_rejects_tampering_and_wrong_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=EditProject(self.corpus,Path(tmp)/'project.json');key='06_Game_data/Pilot_names';r=self.corpus.load(key)[0]['rows'][3]
            p.set(key,r,'en','QA name');path=export_bundle(p,Path(tmp)/'patch_edits.json');release={'corpus_identity':self.corpus.identity}
            groups,_=read_bundle(path,release);self.assertEqual(len(groups),1)
            for (archive,entry),items in groups.items():self.assertTrue(compile_entry(self.sources['PilotData'],items,'en')[1])
            bad=json.loads(path.read_text(encoding='utf8'));bad['groups'][0]['items'][0]['edits']['en']='tampered';atomic_json(path,bad)
            with self.assertRaises(ValueError):read_bundle(path,release)
            bad.pop('payload_sha256');bad['groups'][0]['entry']='/Dat/FixedData/UnitData.dat';bad['payload_sha256']=checksum(bad);atomic_json(path,bad)
            with self.assertRaises(ValueError):read_bundle(path,release)

    def test_gui_fixed_preview_and_keyword_hit_regions(self):
        from PySide6.QtWidgets import QApplication
        from app import Editor,STYLE,load_ui_fonts
        app=QApplication.instance() or QApplication([]);load_ui_fonts();app.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory() as tmp:
            w=Editor(self.corpus,Path(tmp)/'project.json');w.show();app.processEvents()
            key='06_Game_data/Pilot_names';row=next(r for r in self.corpus.load(key)[0]['rows'] if r['en']=='Irmgard')
            w.open_line(key,row['id']);app.processEvents();self.assertEqual(w.preview_stack.currentIndex(),1);self.assertIn('Irmgard',w.data_preview.text)
            w.grab().save(str(ROOT/'script_editor/qa/pilot_names_v35.png'))
            key,row=resolve(w.project,'ATX Team','en')[0];w.open_line(key,row['id']);app.processEvents()
            self.assertTrue(w.data_preview.link_regions);self.assertTrue(w.rename_term.isVisible());w.grab().save(str(ROOT/'script_editor/qa/glossary_v35.png'))
            w.close()

    def test_editor_full_patcher_requires_explicit_snapshot(self):
        from PySide6.QtWidgets import QApplication
        from app import Editor
        from full_dialog import FullPatchDialog
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);w=Editor(self.corpus,tmp/'project.json')
            key='06_Game_data/Pilot_names';row=self.corpus.load(key)[0]['rows'][3]
            w.project.set(key,row,'en','QA snapshot name')
            dialog=FullPatchDialog(tmp/'full',w)
            self.assertEqual(dialog.edits.text(),'')
            self.assertFalse((tmp/'full/editor_exports').exists())
            dialog.use_current_edits()
            groups,_=read_bundle(dialog.edits.text(),{'corpus_identity':self.corpus.identity})
            self.assertEqual(groups[('Logic','/Dat/FixedData/PilotData.dat')][0]['edits'],{'en':'QA snapshot name'})
            w.project.set(key,row,'en','Later change')
            self.assertEqual(read_bundle(dialog.edits.text(),{'corpus_identity':self.corpus.identity})[0],groups)
            dialog.close();w.close();app.processEvents()

if __name__=='__main__':unittest.main()
