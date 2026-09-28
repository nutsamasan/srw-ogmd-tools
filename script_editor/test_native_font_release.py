"""Embedded EBOOT identity, complete build paths, ISO safety and YAML migration."""
import copy,json,os,shutil,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core import atomic_json,Corpus,EditProject,NativeMetrics
from native_eboot import load_asset,extract_elf,ELF_SHA256,STOCK_SHA256,MODE,prepare,validate_prepared,sha
from full_patch import prepare_font_patch,prepare_full_patch,write_full_game,package_info
from iso_image import DiscImage
from archive_patch import digest,repack
from release_delta import build_recipe,sdat_metadata
from vendor import sdat
from runtime_setup import setup_runtime,restore_setup,PPU,PATCH
from test_patch_features import mini_archive
from test_import_iso import mini_iso
from text_layout import battle_display,wrap_battle

ROOT=Path(__file__).resolve().parents[1]
ASSET=ROOT/'script_editor/assets/native_eboot'
DATA=ROOT/'full_patcher/data'
STOCK=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/EBOOT.BIN'


def iso_with_eboot(path):
    mini_iso(path);raw=bytearray(path.read_bytes());boot=STOCK.read_bytes();start=len(raw)//2048
    record=bytearray(44);record[0]=44
    struct.pack_into('<I',record,2,start);struct.pack_into('>I',record,6,start)
    struct.pack_into('<I',record,10,len(boot));struct.pack_into('>I',record,14,len(boot))
    record[18:25]=bytes([126,9,11,0,0,0,0]);record[28:32]=b'\1\0\0\1'
    label=b'EBOOT.BIN;1';record[32]=len(label);record[33:44]=label
    # Existing USRDIR contains just its PSARC child.
    offset=26*2048+raw[26*2048];raw[offset:offset+44]=record
    raw.extend(boot);raw.extend(bytes((-len(raw))%2048))
    struct.pack_into('<I',raw,16*2048+80,len(raw)//2048);struct.pack_into('>I',raw,16*2048+84,len(raw)//2048)
    path.write_bytes(raw)


class NativeFontReleaseTests(unittest.TestCase):
    def test_battle_fix_upgrades_release_and_test_builds_without_diagnostic_recorder(self):
        import zlib
        info,current=load_asset(ASSET)
        self.assertEqual(info['battle_caption_limits'],{'full':768,'compact':720})
        self.assertTrue(info['confirmed_battle_hook_identical'])
        self.assertFalse(info['diagnostic_recorder'])
        source=zlib.decompress((ROOT/'work/backups/battle_caption_release_20260920/script_editor/assets/native_eboot/EBOOT.BIN.zlib').read_bytes())
        candidates=[source]+[(ROOT/'work/poc'/name/'EBOOT.BIN').read_bytes() for name in
            ('battle_fit_cache_20260918','battle_trace_20260920_v2','battle_caption_path_fix_20260920_v2')]
        with tempfile.TemporaryDirectory() as tmp:
            for i,raw in enumerate(candidates):
                folder=Path(tmp)/str(i)
                record=prepare(raw,ASSET,folder/'native/EBOOT.BIN',1)
                self.assertEqual(validate_prepared(folder,record).read_bytes(),current)
                self.assertEqual(record['before'],sha(raw))
        elf=extract_elf(current)
        for address,original in ((0x247574,'7d800026'),(0xb7a198,'f821fbf1'),(0xb7c980,'f821fc01')):
            self.assertEqual(elf[address-0x10000:address-0x10000+4].hex(),original)

    def fixture_game(self,root):
        source=root/'source';game=source/'PS3_GAME';(game/'USRDIR/PSARC').mkdir(parents=True)
        (game/'PARAM.SFO').write_bytes(b'BLJS10335');shutil.copy2(STOCK,game/'USRDIR/EBOOT.BIN')
        (game/'USRDIR/PSARC/current-text.dat').write_bytes(b'current user text')
        (source/'disc.dat').write_bytes(b'untouched disc file')
        return source,game

    def test_embedded_asset_retains_verified_font_hooks_and_fits_stock(self):
        info,raw=load_asset(ASSET)
        tested=(ROOT/'work/poc/native_eboot_20260910_v2/EBOOT.BIN').read_bytes()
        self.assertEqual(sha(extract_elf(tested)),info['previous_elf_sha256']);self.assertEqual(sha(extract_elf(raw)),ELF_SHA256)
        self.assertEqual(len(raw),STOCK.stat().st_size);self.assertEqual(struct.unpack_from('>Q',raw,16)[0],0x88)
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);record=prepare(STOCK.read_bytes(),ASSET,tmp/'native/EBOOT.BIN',1)
            self.assertEqual(validate_prepared(tmp,record).read_bytes(),raw)
            with self.assertRaises(ValueError):prepare(b'wrong revision',ASSET,tmp/'bad',1)
            (tmp/'native/EBOOT.BIN').write_bytes(raw[:-1]+b'!')
            with self.assertRaises(ValueError):validate_prepared(tmp,record)
            again=prepare(raw,ASSET,tmp/'again/EBOOT.BIN',1);self.assertEqual(again['before'],again['after'])

    def test_font_only_folder_keeps_translation_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source,game=self.fixture_game(tmp)
            before={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
            manifest=prepare_font_patch(DATA,source,tmp/'build');output=tmp/'output'
            result=write_full_game(manifest,output);self.assertTrue(result['embedded_font_code'])
            self.assertEqual(before,{p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()})
            for rel,value in before.items():
                if rel.as_posix()=='PS3_GAME/USRDIR/EBOOT.BIN':self.assertEqual(sha(extract_elf((output/rel).read_bytes())),ELF_SHA256)
                else:self.assertEqual((output/rel).read_bytes(),value)
            doc=json.loads(manifest.read_text());self.assertEqual(doc['archives'],[])
            with self.assertRaises(ValueError):write_full_game(manifest,output)
            with self.assertRaises(ValueError):write_full_game(manifest,source/'nested')

    def test_font_only_iso_replaces_only_eboot_and_rejects_stale_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'source.iso';iso_with_eboot(source);before=source.read_bytes()
            manifest=prepare_font_patch(DATA,source,tmp/'build');output=tmp/'output.iso'
            result=write_full_game(manifest,output);self.assertTrue(result['source_preserved'])
            self.assertTrue(result['outside_patched_files_unchanged']);self.assertFalse(result['outside_archive_bytes_unchanged'])
            self.assertEqual(source.read_bytes(),before);self.assertEqual(output.stat().st_size,len(before))
            with DiscImage(output) as check,DiscImage(source) as original:
                self.assertEqual(check.views.keys(),original.views.keys())
                for key,item in check.files.items():
                    if key.endswith('/EBOOT.BIN'):
                        self.assertEqual(sha(extract_elf(b''.join(check.chunks(item)))),ELF_SHA256)
                    else:self.assertEqual(check.checksum(item),original.checksum(original.files[key]))
                extent=check.file('/PS3_GAME/USRDIR/EBOOT.BIN').extents[0]
                after=output.read_bytes();start,size=extent
                self.assertEqual(after[:start],before[:start]);self.assertEqual(after[start+size:],before[start+size:])
            doc=json.loads(manifest.read_text());payload=manifest.parent/doc['eboot']['file'];payload.write_bytes(b'damaged')
            with self.assertRaises(ValueError):write_full_game(manifest,tmp/'bad.iso')
            self.assertFalse((tmp/'bad.iso').exists())

    def test_full_translation_preparation_embeds_eboot(self):
        # Execute the full recipe/decrypt/encrypt path with five real small SDATs.
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source,game=self.fixture_game(tmp);data=tmp/'release';data.mkdir()
            shutil.copytree(ASSET,data/'native_eboot');shutil.copy2(DATA/'install_icon.png',data/'install_icon.png')
            native_info,_=load_asset(ASSET)
            release=dict(version=1,status='ready',release='QA embedded release',title_id='BLJS10335',archives=[],
                font_mode=MODE,embedded_eboot_sha256=native_info['sha256'],eboot_sha256=STOCK_SHA256,
                edited_rows=0,review=[],features=[],project_sha256='QA',install_icon_sha256=digest(data/'install_icon.png'))
            template=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat'
            for name in ['Logic','Common','General2d','Battle','General3d']:
                plain=tmp/(name+'.plain');target=tmp/(name+'.target');mini_archive(plain)
                repack(plain,target,{'/one':b'English '+name.encode()})
                original=game/'USRDIR/PSARC'/(name+'.psarc.sdat');encrypted=tmp/(name+'.new.sdat')
                sdat.encrypt(plain,original,template,verbose=False);sdat.encrypt(target,encrypted,original,verbose=False)
                recipe=build_recipe(plain,target,data/(name+'.delta'));atomic_json(data/(name+'.recipe.json'),recipe)
                (data/(name+'.sdatmeta')).write_bytes(sdat_metadata(encrypted))
                a=dict(name=name,size=encrypted.stat().st_size,source_sdat_sha256=digest(original),target_sdat_sha256=digest(encrypted))
                for field,suffix in [('recipe','.recipe.json'),('blob','.delta'),('metadata','.sdatmeta')]:
                    a[field]=name+suffix;a[field+'_sha256']=digest(data/a[field])
                release['archives'].append(a)
            atomic_json(data/'release.json',release);package_info(data)
            manifest=prepare_full_patch(data,source,tmp/'build');doc=json.loads(manifest.read_text())
            self.assertEqual(doc['font_mode'],MODE);self.assertEqual(len(doc['archives']),5)
            self.assertFalse((manifest.parent/'runtime/spacing.yml').exists())
            output=tmp/'translated';write_full_game(manifest,output)
            self.assertEqual(sha(extract_elf((output/'PS3_GAME/USRDIR/EBOOT.BIN').read_bytes())),ELF_SHA256)
            for a in release['archives']:self.assertEqual(digest(output/'PS3_GAME/USRDIR/PSARC'/(a['name']+'.psarc.sdat')),a['target_sdat_sha256'])

    def test_runtime_native_migration_preserves_other_patches_and_restores(self):
        from test_full_release import FullReleaseTests
        helper=FullReleaseTests()
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);runtime,game,manifest=helper.fixture(tmp,profile='font-only')
            doc=json.loads(manifest.read_text());doc.update(font_mode=MODE,archives=[])
            doc['eboot']=prepare(STOCK.read_bytes(),ASSET,manifest.parent/'native/EBOOT.BIN',1);atomic_json(manifest,doc)
            before=helper.snapshot(runtime)
            result=setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            self.assertFalse(result['patch_enabled']);self.assertIsNone(result['patch_path']);self.assertFalse(result['sync_installed_data'])
            import yaml
            config=yaml.safe_load((runtime/'config/patch_config.yml').read_text());self.assertNotIn(PPU,config)
            self.assertTrue(config['PPU-other']['Preserve']);self.assertEqual((game/'ICON0.PNG').read_bytes(),b'old icon')
            self.assertFalse((runtime/'patches/BLJS10335_patch.yml').exists())
            restore_setup(result['setup_plan'],closed_check=lambda _:None);self.assertEqual(helper.snapshot(runtime),before)

    def test_clean_runtime_needs_no_font_yaml(self):
        from runtime_check import check_runtime_package
        check=check_runtime_package(DATA)
        self.assertEqual(check['font_mode'],MODE);self.assertFalse(check['font_yaml_required']);self.assertTrue(check['restore'])


class BattleLineBreakTests(unittest.TestCase):
    def test_preview_wrap_and_patch_conventions(self):
        from app import Editor,load_ui_fonts
        from PySide6.QtWidgets import QApplication
        from patcher import collect_changes,compile_entry
        from native_formats import parse_bmd
        from vendor.psarc import Psarc
        from script_import import ScriptImporter
        app=QApplication.instance() or QApplication([]);load_ui_fonts()
        corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);w=Editor(corpus,tmp/'project.json')
            try:
                key='04_Shared/Battle_messages/0112';w.open_line(key,'0112:2261')
                original=w.editors['en'].toPlainText();self.assertIn('/',original)
                self.assertEqual(w.preview.text,battle_display(original));self.assertNotIn('/',w.preview.text)
                self.assertIn('2/3 lines',w.fit.text());self.assertEqual(w.project.count(),0)
                w.show();app.processEvents();w.grab().save(str(ROOT/'script_editor/qa/battle_breaks_v37.png'))
                w.preview_language.setCurrentIndex(1);self.assertNotIn('/',w.preview.text)
                w.preview_language.setCurrentIndex(0);w.editors['en'].setPlainText('First line\nSecond line/Third line')
                self.assertEqual(w.preview.text,'First line\nSecond line\nThird line');self.assertIn('3/3 lines',w.fit.text())
                w.project.export(tmp/'export');exported=json.loads((tmp/'export'/key/'script.json').read_text(encoding='utf8'))
                r=next(r for r in exported['rows'] if r['id']=='0112:2261')
                self.assertEqual(r['en_raw'],'First line/Second line/Third line')
                other=EditProject(corpus,tmp/'other.json');plan=ScriptImporter(other).preview(tmp/'export'/key/'script.json')['plan']
                self.assertEqual(plan[0]['after'],'First line\nSecond line/Third line')
                arc=Psarc(ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Battle.psarc')
                for (_,entry),items in collect_changes(w.project,'en').items():
                    raw=arc._read_file(next(e for e in arc.entries if e.name==entry));patched,review=compile_entry(raw,items,'en')
                    self.assertEqual(parse_bmd(patched)[3][2261],'First line/Second line/Third line')
                    self.assertFalse(review[0]['normalized']);self.assertEqual(review[0]['after'],'First line\nSecond line\nThird line')
                w.editors['en'].setPlainText('A/B/C/D');self.assertIn('only 3 fit',w.fit.text())
                row=next(c for c in corpus.collections if c['meta'].get('script_id')=='S001')
                w.open_line(row['key'],corpus.load(row['key'])[0]['rows'][0]['id'])
                w.editors['en'].setPlainText('Keep / in story\nNext line');self.assertIn('/',w.preview.text)
                metrics=w.metrics;wrapped=wrap_battle(metrics,'Alpha beta gamma/Second line',24,100)
                self.assertNotIn('\n',wrapped);self.assertGreater(wrapped.count('/'),1)
                self.assertTrue(all(metrics.width(line,24)<=100 for line in wrapped.split('/')))
                self.assertEqual(wrap_battle(metrics,'A//B',24,768),'A//B')
            finally:w.close()


if __name__=='__main__':unittest.main(verbosity=2)
