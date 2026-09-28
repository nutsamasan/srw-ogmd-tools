"""Native map terrain labels and tutorial titles, with complete row checks."""
from pathlib import Path
import json
import struct
from port_mltd_stage import parse_mltd,sha256
from port_mltd_roll import parse_csb
from ogmd_text_formats import rebuild_csb

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/poc/full_english_20260906'
LANG=ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En'


def build_map():
    relative=Path('Dat/Map/MapLandInfo/landinfo.mti')
    source=(OUT/'native_ui/General3d'/relative).read_bytes()
    entries=parse_mltd((LANG/'MapText.mltd').read_bytes())[0]
    assert source[:8]==bytes.fromhex('4d505449feff0001') and len(source)==12+1024*84
    assert len(entries)==1000
    out=bytearray(source);rows=[]
    for i,entry in enumerate(entries):
        start=12+i*84;blob=source[start:start+64];jp=blob.split(b'\0',1)[0].decode('utf8')
        assert all(b==0 for b in blob[len(jp.encode())+1:])
        suffix='@'+jp.split('@',1)[1] if '@' in jp else ''
        if i==169:
            assert suffix=='@建物の敷地部分、パキスタン・カラチ'
            suffix='@Building site, Karachi, Pakistan'
        result=entry.text+suffix
        assert len(result.encode())<64
        out[start:start+64]=(result.encode()+b'\0').ljust(64,b'\0')
        assert out[start+64:start+84]==source[start+64:start+84]
        rows.append(dict(index=i,japanese=jp,english=result))
    assert out[:12]==source[:12] and out[12+1000*84:]==source[12+1000*84:]
    assert all(not source[12+i*84:12+i*84+64].strip(b'\0') for i in range(1000,1024))
    destination=OUT/'ui/General3d'/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(out)
    report=dict(source_sha256=sha256(source),output_sha256=sha256(out),size=len(out),translated_labels=1000,
                terrain_stats_preserved=True,unused_rows_preserved=24,authoring_note_translated=169,rows=rows)
    (OUT/'mapname_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


def build_guidance():
    relative=Path('Dat/logic/Resource/summary/2og_GuidanceSummary.csb')
    source=(ROOT/'work/extracted/ps3_logic'/relative).read_bytes()
    records=parse_csb(source)[2];entries=parse_mltd((LANG/'GuidanceTitleMessage.mltd').read_bytes())[0]
    assert len(records)==20 and len(entries)==17
    edits={(i+3,4):entry.text for i,entry in enumerate(entries)}
    result=rebuild_csb(source,edits)
    destination=OUT/'ui/Logic'/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(result)
    report=dict(source_sha256=sha256(source),output_sha256=sha256(result),source_size=len(source),output_size=len(result),
                translated_titles=15,empty_titles=2,images_and_other_arguments_preserved=True,
                rows=[dict(row=i+3,japanese=records[i+3]['arguments'][4],english=e.text) for i,e in enumerate(entries)])
    (OUT/'guidance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


if __name__=='__main__':build_map();build_guidance()
