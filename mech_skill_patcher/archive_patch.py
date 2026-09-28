"""Streaming, exact-size PSARC rebuilding; unrelated decoded assets stay identical."""
import hashlib
import math
import shutil
import struct
import zlib
from zopfli.zlib import compress as compact_zlib
from pathlib import Path
from vendor.psarc import Psarc


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def repack(source,destination,overrides,progress=lambda text:None,optimize_images=False):
    """Copy untouched streams, recover padding if necessary, and verify every entry."""
    source=Path(source);destination=Path(destination)
    if source.resolve()==destination.resolve():raise ValueError('Rebuild into a separate output file.')
    arc=Psarc(source);entries=arc.entries
    assert (arc.ver_major,arc.ver_minor,arc.compression,arc.toc_entry_size)==(1,4,b'zlib',30)
    unknown=set(overrides)-{e.name for e in entries}
    if unknown:raise ValueError('Archive entries not found: '+str(sorted(unknown)))
    maximum=(1<<(arc.bt_width*8))-1
    segments=[];lookup={};refs=[];sizes=[]
    for i,e in enumerate(entries):
        changed=e.name in overrides;key=('new',i) if changed else ('old',e.offset)
        if key not in lookup:
            lookup[key]=len(segments)
            if changed:
                blocks=[dict(clen=n,data=b,offset=None) for n,b in arc._compress_file(overrides[e.name])]
            else:
                count=math.ceil(e.size/arc.block_size);offset=e.offset;blocks=[]
                for n in arc.block_table[e.block_index:e.block_index+count]:
                    blocks.append(dict(clen=n,data=None,offset=offset));offset+=n or arc.block_size
                assert len(blocks)==count and offset<=source.stat().st_size
            segments.append(dict(blocks=blocks,entry=e,changed=changed))
        elif segments[lookup[key]]['entry'].size!=e.size:
            raise ValueError('Unsupported archive alias with a different file size: '+e.name)
        refs.append(lookup[key]);sizes.append(len(overrides[e.name]) if changed else e.size)
    def length(block):return len(block['data']) if block['data'] is not None else block['clen'] or arc.block_size
    toc=32+len(entries)*30+sum(len(s['blocks']) for s in segments)*arc.bt_width
    total=toc+sum(length(b) for s in segments for b in s['blocks'])
    budget=source.stat().st_size;delta=budget-total
    def raw(stream,b):
        if b['data'] is not None:return b['data']
        stream.seek(b['offset']);data=stream.read(length(b))
        if len(data)!=length(b):raise ValueError('Truncated source archive')
        return data
    modified=set()
    with source.open('rb') as stream:
        # Existing game builds use trailing bytes in valid zlib streams to
        # retain native sizes. Reclaim those before recompressing any asset.
        if delta<0:
            progress('Recovering archive padding…')
            for si,s in enumerate(segments):
                for b in s['blocks']:
                    if delta>=0:break
                    if not b['clen']:continue
                    data=raw(stream,b)
                    try:
                        dec=zlib.decompressobj();dec.decompress(data)
                    except zlib.error:continue
                    if not dec.eof or not dec.unused_data:continue
                    take=min(-delta,len(dec.unused_data));b.update(data=data[:-take],clen=len(data)-take);delta+=take;modified.add(si)
                if delta>=0:break
        if delta<0:
            # Retail archives already use maximum zlib compression. Recover a
            # few bytes in small text streams before scanning large media assets.
            progress(f'Optimizing text compression; {-delta:,} bytes needed…')
            candidates=sorted(enumerate(segments),key=lambda x:(not x[1]['changed'],x[1]['entry'].size))
            processed=0
            for si,s in candidates:
                if not s['changed'] and not s['entry'].name.lower().endswith(('.bmd','.bin','.csb')):continue
                for b in s['blocks']:
                    if delta>=0:break
                    data=raw(stream,b)
                    try:plain=zlib.decompress(data) if b['clen'] and data[:1]==b'\x78' else data
                    except zlib.error:continue
                    packed=compact_zlib(plain,numiterations=5);processed+=1
                    if len(packed)<len(data) and len(packed)<=maximum:
                        delta+=len(data)-len(packed);b.update(data=packed,clen=len(packed));modified.add(si)
                    if processed%32==0:progress(f'Optimized {processed:,} text blocks; {max(0,-delta):,} bytes still needed…')
                if delta>=0:break
        if delta<0:
            progress('Recovering space with lossless compression…')
            for si,s in sorted(enumerate(segments),key=lambda x:sum(length(b) for b in x[1]['blocks']),reverse=True):
                for b in s['blocks']:
                    if delta>=0:break
                    data=raw(stream,b)
                    try:plain=zlib.decompress(data) if b['clen'] and data[:1]==b'\x78' else data
                    except zlib.error:plain=data
                    packed=zlib.compress(plain,9)
                    if len(packed)<len(data) and len(packed)<=maximum:
                        delta+=len(data)-len(packed);b.update(data=packed,clen=len(packed));modified.add(si)
                if delta>=0:break
        if delta<0 and optimize_images:
            progress('Optimizing image compression without changing pixels…')
            processed=0
            for si,s in sorted(enumerate(segments),key=lambda x:sum(length(b) for b in x[1]['blocks']),reverse=True):
                if not s['entry'].name.lower().endswith('.dds'):continue
                for b in s['blocks']:
                    if delta>=0:break
                    data=raw(stream,b)
                    try:plain=zlib.decompress(data) if b['clen'] and data[:1]==b'\x78' else data
                    except zlib.error:continue
                    best=data
                    for strategy in (zlib.Z_DEFAULT_STRATEGY,zlib.Z_FILTERED,zlib.Z_RLE):
                        compressor=zlib.compressobj(9,zlib.DEFLATED,15,9,strategy)
                        candidate=compressor.compress(plain)+compressor.flush()
                        if len(candidate)<len(best):best=candidate
                    if len(best)<len(data) and len(best)<=maximum:
                        delta+=len(data)-len(best);b.update(data=best,clen=len(best));modified.add(si)
                    processed+=1
                if processed%256<len(s['blocks']):progress(f'Checked {processed:,} image blocks; {max(0,-delta):,} bytes still needed…')
                if delta>=0:break
        if delta<0 and optimize_images:
            progress('Applying compact lossless image compression…')
            processed=0
            for si,s in sorted(enumerate(segments),key=lambda x:sum(length(b) for b in x[1]['blocks']),reverse=True):
                if not s['entry'].name.lower().endswith('.dds'):continue
                for b in s['blocks']:
                    if delta>=0:break
                    data=raw(stream,b)
                    try:plain=zlib.decompress(data) if b['clen'] and data[:1]==b'\x78' else data
                    except zlib.error:continue
                    candidate=compact_zlib(plain,numiterations=1)
                    if len(candidate)<len(data) and len(candidate)<=maximum:
                        delta+=len(data)-len(candidate);b.update(data=candidate,clen=len(candidate));modified.add(si)
                    processed+=1
                    if processed%32==0:progress(f'Compacted {processed:,} image blocks; {max(0,-delta):,} bytes still needed…')
                if delta>=0:break
        if delta<0:raise ValueError(f'Edited archive exceeds the game size by {-delta:,} bytes. Shorten the text.')
        # Pad valid streams only, staying inside the block-table integer range.
        for si,s in sorted(enumerate(segments),key=lambda x:not x[1]['changed']):
            for b in s['blocks']:
                if not delta:break
                if not b['clen'] or length(b)>=maximum:continue
                data=raw(stream,b)
                try:zlib.decompress(data)
                except zlib.error:continue
                take=min(delta,maximum-len(data));b.update(data=data+bytes(take),clen=len(data)+take);delta-=take;modified.add(si)
            if not delta:break
        if delta:raise ValueError('Insufficient compressed-stream padding capacity.')
        block_index=0;offset=toc
        for s in segments:
            s.update(block_index=block_index,offset=offset);block_index+=len(s['blocks']);offset+=sum(length(b) for b in s['blocks'])
        assert offset==budget
        progress('Writing archive…')
        with destination.open('xb') as out:
            out.write(b'PSAR'+struct.pack('>HH',arc.ver_major,arc.ver_minor)+arc.compression)
            out.write(struct.pack('>5I',toc,30,len(entries),arc.block_size,arc.archive_flags))
            for i,e in enumerate(entries):
                s=segments[refs[i]];out.write(e.md5+struct.pack('>I',s['block_index'])+sizes[i].to_bytes(5,'big')+s['offset'].to_bytes(5,'big'))
            for s in segments:
                for b in s['blocks']:out.write(b['clen'].to_bytes(arc.bt_width,'big'))
            for s in segments:
                for b in s['blocks']:out.write(raw(stream,b))
    assert destination.stat().st_size==budget
    progress('Verifying changed and unchanged archive entries…')
    actual=Psarc(destination);checked=set();changed=0
    with source.open('rb') as old,destination.open('rb') as new:
        for i,(a,b) in enumerate(zip(entries,actual.entries)):
            assert a.name==b.name and a.md5==b.md5 and b.size==sizes[i]
            if a.name in overrides:
                assert actual._read_file(b)==overrides[a.name],a.name;changed+=1;continue
            si=refs[i]
            if si in checked:continue
            checked.add(si)
            if si in modified:
                assert arc._read_file(a)==actual._read_file(b),a.name
            else:
                segment=segments[si];old.seek(a.offset);new.seek(b.offset)
                assert arc.block_table[a.block_index:a.block_index+len(segment['blocks'])]==actual.block_table[b.block_index:b.block_index+len(segment['blocks'])]
                remaining=sum(length(x) for x in segment['blocks'])
                while remaining:
                    size=min(1024*1024,remaining);assert old.read(size)==new.read(size),a.name;remaining-=size
    return dict(changed_entries=changed,unchanged_entries=len(entries)-changed,exact_size=budget,all_entries_verified=True,sha256=digest(destination))
