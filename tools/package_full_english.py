"""Build exact-size, fully checked PS3 archives for the complete English pass."""
from pathlib import Path
import sys,json,hashlib,types,zlib,gc,argparse,struct
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'work/poc/full_english_20260906'
sys.path[:0]=[str(ROOT/'work/pydeps'),str(Path(__file__).resolve().parents[1] / 'script_editor/vendor')]
from psarc import Psarc
import sdat
ARCHIVES=['Logic','Common','General2d','Battle','General3d']
SOURCE=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def manifest():
    index={};arcs={a:Psarc(SOURCE/(a+'.psarc')) for a in ARCHIVES}
    for a,arc in arcs.items():
        for e in arc.entries:index.setdefault(e.name,[]).append(a)
    rows=[];seen=set()
    def add(a,name,path):
        assert a in index.get(name,[]) and (a,name) not in seen,(a,name)
        seen.add((a,name));rows.append(dict(archive=a,entry=name,file=str(path.resolve()),size=path.stat().st_size,sha256=digest(path)))
    for f in sorted((OUT/'story').iterdir()):
        names=[n for n in index if n.rsplit('/',1)[-1]==f.name]
        assert len(names)==1 and len(index[names[0]])==1,(f,names)
        add(index[names[0]][0],names[0],f)
    for f in sorted((OUT/'fixed').glob('*.dat')):
        if f.name=='WeaponData_Temp.dat':continue
        add('Logic','/Dat/FixedData/'+f.name,f)
    for f in sorted((OUT/'battle').rglob('*.bmd')):add('Battle','/'+f.relative_to(OUT/'battle').as_posix(),f)
    for f in sorted((OUT/'ui').rglob('*')):
        if not f.is_file():continue
        rel=f.relative_to(OUT/'ui');a=rel.parts[0];name='/'+Path(*rel.parts[1:]).as_posix()
        assert name!='/Dat/Font/font.bin' and not any(name.endswith(f'exFont{i:02d}.bin') for i in range(2,6))
        add(a,name,f)
    result=dict(format=1,overrides=rows,archives=[dict(name=a,source=str(SOURCE/(a+'.psarc')),source_sha256=digest(SOURCE/(a+'.psarc')),source_size=(SOURCE/(a+'.psarc')).stat().st_size,template_sha256=digest(SOURCE/(a+'.psarc.sdat'))) for a in ARCHIVES])
    (OUT/'build_manifest.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(dict(overrides=len(rows),archives={a:sum(r['archive']==a for r in rows) for a in ARCHIVES})),flush=True)
    return result

def build(a,doc):
    rows=[r for r in doc['overrides'] if r['archive']==a]
    ar=next(r for r in doc['archives'] if r['name']==a)
    assert digest(ar['source'])==ar['source_sha256']
    for r in rows:assert digest(r['file'])==r['sha256']
    dest=OUT/'archives';dest.mkdir(exist_ok=True)
    plain=dest/(a+'.psarc');encrypted=dest/(a+'.psarc.sdat');report_path=dest/(a+'.verification.json')
    fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    if report_path.exists():
        old=json.loads(report_path.read_text())
        if old.get('manifest_fingerprint')==fingerprint and old['source_sha256']==ar['source_sha256'] and digest(plain)==old['plain_sha256'] and digest(encrypted)==old['sdat_sha256']:
            print(a+': verified build already current',flush=True);return
    arc=Psarc(ar['source']);overrides={r['entry']:Path(r['file']).read_bytes() for r in rows}
    # Cache compression so the exact-size second pass reuses identical data.
    cache={};compress=arc._compress_file
    # A previous partial or verified archive can supply compressed streams
    # only after they decode to the current exact replacement bytes. This
    # avoids repeating expensive image compression after a text-only edit.
    if plain.exists():
        candidate=Psarc(plain)
        assert candidate.block_size==arc.block_size and candidate.bt_width==arc.bt_width
        previous={e.name:e for e in candidate.entries};reused=0
        with plain.open('rb') as stream:
            for name,data in overrides.items():
                e=previous.get(name)
                if e is None or candidate._read_file(e)!=data:continue
                stream.seek(e.offset);blocks=[]
                for i in range((len(data)+arc.block_size-1)//arc.block_size):
                    clen=candidate.block_table[e.block_index+i];raw=stream.read(clen or arc.block_size)
                    if clen:
                        try:
                            decoder=zlib.decompressobj();decoder.decompress(raw)
                            if decoder.eof and decoder.unused_data:
                                raw=raw[:-len(decoder.unused_data)];clen=len(raw)
                        except zlib.error:pass
                    blocks.append((clen,raw))
                cache[hashlib.sha256(data).digest()]=blocks;reused+=1
        del candidate
        print(a+': reused '+str(reused)+' verified replacement streams',flush=True)
    def cached(self,data):
        key=hashlib.sha256(data).digest()
        if key not in cache:cache[key]=compress(data)
        return cache[key]
    arc._compress_file=types.MethodType(cached,arc)
    print(a+': packing '+str(len(rows))+' replacements',flush=True)
    arc.pack(plain,overrides=overrides)
    padding=ar['source_size']-plain.stat().st_size
    print(a+': initial size difference '+str(-padding),flush=True)
    recompressed={}
    if padding<0 and a!='Common':
        # Recover space from unchanged source assets using lossless zlib-9.
        # Original archives often use less thorough compression. A source
        # offset can have aliases, so update every member of the same group.
        groups={}
        for entry in arc.entries:
            if entry.name not in overrides:groups.setdefault(entry.offset,[]).append(entry)
        for group in sorted(groups.values(),key=lambda g:sum(len(raw) for _,raw in g[0]._blocks),reverse=True):
            entry=group[0];original=arc._read_file(entry)
            blocks=compress(original);old_size=sum(len(raw) for _,raw in entry._blocks);new_size=sum(len(raw) for _,raw in blocks)
            # Compression may change block count for unusual source streams.
            # Keep the original block count here to preserve the TOC size.
            if len(blocks)!=len(entry._blocks) or new_size>=old_size:continue
            recovered=bytearray()
            for clen,raw in blocks:
                try:recovered.extend(zlib.decompress(raw))
                except zlib.error:recovered.extend(raw)
            assert bytes(recovered)==original
            for alias in group:
                alias._blocks=blocks
                recompressed[alias.name]=hashlib.sha256(original).hexdigest()
            padding+=old_size-new_size
            if padding>=0:break
        print(a+': lossless source recompression '+str(len(recompressed))+' entries; size difference '+str(-padding),flush=True)
        arc.pack(plain,overrides=overrides)
        assert ar['source_size']-plain.stat().st_size==padding
    if padding<0:
        # Replacement images may already use Zopfli from an earlier pass.
        # Target unchanged source images next; retain their exact decoded
        # bytes. Stop when enough space has been recovered, and cache work.
        import zopfli.zlib
        maximum=(1<<(8*arc.bt_width))-1
        groups={}
        for entry in arc.entries:
            if entry.name not in overrides:groups.setdefault(entry.offset,[]).append(entry)
        cache_dir=OUT/'compression_cache';cache_dir.mkdir(exist_ok=True)
        for group in sorted(groups.values(),key=lambda g:sum(len(raw) for _,raw in g[0]._blocks),reverse=True):
            entry=group[0];original=arc._read_file(entry);key=hashlib.sha256(original).hexdigest()
            stored=cache_dir/(key+'.blocks');blocks=entry._blocks;old_size=sum(len(raw) for _,raw in blocks)
            improved=[]
            if stored.exists():
                blob=stored.read_bytes();bs,count=struct.unpack_from('>II',blob,4);assert blob[:4]==b'OGCZ' and bs==arc.block_size
                pos=12
                for _ in range(count):
                    clen,n=struct.unpack_from('>II',blob,pos);pos+=8;improved.append((clen,blob[pos:pos+n]));pos+=n
                assert pos==len(blob)
            else:
                for clen,raw in blocks:
                    try:data=zlib.decompress(raw)
                    except zlib.error:data=raw
                    packed=zopfli.zlib.compress(data,numiterations=5)
                    improved.append((len(packed),packed) if len(packed)<len(raw) and len(packed)<=maximum else (clen,raw))
                stored.write_bytes(b'OGCZ'+struct.pack('>II',arc.block_size,len(improved))+b''.join(struct.pack('>II',clen,len(raw))+raw for clen,raw in improved))
            recovered=bytearray()
            for clen,raw in improved:
                try:recovered.extend(zlib.decompress(raw))
                except zlib.error:recovered.extend(raw)
            assert bytes(recovered)==original and len(improved)==len(blocks)
            saved=old_size-sum(len(raw) for _,raw in improved)
            if saved<=0:continue
            for alias in group:alias._blocks=improved;recompressed[alias.name]=key
            padding+=saved
            print(a+': saved '+str(saved)+' bytes on '+entry.name+'; remaining '+str(max(0,-padding)),flush=True)
            if padding>=0:break
        arc.pack(plain,overrides=overrides)
        assert ar['source_size']-plain.stat().st_size==padding
    assert padding>=0,(a,'English build does not fit native archive',padding)
    # Pad valid zlib streams, distributing padding within the block-table
    # integer limit. Decompression ignores bytes after the end of the stream.
    remaining=padding;maximum=(1<<(8*arc.bt_width))-1;padded=[]
    for name,data in overrides.items():
        key=hashlib.sha256(data).digest();blocks=list(cache[key])
        for i,(clen,raw) in enumerate(blocks):
            if not remaining:break
            if not clen or len(raw)>=maximum:continue
            try:zlib.decompress(raw)
            except zlib.error:continue
            amount=min(remaining,maximum-len(raw));blocks[i]=(len(raw)+amount,raw+bytes(amount));remaining-=amount
            padded.append(dict(entry=name,block=i,bytes=amount))
        cache[key]=blocks
        if not remaining:break
    assert remaining==0,(a,'Insufficient verified compressed padding capacity',remaining)
    arc.pack(plain,overrides=overrides);assert plain.stat().st_size==ar['source_size']
    rebuilt=Psarc(plain);assert len(arc.entries)==len(rebuilt.entries)
    changed=unchanged=0;checked=set()
    with plain.open('rb') as stream:
        for old,new in zip(arc.entries,rebuilt.entries):
            assert old.name==new.name and old.md5==new.md5
            if new.name in overrides:
                assert rebuilt._read_file(new)==overrides[new.name],new.name
                changed+=1;continue
            if new.name in recompressed:
                assert hashlib.sha256(rebuilt._read_file(new)).hexdigest()==recompressed[new.name],new.name
                unchanged+=1;continue
            assert old.size==new.size
            pair=(old.offset,new.offset)
            if pair not in checked:
                stream.seek(new.offset)
                for i,(clen,raw) in enumerate(old._blocks):
                    assert rebuilt.block_table[new.block_index+i]==clen
                    assert stream.read(len(raw))==raw,new.name
                checked.add(pair)
            unchanged+=1
    assert changed==len(rows)
    del arc,rebuilt,overrides,cache,compress,cached;gc.collect()
    print(a+': all '+str(changed)+' replacements and '+str(unchanged)+' unchanged entries verified; encrypting',flush=True)
    template=SOURCE/(a+'.psarc.sdat');assert digest(template)==ar['template_sha256']
    sdat.encrypt(plain,encrypted,template,verbose=False)
    assert encrypted.stat().st_size==template.stat().st_size
    assert sdat.verify(encrypted,expect_plain=plain,verbose=False)
    report=dict(archive=a,source_sha256=ar['source_sha256'],manifest_fingerprint=fingerprint,plain_sha256=digest(plain),sdat_sha256=digest(encrypted),plain_size=plain.stat().st_size,sdat_size=encrypted.stat().st_size,exact_native_sizes=True,replaced_entries_verified=changed,unchanged_entries_verified=unchanged,losslessly_recompressed_source_entries=recompressed,sdat_all_block_hashes_and_plaintext_verified=True,padding_bytes=padding,padding=padded)
    report_path.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(a+': complete '+report['sdat_sha256'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',choices=ARCHIVES);p.add_argument('--manifest-only',action='store_true');args=p.parse_args()
    doc=manifest()
    if not args.manifest_only:
        for a in ([args.archive] if args.archive else ARCHIVES):build(a,doc)
