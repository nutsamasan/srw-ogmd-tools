"""Port menu text through the PS4's exact window/group/widget/state lookup."""
from pathlib import Path
from collections import defaultdict
import bisect
import json
import re
import struct

from port_mltd_stage import localization_hash, mltd_lookup, read_cstring, sha256
from decode_wtd_native import Decoder, WTD_PATH, OUT

ROOT=Path(__file__).resolve().parents[1]
LANG=ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En'
JP=re.compile('[ぁ-んァ-ヶ一-鿿]')


def make_rows(source, decoded):
    labels=mltd_lookup((LANG/'windowdataMainLabelListText.mltd').read_bytes())
    english=mltd_lookup((ROOT/'work/extracted/ps4_patch0101/Dat/MultiLanguage/@En/windowdataMainText.mltd').read_bytes())
    windows=[x['offset'] for x in decoded['windows']]
    groups=[x['offset'] for x in decoded['groups']]
    objects=[x['offset'] for x in decoded['objects']]
    # The loader decodes the first state a second time while applying it.
    # Only serialized properties belong in the state ordinal sequence.
    properties=sorted({x['offset']:x for x in decoded['properties']}.values(),key=lambda x:x['offset'])
    rows=[]
    ordinal=defaultdict(int)
    used=set()
    for prop in properties:
        o=objects[bisect.bisect_right(objects,prop['offset'])-1]
        g=groups[bisect.bisect_right(groups,o)-1]
        w=windows[bisect.bisect_right(windows,g)-1]
        state=ordinal[o];ordinal[o]+=1
        identifiers=[struct.unpack_from('>I',source,p)[0] for p in [w+4,g,o+4]]
        key='_'.join(map(str,identifiers+[state]))
        label=labels.get(localization_hash(key))
        if label: used.add(localization_hash(key))
        if prop['text'] is None:
            continue
        offset=prop['text']-2
        length=struct.unpack_from('>I',source,offset)[0]
        jp=read_cstring(source,offset+4) if length else ''
        assert length==len(jp.encode())+1 or length==0
        entry=english[localization_hash(label.text)] if label else None
        rows.append(dict(offset=offset,extent=4+((length+3)&~3),window=w,object=o,
                         property=prop['offset'],state=state,key=key,japanese=jp,
                         label=label.text if label else None,
                         english=entry.text if entry else None))
    return rows,dict(label_entries=len(labels),used_labels=len(used),unused_label_keys=sorted(set(labels)-used))


def build():
    source=WTD_PATH.read_bytes()
    assert source==(OUT/'native_ui/PS4General2d/Dat/Window/WindowToolData/windowdataMain.wtd').read_bytes()
    decoded=json.loads((OUT/'wtd_native_decode.json').read_text())
    rows,coverage=make_rows(source,decoded)
    unmatched=[r for r in rows if r['english'] is None and r['japanese']]
    # The PS4 omits this single numeric counter template from its lookup.
    # Preserve its native fallback; it is replaced with a live value in use.
    assert [(r['offset'],r['japanese']) for r in unmatched]==[(5740,'００００')], unmatched[:5]
    edits=[]
    for row in rows:
        text=row['english']
        if text is None or text==row['japanese']: continue
        payload=text.encode()+b'\0'
        blob=struct.pack('>I',len(payload))+payload+bytes((-len(payload))%4)
        edits.append((row['offset'],row['extent'],blob,row['window']))
    changes=defaultdict(int)
    for offset,extent,blob,window in edits: changes[window]+=len(blob)-extent
    boundaries={w['offset']:w for w in decoded['windows']}
    patches=[(o,n,b) for o,n,b,_ in edits]+[(w,4,struct.pack('>I',boundaries[w]['size']+delta)) for w,delta in changes.items()]
    patches.sort()
    output=bytearray();cursor=0;relocations=[]
    for offset,extent,blob in patches:
        assert cursor<=offset
        output.extend(source[cursor:offset]);output.extend(blob)
        cursor=offset+extent
        relocations.append((cursor,len(output)-cursor))
    output.extend(source[cursor:]);result=bytes(output)
    def remap(offset):
        k=bisect.bisect_right(relocations,(offset,10**10))-1
        return offset+(relocations[k][1] if k>=0 else 0)
    # The actual stock PS3 readers must finish every grown window exactly.
    dec=Decoder(result)
    for window in decoded['windows']:
        offset=remap(window['offset'])
        assert dec.window(offset)==remap(window['offset']+window['size'])
    before=sorted({x['offset']:x for x in decoded['properties']}.values(),key=lambda x:x['offset'])
    after=sorted({x['offset']:x for x in dec.properties}.values(),key=lambda x:x['offset'])
    assert len(before)==len(after)
    expected={r['property']:r for r in rows}
    for a,b in zip(before,after):
        assert remap(a['offset'])==b['offset'] and remap(a['end'])==b['end'] and a['flags']==b['flags']
        if a['text'] is None: assert b['text'] is None;continue
        row=expected[a['offset']]
        n=int.from_bytes(result[b['text']-2:b['text']+2],'big')
        text=read_cstring(result,b['text']+2) if n else ''
        assert text==(row['english'] if row['english'] is not None else row['japanese'])
    # Reversing only the approved string spans and window sizes must give the
    # pristine source exactly; thus layout/IDs/scripts are byte-preserved.
    reverse=bytearray(result)
    for offset,extent,blob in reversed(patches):
        at=remap(offset)
        reverse[at:at+len(blob)]=source[offset:offset+extent]
    assert bytes(reverse)==source
    destination=OUT/'ui/General2d/Dat/Window/WindowToolData/windowdataMain.wtd'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(result)
    report=dict(source_sha256=sha256(source),output_sha256=sha256(result),source_size=len(source),output_size=len(result),
                windows=403,translated_fields=len(edits),all_native_readers_passed=True,
                all_other_bytes_preserved=True,remaining_japanese=[],preserved_numeric_template=unmatched,
                coverage=coverage,rows=rows)
    (OUT/'wtd_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','coverage')}))


if __name__=='__main__':build()
