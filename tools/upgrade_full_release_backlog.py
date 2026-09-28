"""Stage release 1.4 from 1.3 without rebuilding accepted translation edits."""
from pathlib import Path
import copy,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json
from full_patch import package_info
from archive_patch import digest
from backlog_layout import ENTRY,FEATURE,patch_backlog
from vendor.psarc import Psarc
from vendor import sdat
from release_delta import build_recipe,apply_recipe,sdat_metadata


def main():
    source=ROOT/'full_patcher/data';out=ROOT/'full_patcher/data_v14'
    old=package_info(source);release=copy.deepcopy(old)
    assert old['release']=='OGMD Full English 1.3'
    if out.exists():raise ValueError('Staging folder already exists; inspect before rebuilding.')
    tested=ROOT/'work/poc/backlog_margin_20260913'
    plain=tested/'General2d.psarc';encrypted=tested/'General2d.psarc.sdat'
    assert digest(plain)=='999bf328c8ad2b9b7792f012269ab50804be7396ae250fcf4c4b6ed4c6043340'
    assert digest(encrypted)=='c9ef5529801614e463a732ef9646a8899fcbbc5b33db08fb8c160c77a6027971'
    arc=Psarc(plain);raw=arc._read_file(next(e for e in arc.entries if e.name==ENTRY))
    assert patch_backlog(raw)[1]['already_applied']
    shutil.copytree(source,out)
    item=next(a for a in release['archives'] if a['name']=='General2d')
    # These three explicit staged copies alone are replaced.
    for key in ('recipe','blob','metadata'):(out/item[key]).unlink()
    vanilla=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/General2d.psarc'
    print('Building the General2d release delta…',flush=True)
    recipe=build_recipe(vanilla,plain,out/item['blob'])
    atomic_json(out/item['recipe'],recipe)
    (out/item['metadata']).write_bytes(sdat_metadata(encrypted))
    check=ROOT/'work/poc/backlog_release_20260914';check.mkdir(exist_ok=False)
    rebuilt=check/'General2d.psarc';replayed=check/'General2d.psarc.sdat'
    print('Reconstructing the release and checking SDAT metadata replay…',flush=True)
    apply_recipe(vanilla,out/item['blob'],recipe,rebuilt)
    sdat.encrypt(rebuilt,replayed,vanilla.with_suffix('.psarc.sdat'),verbose=False)
    sdat_metadata(replayed,(out/item['metadata']).read_bytes())
    assert digest(rebuilt)==digest(plain) and digest(replayed)==digest(encrypted)
    assert sdat.verify(replayed,expect_plain=rebuilt,verbose=False)
    for key in ('recipe','blob','metadata'):item[key+'_sha256']=digest(out/item[key])
    item.update(target_sdat_sha256=digest(encrypted),backlog_margin_width=720)
    release.update(release='OGMD Full English 1.4',backlog_margin_width=720,backlog_user_confirmed=True)
    release['features'].append(FEATURE)
    release['package_bytes']=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    atomic_json(out/'release.json',release);package_info(out)
    assert release['review']==old['review'] and release['edited_rows']==old['edited_rows']==801
    for previous,current in zip(old['archives'],release['archives']):
        if current['name']!='General2d':assert previous==current
    for file in source.rglob('*'):
        if file.is_file() and file.name not in ('release.json',item['recipe'],item['blob'],item['metadata']):
            assert digest(file)==digest(out/file.relative_to(source))
    atomic_json(check/'verification.json',dict(status='verified',exact_user_tested_archive=True,
        plain_sha256=digest(rebuilt),sdat_sha256=digest(replayed),sdat_all_blocks_verified=True,
        other_four_archives_unchanged=True,accepted_801_edits_unchanged=True))
    print('Release 1.4 staged and verified against the user-tested archive.',flush=True)


if __name__=='__main__':main()
