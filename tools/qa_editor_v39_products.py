"""Build real full-release corrections and the user's current edit snapshot offline."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import Corpus,EditProject,NativeMetrics,atomic_json
from full_patch import prepare_full_patch
from patcher import prepare_patch,compile_entry,collect_changes
from edit_bundle import export_bundle
from archive_patch import digest
from vendor import sdat
from vendor.psarc import Psarc

def main():
    work=ROOT/'work/poc/editor_v39_20260914';data=ROOT/'full_patcher/data_v15';c=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    p=EditProject(c,work/'qa_project.json')
    for key,value in [('06_Game_data/Spirit_commands','QA Spirit'),('06_Game_data/Weapon_names','QA Weapon'),('07_Location_banners/Locations','QA Location')]:
        row=next(r for r in c.load(key)[0]['rows'] if r['en'] and r.get('en') not in ('Dummy','dummy'))
        p.set(key,row,'en',value)
    bundle=export_bundle(p,work/'qa_patch_edits.json')
    progress=lambda text:print(text,flush=True)
    manifest=prepare_full_patch(data,ROOT/'work/ps3_disc',work/'full_qa',progress,edits=bundle)
    doc=json.loads(manifest.read_text(encoding='utf8'));assert doc['status']=='ready' and len(doc['archives'])==5
    assert len(doc['editor_corrections_review'])==3
    base=work/'Logic.psarc';checked=work/'Logic.qa_checked.psarc'
    sdat.decrypt(manifest.parent/'native/Logic.psarc.sdat',checked,verbose=False)
    a,b=Psarc(base),Psarc(checked);old={e.name:a._read_file(e) for e in a.entries};groups=collect_changes(p,'en')
    expected={entry:compile_entry(old[entry],items,'en')[0] for (archive,entry),items in groups.items()}
    for e in b.entries:assert b._read_file(e)==expected.get(e.name,old[e.name]),e.name
    # Prepare the real saved edits against the installed game. No installation.
    user=EditProject(c,ROOT/'script_editor/edits/project.json');project_before=digest(user.path)
    target=Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC')
    snapshots={f.name:digest(f) for f in target.glob('*.sdat') if f.name in ('Logic.psarc.sdat','Common.psarc.sdat','Battle.psarc.sdat','General2d.psarc.sdat')}
    editor=prepare_patch(user,'en',[target],ROOT/'script_editor/builds/v39_current_edits_20260914',NativeMetrics(ROOT/'script_editor/assets/font.bin'),progress=progress)
    assert digest(user.path)==project_before
    assert snapshots=={name:digest(target/name) for name in snapshots}
    atomic_json(work/'products_verification.json',dict(status='verified',full_build=str(manifest),full_editor_corrections=3,
        full_five_archives_verified=True,full_corrections_native_entries_verified=True,editor_build=str(editor),
        saved_project_sha256=project_before,installed_archives_before=snapshots,installed_archives_preserved=True,installed=False,emulator_started=False))
    print('Both real product paths passed; current edits ready to install.',flush=True)

if __name__=='__main__':main()
