"""Build the new release offline and verify the two actual native payloads."""
from pathlib import Path
import json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from full_patch import prepare_full_patch,package_info
from core import atomic_json
from archive_patch import digest
from vendor.psarc import Psarc
from vendor import sdat


def main():
    work=ROOT/'work/poc/startup_assets_20260915';data=ROOT/'full_patcher/data_v16';release=package_info(data)
    build=work/'full_build_check'
    if not build.exists():
        manifest=prepare_full_patch(data,ROOT/'work/ps3_disc',build,lambda s:print(s,flush=True))
    else:
        manifest=build/'full_patch.json'
        assert json.loads(manifest.read_text(encoding='utf8'))['status']=='ready'
    doc=json.loads(manifest.read_text(encoding='utf8'));assert doc['version']==2 and doc['movie'] and len(doc['archives'])==5
    assert doc['edited_rows']==918
    for item in release['archives']:
        assert digest(build/'native'/(item['name']+'.psarc.sdat'))==item['target_sdat_sha256']
    assert digest(build/'native/Movie.psarc')==release['movie']['target_sha256']
    checked=work/'Common.from_release.psarc'
    sdat.decrypt(build/'native/Common.psarc.sdat',checked,verbose=False)
    arc=Psarc(checked);name='/Dat/Logo/@Ja/@ps3/CESA_720.dds'
    assert arc._read_file(next(e for e in arc.entries if e.name==name))==(work/'CESA_720.dds').read_bytes()
    assert sdat.verify(build/'native/Common.psarc.sdat',expect_plain=checked,verbose=False)
    arc=Psarc(build/'native/Movie.psarc');name='/Dat/Movie/m_op_02.pam'
    assert arc._read_file(next(e for e in arc.entries if e.name==name))==(work/'m_op_02.english.pam').read_bytes()
    source=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Movie.psarc'
    old=Psarc(source)
    assert [(e.name,e.size,e.offset,e.md5) for e in arc.entries]==[(e.name,e.size,e.offset,e.md5) for e in old.entries]
    assert arc.block_table==old.block_table
    target=build/'native/Movie.psarc';entry=next(e for e in arc.entries if e.name==name)
    with source.open('rb') as a,target.open('rb') as b:
        offset=0
        while True:
            left=a.read(8*1024*1024);right=b.read(len(left))
            if not left:break
            lo=max(entry.offset,offset)-offset;hi=min(entry.offset+entry.size,offset+len(left))-offset
            if lo<hi:
                assert left[:lo]==right[:lo] and left[hi:]==right[hi:]
            else:assert left==right
            offset+=len(left)
    atomic_json(work/'full_build_verification.json',dict(status='verified',release=release['release'],manifest=str(manifest),
        five_sdat_archives_verified=True,movie_recipe_reconstructed=True,notice_pixels_verified=True,
        movie_payload_verified=True,movie_toc_and_all_other_movie_bytes_preserved=True,
        edited_rows_preserved=918,user_game_modified=False,emulator_started=False,in_game_test=False))
    print('Real release reconstruction and both startup payloads verified.',flush=True)


if __name__=='__main__':main()
