"""Real source coverage, shared-event protection and UI checks for v3.9."""
import copy,json,os,struct,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from core import Corpus,EditProject,atomic_json
from patcher import collect_changes,compile_entry
from native_formats import parse_ldbi_table,read_cstring,LDBI_TEXT_FIELDS,location_signature
from fixed_data import parse_fixed,SCHEMAS,structure_hash
from edit_bundle import export_bundle,read_bundle
from script_import import ScriptImporter
from vendor.psarc import Psarc

ROOT=Path(__file__).resolve().parents[1]
LOCATION='07_Location_banners/Locations'

class ExpandedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        cls.arc=Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
        cls.sources={e.name:cls.arc._read_file(e) for e in cls.arc.entries if e.name.startswith(('/Dat/logic/','/Dat/FixedData/'))}

    def test_all_locations_both_languages_and_unrelated_commands(self):
        rows=self.corpus.load(LOCATION)[0]['rows'];self.assertEqual(len(rows),764)
        for lang in ('en','jp'):
            grouped={}
            for row in rows:grouped.setdefault('/'+row['native_entry'],[]).append(dict(row=row,edits={lang:row[lang]}))
            for entry,items in grouped.items():
                before=self.sources[entry];after,review=compile_entry(before,items,lang)
                count,start=struct.unpack_from('>II',before,0x20);offsets=parse_ldbi_table(after)[2]
                allowed=set()
                for item in items:
                    row=item['row'];offset=LDBI_TEXT_FIELDS[row['location_field']][1];at=row['command_offset']+offset
                    index=struct.unpack_from('>I',after,at)[0]
                    self.assertEqual(read_cstring(after,offsets[index]),row[lang]);allowed.update(range(at,at+4))
                for i in range(start,len(before)):
                    if i not in allowed:self.assertEqual(before[i],after[i],(entry,hex(i)))

    def test_banner_and_dialogue_same_script_remain_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            p=EditProject(self.corpus,Path(temp)/'edits.json')
            banner=next(r for r in self.corpus.load(LOCATION)[0]['rows'] if 'Hagwane' in r['en'])
            key=banner['source_collection'];dialogue=next(r for r in self.corpus.load(key)[0]['rows'] if r['en'])
            p.set(LOCATION,banner,'en','Hagane, QA Hangar');p.set(key,dialogue,'en','QA dialogue')
            groups=collect_changes(p,'en');self.assertEqual(len(groups),1)
            entry=next(iter(groups))[1];result,_=compile_entry(self.sources[entry],next(iter(groups.values())),'en')
            offsets=parse_ldbi_table(result)[2]
            for row,off,want in ((banner,LDBI_TEXT_FIELDS[banner['location_field']][1],'Hagane, QA Hangar'),(dialogue,16,'QA dialogue')):
                self.assertEqual(read_cstring(result,offsets[struct.unpack_from('>I',result,row['command_offset']+off)[0]]),want)
            bundle=export_bundle(p,Path(temp)/'patch_edits.json')
            self.assertEqual(read_bundle(bundle,{'corpus_identity':self.corpus.identity})[0],groups)
            p.export(Path(temp)/'export')
            for fmt in ('script.json','EN.txt','Bilingual.txt'):
                q=EditProject(self.corpus,Path(temp)/'import.json')
                self.assertEqual(len(ScriptImporter(q).preview(Path(temp)/'export',fmt)['plan']),2)

    def test_location_rejects_changed_event_or_invalid_controls(self):
        row=self.corpus.load(LOCATION)[0]['rows'][0];source=self.sources['/'+row['native_entry']]
        for text in ('two\nlines','<control>'):
            with self.assertRaisesRegex(ValueError,'one line'):compile_entry(source,[dict(row=row,edits={'en':text})],'en')
        bad=bytearray(source);bad[row['command_offset']+100]^=1
        with self.assertRaisesRegex(ValueError,'event data'):compile_entry(bytes(bad),[dict(row=row,edits={'en':'QA'})],'en')
        badrow=copy.deepcopy(row);badrow['location_field']='text'
        with self.assertRaises(ValueError):compile_entry(source,[dict(row=badrow,edits={'en':'QA'})],'en')

    def test_spirits_can_be_edited_repeatedly_without_pointer_exhaustion(self):
        rows=self.corpus.load('06_Game_data/Spirit_commands')[0]['rows'];source=self.sources['/Dat/FixedData/SpiritData.dat']
        old=parse_fixed(source);self.assertEqual(len(rows),88)
        for iteration in range(8):
            items=[dict(row=r,edits={'en':f'QA {iteration} {n}'}) for n,r in enumerate(rows)]
            source,_=compile_entry(source,items,'en');actual=parse_fixed(source)
            self.assertEqual(structure_hash(actual,'SpiritData'),structure_hash(old,'SpiritData'))
            self.assertLessEqual(len(actual.strings),256)
            for item in items:
                r=item['row'];off,width=SCHEMAS['SpiritData'][1][r['fixed_field']]
                self.assertEqual(actual.strings[actual.records[r['fixed_record']][off]],item['edits']['en'])

    def test_expanded_gui_search_and_previews(self):
        from PySide6.QtWidgets import QApplication
        from app import Editor,STYLE,load_ui_fonts
        app=QApplication.instance() or QApplication([]);load_ui_fonts();app.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory() as temp:
            w=Editor(self.corpus,Path(temp)/'edits.json');w.show();app.processEvents()
            keys=[LOCATION,'06_Game_data/Weapon_names']
            for key in keys:
                row=next(r for r in self.corpus.load(key)[0]['rows'] if r['en'])
                w.open_line(key,row['id']);app.processEvents();self.assertEqual(w.preview_stack.currentIndex(),1)
                self.assertFalse(w.speakers['en'].isVisible())
                self.assertTrue(w.data_preview.heading)
                w.grab().save(str(ROOT/'script_editor/qa'/('v39_'+key.split('/')[-1]+'.png')))
            hits=w.project.find_all('Hagwane','Hagane');self.assertEqual(len([h for h in hits if h['key']==LOCATION]),117)
            weapon=next(r for r in self.corpus.load('06_Game_data/Weapon_names')[0]['rows'] if r['weapon_unit'] in w.weapon_units and r['weapon_unit'])
            unit=w.weapon_units[weapon['weapon_unit']];w.project.set('06_Game_data/Mech_names',unit,'en','QA updated owner')
            w.open_line('06_Game_data/Weapon_names',weapon['id']);app.processEvents()
            self.assertEqual(w.data_preview.text,'QA updated owner');w.search.setText('QA updated owner');self.assertGreater(w.proxy.rowCount(),0)
            w.open_line('04_Shared/Battle_messages/0057','0057:0064');app.processEvents()
            self.assertEqual((w.cell.value(),w.width_limit.value()),(28,768))
            self.assertIn('wide lines will compress',w.fit.text())
            w.grab().save(str(ROOT/'script_editor/qa/v39_battle_fit.png'));w.close()

    def test_upgrade_legacy_embedded_eboot_and_reopen_prepared_build(self):
        from native_eboot import prepare,validate_prepared,extract_elf,sha,ELF_SHA256
        asset=ROOT/'script_editor/assets/native_eboot'
        sources=[ROOT/'work/poc/native_eboot_20260910_v2/EBOOT.BIN']
        import zlib
        raw=[p.read_bytes() for p in sources]+[zlib.decompress((ROOT/'work/poc/editor_v39_20260914/backups/native_eboot/EBOOT.BIN.zlib').read_bytes())]
        with tempfile.TemporaryDirectory() as temp:
            for n,before in enumerate(raw):
                folder=Path(temp)/str(n);record=prepare(before,asset,folder/'native/EBOOT.BIN',1)
                after=validate_prepared(folder,record).read_bytes()
                self.assertEqual(len(after),len(before));self.assertEqual(sha(extract_elf(after)),ELF_SHA256)
                again=prepare(after,asset,folder/'again/EBOOT.BIN',1);self.assertEqual(again['before'],again['after'])

if __name__=='__main__':unittest.main()
