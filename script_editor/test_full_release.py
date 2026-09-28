import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from archive_patch import repack,digest
from core import atomic_json
from release_delta import build_recipe,apply_recipe,sdat_metadata
from runtime_setup import prepare_setup,apply_setup,restore_setup,setup_runtime,verify_runtime,verify_patch_address_format,dump_patch_yaml,PPU,PATCH,GAME
from full_patch import write_full_game
from vendor import sdat
from test_patch_features import mini_archive

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'full_patcher/data'


class FullReleaseTests(unittest.TestCase):
    def test_recipe_roundtrip_and_input_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'old.psarc';target=root/'new.psarc';mini_archive(source)
            repack(source,target,{'/one':b'Full English text'})
            blob=root/'payload';recipe=build_recipe(source,target,blob)
            self.assertTrue(any(x[0]=='copy' for x in recipe['ops']))
            self.assertTrue(any(x[0]=='data' for x in recipe['ops']))
            output=root/'out';apply_recipe(source,blob,recipe,output);self.assertEqual(output.read_bytes(),target.read_bytes())
            with self.assertRaises(ValueError):apply_recipe(source,blob,recipe,output)
            bad=copy.deepcopy(recipe);bad['ops'][0][1]=-1
            with self.assertRaises(ValueError):apply_recipe(source,blob,bad,root/'invalid')
            self.assertFalse((root/'invalid').exists())
            blob.write_bytes(blob.read_bytes()+b'damaged')
            with self.assertRaises(ValueError):apply_recipe(source,blob,recipe,root/'damaged')
            self.assertFalse((root/'damaged').exists())

    def test_reproducible_sdat_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plain=root/'plain';plain.write_bytes(b'Full English test '*1400)
            template=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat'
            a,b=root/'a',root/'b';sdat.encrypt(plain,a,template,verbose=False);sdat.encrypt(plain,b,template,verbose=False)
            metadata=sdat_metadata(a);sdat_metadata(b,metadata)
            self.assertEqual(a.read_bytes(),b.read_bytes());self.assertTrue(sdat.verify(b,expect_plain=plain,verbose=False))
            with self.assertRaises(ValueError):sdat_metadata(b,metadata[:-1])

    def fixture(self,root,profile='full-english'):
        runtime=root/'rpcs3';runtime.mkdir();(runtime/'rpcs3.exe').write_bytes(b'QA')
        (runtime/'config').mkdir();(runtime/'patches').mkdir()
        (runtime/'config.yml').write_text(yaml.safe_dump({'Video':{'Resolution Scale':200},'Core':{'SPU Cache':True,'Libraries Control':['other.sprx:lle']}}))
        old={'Version':1.2,'PPU-other':{'Unrelated':{'Patch':[['be32',123,456]]}},PPU:{'OGMD English dialogue native spacing v2':{'Patch':[]}}}
        (runtime/'patches/imported_patch.yml').write_text(yaml.safe_dump(old))
        # Valid for RPCS3, but rejected by PyYAML's duplicate-anchor check.
        # An unrelated community catalog must remain byte-for-byte intact.
        (runtime/'patches/patch.yml').write_text('Version: 1.2\nPPU-first: {Value: &shared 1}\nPPU-second: {Value: &shared 2}\n')
        (runtime/'config/patch_config.yml').write_text(yaml.safe_dump({'PPU-other':{'Preserve':True},PPU:{'OGMD English dialogue native spacing v2':{}}}))
        game=runtime/'dev_hdd0/game/BLJS10335';(game/'USRDIR/PSARC').mkdir(parents=True)
        (game/'PARAM.SFO').write_bytes(b'BLJS10335'.ljust(2048,b'\0'));(game/'ICON0.PNG').write_bytes(b'old icon')
        build=root/'build';(build/'native').mkdir(parents=True);archives=[]
        for n in ['Logic','Common','Battle','General2d','General3d']:
            target=game/'USRDIR/PSARC'/(n+'.psarc.sdat');target.write_bytes(b'old '+n.encode());os.utime(target,ns=(100000000000,100000000000))
            payload=build/'native'/target.name;payload.write_bytes(b'english '+n.encode())
            archives.append(dict(name=n,file='native/'+target.name,size=payload.stat().st_size,before=digest(target),after=digest(payload),mtime_ns=200000000000))
        manifest=build/'patch.json';atomic_json(manifest,dict(status='ready',profile=profile,archives=archives))
        return runtime,game,manifest

    def snapshot(self,runtime):
        return {str(p.relative_to(runtime)):(p.read_bytes(),p.stat().st_mtime_ns) for p in runtime.rglob('*') if p.is_file()}

    def test_runtime_setup_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp));before=self.snapshot(runtime)
            plan=prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime')
            result=apply_setup(plan,closed_check=lambda _:None)
            self.assertEqual(result['status'],'installed');self.assertGreater(result['installed_kb'],result['required_kb'])
            config=yaml.safe_load((runtime/'config/custom_configs/config_BLJS10335.yml').read_text())
            self.assertEqual(config['Video']['Resolution Scale'],200);self.assertFalse(config['Core']['SPU Cache'])
            self.assertEqual(config['Core']['Libraries Control'],['other.sprx:lle','libvdec.sprx:lle'])
            settings=yaml.safe_load((runtime/'config/patch_config.yml').read_text());self.assertTrue(settings['PPU-other']['Preserve'])
            self.assertTrue(settings[PPU][PATCH][GAME]['BLJS10335']['01.00']['Enabled'])
            self.assertEqual((game/'ICON0.PNG').read_bytes(),(DATA/'install_icon.png').read_bytes())
            self.assertEqual((game/'ICON0.PNG').stat().st_mtime_ns,200000000000)
            installed=self.snapshot(runtime);checks=[0]
            def interrupt(_):
                checks[0]+=1
                if checks[0]==3:raise OSError('Injected restore interruption')
            with self.assertRaises(OSError):restore_setup(plan,closed_check=interrupt)
            self.assertEqual(installed,self.snapshot(runtime))
            restore_setup(plan,closed_check=lambda _:None);self.assertEqual(before,self.snapshot(runtime))

    def test_runtime_failed_write_recovers_and_later_changes_block_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp));before=self.snapshot(runtime)
            plan=prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime')
            import runtime_setup as rs
            original=rs.atomic_copy;calls=[0]
            def fail(source,target,expected,mtime_ns):
                if Path(target).is_relative_to(runtime):
                    calls[0]+=1
                    if calls[0]==3:raise OSError('Injected disk failure')
                return original(source,target,expected,mtime_ns)
            with patch.object(rs,'atomic_copy',fail),self.assertRaises(OSError):apply_setup(plan,closed_check=lambda _:None)
            self.assertEqual(before,self.snapshot(runtime))
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp));plan=prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime')
            apply_setup(plan,closed_check=lambda _:None)
            (runtime/'config/patch_config.yml').write_text('User: later edit')
            changed=self.snapshot(runtime)
            with self.assertRaises(ValueError):restore_setup(plan,closed_check=lambda _:None)
            self.assertEqual(changed,self.snapshot(runtime))

    def test_script_setup_does_not_replace_installed_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp),'script-only');before=self.snapshot(game)
            plan=prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime');apply_setup(plan,closed_check=lambda _:None)
            self.assertEqual(before,self.snapshot(game))

    def test_patch_is_discovered_by_rpcs3_boot_loader_and_preserves_title_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp))
            title=runtime/'patches/BLJS10335_patch.yml'
            title.write_text(yaml.safe_dump({'Version':1.2,PPU:{'Unrelated OGMD patch':{'Patch':[['be32',100,200]]}}}))
            result=setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            # Utilities/bin_patch.cpp: append_global_patches / append_title_patches.
            boot_paths=[runtime/'patches/patch.yml',runtime/'patches/imported_patch.yml',title]
            self.assertIn(Path(result['patch_path']),boot_paths)
            patches=yaml.safe_load(title.read_text())
            self.assertIn('Unrelated OGMD patch',patches[PPU])
            expected=yaml.safe_load((ROOT/'script_editor/assets/runtime/spacing.yml').read_text())[PPU][PATCH]
            self.assertEqual(patches[PPU][PATCH],expected)
            self.assertIn('0x00b7f9a8',title.read_text())
            with self.assertRaises(ValueError):verify_patch_address_format(yaml.safe_dump(patches))
            self.assertEqual(yaml.safe_load(dump_patch_yaml(patches)),patches)
            other={'Patch':[['bef32',16,3],['bpex',32,0],['cutf8',48,'test']]}
            encoded=dump_patch_yaml(other)
            self.assertEqual(yaml.safe_load(encoded),other)
            for address in ('0x00000010','0x00000020','0x00000030'):self.assertIn(address,encoded)
            verify_runtime(runtime,ROOT/'script_editor/assets/runtime')

    def test_repair_rechecks_disk_and_can_use_a_different_selected_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime,game,manifest=self.fixture(root)
            first=setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            first_bytes=Path(first['setup_plan']).read_bytes()
            (runtime/'patches/BLJS10335_patch.yml').unlink()
            (runtime/'config/patch_config.yml').write_text('Other: retained\n')
            second=setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            self.assertNotEqual(first['setup_plan'],second['setup_plan'])
            self.assertEqual(first_bytes,Path(first['setup_plan']).read_bytes())
            self.assertTrue(second['patch_enabled'])
            self.assertEqual(yaml.safe_load((runtime/'config/patch_config.yml').read_text())['Other'],'retained')
            import shutil
            alternate=root/'another_rpc';alternate.mkdir();(alternate/'rpcs3.exe').write_bytes(b'QA')
            result=setup_runtime(alternate,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            self.assertEqual(Path(result['patch_path']),alternate/'patches/BLJS10335_patch.yml')
            self.assertTrue((runtime/'patches/BLJS10335_patch.yml').is_file())

    def test_global_config_location_and_custom_preferences_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp))
            (runtime/'config/config.yml').write_text(yaml.safe_dump({'Video':{'Resolution Scale':150,'Renderer':'Vulkan'},'Audio':{'Master Volume':63}}))
            custom=runtime/'config/custom_configs/config_BLJS10335.yml';custom.parent.mkdir()
            custom.write_text(yaml.safe_dump({'Video':{'Resolution Scale':250},'Core':{'SPU Cache':True}}))
            setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            actual=yaml.safe_load(custom.read_text())
            self.assertEqual(actual['Video'],{'Resolution Scale':250,'Renderer':'Vulkan'})
            self.assertEqual(actual['Audio']['Master Volume'],63)

    def test_legacy_ignored_file_and_failed_preparation_do_not_block_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime,game,manifest=self.fixture(Path(tmp))
            legacy=runtime/'patches/ogmd_full_english.yml'
            legacy.write_bytes((ROOT/'script_editor/assets/runtime/spacing.yml').read_bytes());legacy_before=legacy.read_bytes()
            settings=runtime/'config/config.yml'
            settings.write_text('Core:\n  Libraries Control: invalid\n')
            with self.assertRaises(ValueError):prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime')
            settings.write_text('Core:\n  Libraries Control: []\n')
            result=setup_runtime(runtime,manifest,ROOT/'script_editor/assets/runtime',closed_check=lambda _:None)
            self.assertTrue(result['patch_enabled']);self.assertEqual(legacy_before,legacy.read_bytes())

    def test_folder_output_preserves_original_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime,game,manifest=self.fixture(root)
            source=root/'vanilla';source.mkdir();import shutil
            shutil.copytree(game,source/'PS3_GAME');(source/'disc.dat').write_bytes(b'unchanged disc file')
            doc=json.loads(manifest.read_text());doc.update(kind='ogmd-full-folder',source=str(source),game_root=str(source/'PS3_GAME'))
            for a in doc['archives']:a['mtime_ns']=100000000000
            atomic_json(manifest,doc);before=self.snapshot(source)
            output=root/'English';result=write_full_game(manifest,output)
            self.assertEqual(result['status'],'verified');self.assertEqual(before,self.snapshot(source))
            self.assertEqual((output/'disc.dat').read_bytes(),b'unchanged disc file')
            plan=prepare_setup(runtime,manifest,ROOT/'script_editor/assets/runtime');apply_setup(plan,closed_check=lambda _:None)
            games=yaml.safe_load((runtime/'config/games.yml').read_text())
            self.assertEqual(games['BLJS10335'],str(output).replace('\\','/'))
            with self.assertRaises(ValueError):write_full_game(manifest,output)


if __name__=='__main__':unittest.main()
