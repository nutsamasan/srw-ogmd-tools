"""Exercise the real 1.4 full build and editor builder, without installing."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from full_patch import prepare_full_patch,package_info
from core import Corpus,EditProject,atomic_json
from patcher import prepare_patch
from archive_patch import digest
from backlog_layout import ENTRY,patch_backlog
from vendor.psarc import Psarc


def main():
    root=ROOT/'work/poc/backlog_products_20260914';root.mkdir(exist_ok=True)
    data=ROOT/'full_patcher/data_v14';release=package_info(data)
    progress=lambda m:print(m,flush=True)
    manifest=root/'full/full_patch.json'
    if not manifest.exists():manifest=prepare_full_patch(data,ROOT/'work/ps3_disc',root/'full',progress=progress)
    doc=json.loads(manifest.read_text(encoding='utf8'));assert len(doc['archives'])==5 and doc['status']=='ready'
    assert doc['release_manifest_sha256']==digest(data/'release.json')
    for actual,expected in zip(doc['archives'],release['archives']):
        assert actual['name']==expected['name']
        assert actual['after']==expected['target_sdat_sha256']
        assert digest(manifest.parent/actual['file'])==actual['after']
    assert doc['review']==release['review'] and doc['edited_rows']==801
    target=root/'editor_source/USRDIR/PSARC';target.mkdir(parents=True)
    (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335')
    (target/'Logic.psarc.sdat').write_bytes(b'Unedited Logic is not loaded')
    source=ROOT/'work/poc/backlog_margin_20260913/backups/General2d.psarc.sdat'
    shutil.copy2(source,target/source.name);source_hash=digest(source)
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908');project=EditProject(corpus,root/'empty_project.json')
    editor=prepare_patch(project,'en',[target],root/'editor',progress=progress,keep_plain=True)
    edoc=json.loads(editor.read_text(encoding='utf8'));assert edoc['review']==[] and len(edoc['archives'])==1
    arc=Psarc(editor.parent/'General2d.patched.psarc');raw=arc._read_file(next(e for e in arc.entries if e.name==ENTRY))
    assert raw==(ROOT/'work/poc/backlog_margin_20260913/windowdataMain.wtd').read_bytes()
    assert digest(editor.parent/'General2d.patched.psarc')=='999bf328c8ad2b9b7792f012269ab50804be7396ae250fcf4c4b6ed4c6043340'
    assert digest(source)==source_hash==digest(target/source.name)
    assert not project.path.exists()
    atomic_json(root/'verification.json',dict(status='verified',full_build=str(manifest),editor_build=str(editor),
        full_five_archive_checksums_match_release=True,all_sdat_blocks_verified=True,
        editor_matches_user_tested_plain_archive=True,accepted_801_edits_preserved=True,
        editor_source_preserved=True,installed=False,game_started=False))
    print('Both real product builds passed.',flush=True)


if __name__=='__main__':main()
