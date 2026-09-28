"""Stage 1.5 with banner corrections and the independently checked battle ELF."""
import copy,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import Corpus,EditProject,atomic_json
from patcher import collect_changes,compile_entry
from full_patch import package_info
from archive_patch import digest,repack
from vendor.psarc import Psarc
from vendor import sdat
from release_delta import build_recipe,apply_recipe,sdat_metadata
from edit_bundle import export_bundle

def main():
    work=ROOT/'work/poc/editor_v39_20260914';out=ROOT/'full_patcher/data_v15';source=ROOT/'full_patcher/data'
    assert json.loads((work/'battle_fit/verification.json').read_text())['status']=='passed'
    old=package_info(source);assert old['release']=='OGMD Full English 1.4'
    release=copy.deepcopy(old);shutil.copytree(source,out)
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908');project=EditProject(corpus,work/'location_corrections.json')
    key='07_Location_banners/Locations'
    for row in corpus.load(key)[0]['rows']:
        if 'Hagwane' in row['en']:project.set(key,row,'en',row['en'].replace('Hagwane','Hagane'))
    project.save();export_bundle(project,work/'location_patch_edits.json')
    groups=collect_changes(project,'en');assert len(groups)>0
    base=ROOT/'work/poc/full_release_20260910_v12/Logic.psarc'
    arc=Psarc(base);entries={e.name:e for e in arc.entries};overrides={};review=[]
    for (name,entry),items in groups.items():
        assert name=='Logic'
        overrides[entry],details=compile_entry(arc._read_file(entries[entry]),items,'en');review.extend(dict(archive=name,entry=entry,**r) for r in details)
    plain=work/'Logic.psarc';encrypted=work/'Logic.psarc.sdat'
    # This accepted Logic is identical to release 1.4's target before these edits.
    old_item=next(a for a in old['archives'] if a['name']=='Logic')
    assert digest(base)==json.loads((source/'Logic.recipe.json').read_text())['target_sha256']
    repack(base,plain,overrides)
    vanilla=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc'
    sdat.encrypt(plain,encrypted,vanilla.with_suffix('.psarc.sdat'),verbose=False)
    assert sdat.verify(encrypted,expect_plain=plain,verbose=False)
    item=next(a for a in release['archives'] if a['name']=='Logic')
    for k in ('recipe','blob','metadata'):(out/item[k]).unlink()
    recipe=build_recipe(vanilla,plain,out/item['blob']);atomic_json(out/item['recipe'],recipe)
    (out/item['metadata']).write_bytes(sdat_metadata(encrypted))
    replay=work/'Logic.replayed.psarc';apply_recipe(vanilla,out/item['blob'],recipe,replay)
    assert digest(replay)==digest(plain)
    verified=Psarc(plain)
    for e in verified.entries:
        expected=overrides.get(e.name)
        if expected is None:expected=arc._read_file(entries[e.name])
        assert verified._read_file(e)==expected,e.name
    for k in ('recipe','blob','metadata'):item[k+'_sha256']=digest(out/item[k])
    item.update(target_sdat_sha256=digest(encrypted),size=encrypted.stat().st_size,plain_size=plain.stat().st_size,
                location_banner_fields=project.count())
    assets=work/'battle_fit/native_eboot';info=json.loads((assets/'assets.json').read_text())
    for p in assets.iterdir():shutil.copy2(p,out/'native_eboot'/p.name)
    release.update(release='OGMD Full English 1.5',embedded_eboot_sha256=info['sha256'],embedded_elf_sha256=info['elf_sha256'],
        embedded_ppu=info['ppu'],battle_text_right_edge=1136,battle_fit_visual_tested=False,location_banner_corrections=project.count())
    release['features'] += ['Battle subtitles fit inside the dialogue frame; fresh battle visual check pending.',
        'Location banners use Hagane; editor corrections support locations, Spirit Commands and weapon names.']
    release['edited_rows']+=project.count();release['review']+=review
    atomic_json(out/'release.json',release);package_info(out)
    atomic_json(work/'release_verification.json',dict(status='verified',banner_fields=project.count(),banner_scripts=len(groups),
        accepted_801_edits_preserved=release['review'][:len(old['review'])]==old['review'],unchanged_native_entries_verified=True,
        other_four_archives_unchanged=old['archives'][1:]==release['archives'][1:],sdat_all_blocks_verified=True,
        recipe_replay_verified=True,logic_plain_sha256=digest(plain),logic_sdat_sha256=digest(encrypted)))
    print(f'Release 1.5 staged: {project.count()} banner fields in {len(groups)} scripts.',flush=True)

if __name__=='__main__':main()
