"""Use supported equivalent glyphs without changing the accepted font asset."""
import json,unicodedata,struct
from audit_english_glyphs import ROOT,OUT,glyph_missing,strings
from ogmd_text_formats import rebuild_ldbi_pool,parse_fixed,rebuild_fixed,rebuild_csb,parse_ldbi_table,read_cstring
from port_mltd_roll import parse_csb
from port_battle_corpus import parse_bmd
from port_mltd_stage import sha256
SPECIAL={'≥':'≧','≤':'≦','｢':'"','｣':'"','〜':'～','Ι':'I','❝':'“','❞':'”'}

def normalize(text):
    result=[]
    for c in text:
        if not glyph_missing(c):result.append(c);continue
        if c in SPECIAL:replacement=SPECIAL[c]
        else:
            assert unicodedata.name(c,'').startswith('LATIN '),repr(c)
            replacement=''.join(x for x in unicodedata.normalize('NFKD',c) if not unicodedata.combining(x))
            assert replacement and replacement.isascii(),repr(c)
        assert not any(glyph_missing(x) for x in replacement)
        result.append(replacement)
    return ''.join(result)

def build():
    findings=json.loads((OUT/'unsupported_glyphs.json').read_text(encoding='utf8'))
    files=sorted({f for r in findings.values() for f in r['files']});report=[]
    for name in files:
        path=OUT/name;source=path.read_bytes();before=strings(path);after=[normalize(t) for t in before]
        if before==after:continue
        if source[:4]==b'LDBI':
            edits={i:normalize(read_cstring(source,p)) for i,p in enumerate(parse_ldbi_table(source)[2]) if normalize(read_cstring(source,p))!=read_cstring(source,p)}
            result,_=rebuild_ldbi_pool(source,edits)
        elif source[:4]==b'FIXH':
            data=parse_fixed(source);result=rebuild_fixed(data,{i:normalize(t) for i,t in enumerate(data.strings) if normalize(t)!=t})
            assert parse_fixed(result).records==data.records
        elif source[:4]==b'CSB ':
            records=parse_csb(source)[2];edits={(k,j):normalize(t) for k,r in enumerate(records) for j,t in enumerate(r['arguments']) if normalize(t)!=t}
            result=rebuild_csb(source,edits)
        elif source[:2]==b'\x03\0':
            counts,start,pool,texts=parse_bmd(source);body=bytearray(source[:pool]);payload=bytearray();offsets={}
            for k,t in enumerate(texts):
                if t is None:continue
                t=normalize(t)
                if t not in offsets:offsets[t]=len(payload);payload.extend(t.encode('utf8')+b'\0')
                struct.pack_into('>I',body,start+k*20+16,offsets[t])
            result=bytes(body+payload)
            assert parse_bmd(result)[3]==[normalize(t) if t is not None else None for t in texts]
            assert source[:start]==result[:start]
            assert all(source[start+k*20:start+k*20+16]==result[start+k*20:start+k*20+16] for k in range(counts[2]))
        else:raise ValueError(name)
        path.write_bytes(result);assert strings(path)==after
        report.append(dict(file=name,source_sha256=sha256(source),output_sha256=sha256(result),replaced=[dict(before=a,after=b) for a,b in zip(before,after) if a!=b]))
    (OUT/'glyph_fallback_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(report),changed_strings=sum(len(r['replaced']) for r in report))))

if __name__=='__main__':build()
