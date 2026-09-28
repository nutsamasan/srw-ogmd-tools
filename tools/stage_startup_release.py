"""Stage the user's notice and official English intro in Full Patcher 1.6."""
from pathlib import Path
import copy,json,sys,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json
from full_patch import package_info
from archive_patch import digest,repack
from vendor.psarc import Psarc
from vendor import sdat
from release_delta import build_recipe,sdat_metadata,apply_recipe


def main():
    work=ROOT/'work/poc/startup_assets_20260915';source=ROOT/'full_patcher/data';out=ROOT/'full_patcher/data_v16'
    old=package_info(source);assert old['release']=='OGMD Full English 1.5'
    notice=json.loads((work/'notice_verification.json').read_text(encoding='utf8'))
    intro=json.loads((work/'intro_verification.json').read_text(encoding='utf8'));assert intro['status']=='verified'
    release=copy.deepcopy(old)
    if not out.exists():shutil.copytree(source,out)
    common=next(a for a in release['archives'] if a['name']=='Common')
    base=ROOT/'work/poc/full_release_20260910_v12/Common.psarc'
    assert digest(base)==json.loads((source/common['recipe']).read_text(encoding='utf8'))['target_sha256']
    entry='/Dat/Logo/@Ja/@ps3/CESA_720.dds';plain=work/'Common.psarc';encrypted=work/'Common.psarc.sdat'
    if not plain.exists():
        checked=repack(base,plain,{entry:(work/'CESA_720.dds').read_bytes()},lambda s:print(s,flush=True),optimize_images=True)
        atomic_json(work/'Common.repack.json',checked)
    checked=json.loads((work/'Common.repack.json').read_text(encoding='utf8'));assert digest(plain)==checked['sha256']
    vanilla=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Common.psarc'
    if not encrypted.exists():
        print('Encrypting and verifying the notice archive…',flush=True)
        sdat.encrypt(plain,encrypted,vanilla.with_suffix('.psarc.sdat'),verbose=False)
    assert sdat.verify(encrypted,expect_plain=plain,verbose=False)
    (out/common['blob']).unlink()
    recipe=build_recipe(vanilla,plain,out/common['blob']);atomic_json(out/common['recipe'],recipe)
    (out/common['metadata']).write_bytes(sdat_metadata(encrypted))
    common.update(target_sdat_sha256=digest(encrypted),custom_notice_sha256=notice['dds_sha256'])
    for key in ('recipe','blob','metadata'):common[key+'_sha256']=digest(out/common[key])
    # Native PAMF entries are contiguous and uncompressed; replace only those
    # bytes, without changing the Movie PSARC TOC or any other movie.
    movie_source=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Movie.psarc';arc=Psarc(movie_source)
    movie_entry=next(e for e in arc.entries if e.name=='/Dat/Movie/m_op_02.pam')
    count=(movie_entry.size+arc.block_size-1)//arc.block_size
    blocks=arc.block_table[movie_entry.block_index:movie_entry.block_index+count]
    assert all(n==0 for n in blocks[:-1]) and blocks[-1]==movie_entry.size%arc.block_size
    replacement=(work/'m_op_02.english.pam').read_bytes();assert len(replacement)==movie_entry.size
    start,end=movie_entry.offset,movie_entry.offset+movie_entry.size
    for e in arc.entries:
        if e is movie_entry:continue
        n=(e.size+arc.block_size-1)//arc.block_size
        length=sum(x or arc.block_size for x in arc.block_table[e.block_index:e.block_index+n])
        assert not (e.offset<end and e.offset+length>start)
    source_hash=hashlib.sha256();target_hash=hashlib.sha256()
    print('Fingerprinting the movie archive and its exact replacement…',flush=True)
    with movie_source.open('rb') as stream:
        for offset in range(0,movie_source.stat().st_size,8*1024*1024):
            data=stream.read(8*1024*1024);source_hash.update(data)
            lo,hi=max(start,offset),min(end,offset+len(data))
            if lo<hi:data=data[:lo-offset]+replacement[lo-start:hi-start]+data[hi-offset:]
            target_hash.update(data)
    shutil.copy2(work/'m_op_02.english.pam',out/'Movie.delta')
    size=movie_source.stat().st_size
    recipe=dict(source_sha256=source_hash.hexdigest(),target_sha256=target_hash.hexdigest(),size=size,
                blob_sha256=digest(out/'Movie.delta'),blob_size=len(replacement),
                ops=[['copy',0,start],['data',0,len(replacement)],['copy',end,size-end]])
    atomic_json(out/'Movie.recipe.json',recipe)
    release.update(version=2,release='OGMD Full English 1.6',baseline_overrides=old['baseline_overrides']+2,custom_notice=notice,
                   movie=dict(recipe='Movie.recipe.json',blob='Movie.delta',recipe_sha256=digest(out/'Movie.recipe.json'),
                              blob_sha256=recipe['blob_sha256'],source_sha256=recipe['source_sha256'],target_sha256=recipe['target_sha256'],
                              size=size,entry=movie_entry.name,verification=intro))
    release['features']+=['User-supplied English startup notice.','Official PS4 English logo animation converted to PS3 video; original audio and timing retained.']
    release['package_bytes']=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    atomic_json(out/'release.json',release);package_info(out)
    assert release['review']==old['review'] and release['edited_rows']==old['edited_rows']==918
    for a,b in zip(old['archives'],release['archives']):
        if a['name']!='Common':assert a==b
    for p in source.rglob('*'):
        if p.is_file() and p.name not in ('release.json',common['recipe'],common['blob'],common['metadata']):
            assert digest(p)==digest(out/p.relative_to(source))
    atomic_json(work/'staging_verification.json',dict(status='verified',data=str(out),notice=notice,intro=intro,
        common=checked,movie=release['movie'],other_four_archives_unchanged=True,all_918_edits_preserved=True,
        original_movies_unchanged_except_intro=True,user_game_modified=False,emulator_started=False))
    print('Release 1.6 assets staged and verified.',flush=True)


if __name__=='__main__':main()
