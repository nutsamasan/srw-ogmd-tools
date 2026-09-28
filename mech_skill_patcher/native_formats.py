"""Native readers copied from the verified local OGMD conversion tools."""
import struct
from bisect import bisect_left
from collections import defaultdict


def _dialogue_pool(texts,share_suffixes=False):
    """Pack NUL-terminated UTF-8 strings without changing their table indices."""
    encoded={text:text.encode('utf8') for text in texts}
    if any(b'\0' in raw for raw in encoded.values()):raise ValueError('Dialogue text contains a NUL character.')
    payload=bytearray();pointers={}
    if not share_suffixes:
        for text,raw in encoded.items():
            pointers[text]=0x80+len(payload);payload.extend(raw+b'\0')
    else:
        # A string-table pointer may address a complete UTF-8 suffix of another
        # NUL-terminated string. Store only maximal suffix owners. The table
        # still contains every original index, including unknown control users.
        reversed_strings=sorted(raw[::-1] for raw in encoded.values())
        owners=[raw for i,raw in enumerate(reversed_strings)
                if i+1==len(reversed_strings) or not reversed_strings[i+1].startswith(raw)]
        starts=[]
        for owner in owners:
            starts.append(0x80+len(payload));payload.extend(owner[::-1]+b'\0')
        for text,raw in encoded.items():
            i=bisect_left(owners,raw[::-1])
            assert i<len(owners) and owners[i].startswith(raw[::-1])
            pointers[text]=starts[i]+len(owners[i])-len(raw)
    return payload,[pointers[text] for text in texts]


LDBI_TEXT_FIELDS={'text':(0,16),'speaker':(0,12),'location':(9,8),'map_location':(20,8),'map_label':(20,28)}


def location_signature(command):
    """Guard a banner event while allowing its supported text pointers to move."""
    opcode=struct.unpack_from('>I',command)[0]
    if len(command)!=196 or opcode not in (9,20):raise ValueError('Unsupported location event.')
    value=bytearray(command)
    for expected,offset in LDBI_TEXT_FIELDS.values():
        if opcode==expected:value[offset:offset+4]=bytes(4)
    return value.hex()


def patch_ldbi(source,changes):
    """Change individual command text/name pointers without changing shared users."""
    count,table,offsets=parse_ldbi_table(source)
    boundary=struct.unpack_from('>I',source,0x1c)[0]
    number,start=struct.unpack_from('>II',source,0x20)
    texts=[read_cstring(source,p) for p in offsets]
    assert min(offsets)==0x80 and table+count*4<=boundary<=start
    assert all(0x80<=p and p+len(t.encode('utf8'))<table for p,t in zip(offsets,texts))
    out=bytearray(source);allowed=[];requests=[];by_index=defaultdict(list)
    for command,field,text in changes:
        if field not in LDBI_TEXT_FIELDS or not 0<=command<number:raise ValueError('Invalid dialogue command')
        p=start+command*196
        opcode,offset=LDBI_TEXT_FIELDS[field]
        if struct.unpack_from('>I',source,p)[0]!=opcode:raise ValueError('Native text event changed.')
        at=p+offset
        old_index=struct.unpack_from('>I',source,at)[0]
        assert old_index<count
        requests.append((at,old_index,text));by_index[old_index].append((at,text))
    # Reuse a pool slot only when all byte occurrences of its native 32-bit
    # reference outside the text pool belong to fields being changed together.
    # Unknown/control references therefore force a separate variant. This
    # avoids retaining a second full text corpus after a large Replace all.
    for index,uses in by_index.items():
        desired={text for at,text in uses}
        if len(desired)!=1:continue
        needle=struct.pack('>I',index);positions=set();at=source.find(needle,boundary)
        while at!=-1:positions.add(at);at=source.find(needle,at+1)
        if positions and positions<={at for at,text in uses}:texts[index]=next(iter(desired))
    intern={text:i for i,text in enumerate(texts)}
    for at,old_index,text in requests:
        if text not in intern:intern[text]=len(texts);texts.append(text)
        index=old_index if texts[old_index]==text else intern[text]
        struct.pack_into('>I',out,at,index);allowed.append((at,at+4))
    payload,new_offsets=_dialogue_pool(texts)
    new_table=align(0x80+len(payload));end=new_table+len(texts)*4
    if end>boundary:
        payload,new_offsets=_dialogue_pool(texts,share_suffixes=True)
        new_table=align(0x80+len(payload));end=new_table+len(texts)*4
    if end>boundary:raise ValueError(f'Dialogue text needs {end-boundary:,} more bytes. Shorten the edited text.')
    out[0x80:boundary]=bytes(boundary-0x80);out[0x80:0x80+len(payload)]=payload
    struct.pack_into('>I',out,0xc,len(texts));struct.pack_into('>I',out,0x14,new_table)
    struct.pack_into('>'+str(len(texts))+'I',out,new_table,*new_offsets)
    mask=bytearray(len(source))
    for a,b in [(0x80,boundary),(0xc,0x10),(0x14,0x18),*allowed]:mask[a:b]=b'\1'*(b-a)
    assert len(out)==len(source) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(source,out)))
    actual=parse_ldbi_table(out)[2]
    assert [read_cstring(out,p) for p in actual]==texts
    for command,field,text in changes:
        index=struct.unpack_from('>I',out,start+command*196+LDBI_TEXT_FIELDS[field][1])[0]
        assert read_cstring(out,actual[index])==text
    return bytes(out)


def patch_logo(source,changes):
    base,tables=parse_logo(source);t=tables[1];count=t['count'];tp=t['table']
    start=struct.unpack_from('>I',source,0x5c)[0]
    old_end=base+struct.unpack_from('>I',source,tp+count*4)[0]
    assert start==base+t['offsets'][0] and start<=old_end<=len(source)
    values=list(t['strings'])
    for index,text in changes.items():
        if not 0<=index<count:raise ValueError('Invalid map text index')
        values[index]=text
    payload=bytearray();offsets=[]
    for text in values:offsets.append(start-base+len(payload));payload.extend(text.encode('utf8')+b'\0')
    offsets.append(start-base+len(payload));end=start+len(payload)
    if end>len(source):raise ValueError(f'Map text needs {end-len(source):,} more bytes. Shorten the edited text.')
    if end>old_end and any(source[old_end:end]):raise ValueError('Map text would overwrite another section.')
    out=bytearray(source);out[start:max(end,old_end)]=bytes(max(end,old_end)-start);out[start:end]=payload
    struct.pack_into('>'+str(count+1)+'I',out,tp,*offsets)
    _,actual=parse_logo(out)
    assert len(out)==len(source) and actual[0]==tables[0] and actual[1]['strings']==values
    assert all(a==b or start<=i<max(end,old_end) or tp<=i<tp+4*(count+1) for i,(a,b) in enumerate(zip(source,out)))
    return bytes(out)


def patch_bmd(source,changes):
    counts,start,pool,texts=parse_bmd(source);out=bytearray(source[:pool]);payload=bytearray();offsets={}
    values=list(texts)
    for index,text in changes.items():
        if not 0<=index<len(values) or values[index] is None:raise ValueError('This battle record has no subtitle field.')
        values[index]=text
    for i,text in enumerate(values):
        if text is None:continue
        if text not in offsets:offsets[text]=len(payload);payload.extend(text.encode('utf8')+b'\0')
        struct.pack_into('>I',out,start+i*20+16,offsets[text])
    result=bytes(out+payload)
    assert parse_bmd(result)[3]==values and result[:start]==source[:start]
    assert all(result[start+i*20:start+i*20+16]==source[start+i*20:start+i*20+16] for i in range(counts[2]))
    return result


def read_cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError(f"string offset 0x{offset:X} is outside a {len(data)}-byte file")
    try:
        end = data.index(0, offset)
    except ValueError as exc:
        raise ValueError(f"string at 0x{offset:X} has no NUL terminator") from exc
    return data[offset:end].decode("utf-8", errors="strict")


def parse_ldbi_table(data: bytes) -> tuple[int, int, list[int]]:
    if len(data) < 0x18 or data[:4] != b"LDBI":
        raise ValueError("not an LDBI stage file")
    count = struct.unpack_from(">I", data, 0x0C)[0]
    table_offset = struct.unpack_from(">I", data, 0x14)[0]
    table_end = table_offset + count * 4
    if table_end > len(data):
        raise ValueError(
            f"LDBI table 0x{table_offset:X}-0x{table_end:X} extends past EOF"
        )
    offsets = list(struct.unpack_from(f">{count}I", data, table_offset))
    return count, table_offset, offsets


def parse_csb(data: bytes):
    if data[:8] != b"CSB \xfe\xff\x01\x00":
        raise ValueError("Unsupported CSB header")
    chunks = {}
    position = 0x18
    while position < len(data):
        tag, size, count = struct.unpack_from(">4sII", data, position)
        if size < 12 or position + size > len(data) or tag in chunks:
            raise ValueError("Invalid or duplicate CSB chunk")
        chunks[tag] = (position, size, count)
        position += size
    if position != len(data) or list(chunks) != [b"STRP", b"LNP ", b"LNT "]:
        raise ValueError("Unsupported CSB chunk layout")
    sp, ss, sc = chunks[b"STRP"]
    strings = {}
    position = sp + 12
    for _ in range(sc):
        text = read_cstring(data, position)
        strings[position] = text
        position += len(text.encode("utf-8")) + 1
    # Some shipped Archive CSBs leave up to three uninitialized alignment
    # bytes after the declared strings (including non-UTF8 bytes). These are
    # not strings. Longer reserved space must remain zero-filled.
    if position > sp + ss or (sp + ss - position >= 4 and any(data[position:sp + ss])):
        raise ValueError("STRP count or trailing padding is invalid")
    lp, ls, lc = chunks[b"LNP "]
    tp, ts, tc = chunks[b"LNT "]
    if lc != tc or struct.unpack_from(">I", data, 0x14)[0] != tc or ts != 12 + tc * 4:
        raise ValueError("Inconsistent CSB command counts")
    records = []
    for r in struct.unpack_from(f">{tc}I", data, tp + 12):
        if not lp + 12 <= r <= lp + ls - 8:
            raise ValueError("Command record is outside LNP")
        n, ptr = struct.unpack_from(">II", data, r)
        if ptr != r + 8 or ptr + n * 4 > lp + ls:
            raise ValueError("Invalid command parameter array")
        pointers = list(struct.unpack_from(f">{n}I", data, ptr))
        if any(p not in strings for p in pointers):
            raise ValueError("Command refers outside the STRP string boundaries")
        records.append(dict(offset=r, pointer_array=ptr, pointers=pointers,
                            arguments=[strings[p] for p in pointers]))
    return chunks, strings, records


def parse_logo(data):
    assert data[:4]==b'LOGO' and int.from_bytes(data[4:8],'big')==len(data)
    n,t,nn,base,m,mt=struct.unpack_from('>6I',data,0x40)
    assert n==nn and t+n*4<=mt and mt+m*4<=base
    tables=[]
    for count,table in [(n,t),(m-1,mt)]:
        offsets=struct.unpack_from('>'+str(count)+'I',data,table)
        strings=[read_cstring(data,base+x) for x in offsets]
        assert all(base+x+len(s.encode('utf8'))<len(data) for x,s in zip(offsets,strings))
        tables.append(dict(count=count,table=table,offsets=offsets,strings=strings))
    assert tables[0]['offsets'][0]==0
    return base,tables


def parse_bmd(data):
    assert data[:2] == b'\x03\x00'
    groups,conditions,lines = struct.unpack_from('>3H',data,2)
    start = 8 + groups*12 + conditions*20
    pool = start + lines*20
    assert pool <= len(data)
    texts = []
    for k in range(lines):
        offset = struct.unpack_from('>I',data,start+k*20+16)[0]
        texts.append(None if offset == 0xFFFFFFFF else read_cstring(data,pool+offset))
    return (groups,conditions,lines),start,pool,texts


def align(value, alignment=128):
    return (value + alignment - 1) // alignment * alignment


def rebuild_csb(source, edits):
    """Rebuild CSB text for {(command ordinal, argument ordinal): string}."""
    chunks, strings, records = parse_csb(source)
    sp, ss, sc = chunks[b'STRP']
    lp, ls, lc = chunks[b'LNP ']
    tp, ts, tc = chunks[b'LNT ']
    assert sp == 0x18 and lp == sp + ss and tp == lp + ls
    references = defaultdict(list)
    for k, record in enumerate(records):
        for j, ptr in enumerate(record['pointers']):
            references[ptr].append(edits.get((k,j), strings[ptr]))
    payload, new_pointers = bytearray(), {}
    def intern(text):
        if text not in new_pointers:
            new_pointers[text] = sp + 12 + len(payload)
            payload.extend(text.encode('utf8') + b'\0')
        return new_pointers[text]
    for ptr, original in strings.items():
        for text in references.get(ptr, [original]):
            intern(text)
    new_size = max(ss, align(12 + len(payload), 4))
    delta = new_size - ss
    out = bytearray(source[:sp])
    out.extend(struct.pack('>4sII',b'STRP',new_size,len(new_pointers)))
    out.extend(payload + bytes(new_size - 12 - len(payload)))
    out.extend(source[lp:])
    for k, record in enumerate(records):
        r = record['offset'] + delta
        struct.pack_into('>I',out,r+4,r+8)
        for j, original in enumerate(record['arguments']):
            struct.pack_into('>I',out,r+8+j*4,new_pointers[edits.get((k,j),original)])
        struct.pack_into('>I',out,tp+delta+12+k*4,r)
    result = bytes(out)
    _,_,actual = parse_csb(result)
    assert len(actual) == len(records)
    assert all(r['arguments'] == [edits.get((k,j),text) for j,text in enumerate(records[k]['arguments'])]
               for k,r in enumerate(actual))
    assert all(0 <= k < len(records) and 0 <= j < len(records[k]['arguments']) for k,j in edits)
    return result
