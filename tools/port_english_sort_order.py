"""Apply official English name-sort ranks to the proven native rank fields."""
import json,struct
from pathlib import Path
from ogmd_text_formats import parse_fixed
from port_mltd_stage import parse_mltd,sha256
from inspect_native_ui import disassemble
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'work/poc/full_english_20260906'

def build():
    reports=[]
    for name,table,getter,load in [('UnitData','SortMachineName',0x14828c,0x142cd0),('PilotData','SortPilotNickName',0x149ffc,0x1426d0)]:
        path=OUT/'fixed'/(name+'.dat');source=path.read_bytes();data=parse_fixed(source)
        entries=parse_mltd((ROOT/f'work/extracted/ps4_lang/Dat/MultiLanguage/@En/FixedData/{table}.mltd').read_bytes())[0]
        assert len(entries)==len(data.logical_indices)
        rp,_=data.chunks[b'DATA'];stride=len(data.records[0]);out=bytearray(source);seen={};rows=[]
        for logical,physical in enumerate(data.logical_indices):
            if physical==0xffffffff:continue
            rank=int(entries[logical].text);assert 0<=rank<=65535
            assert seen.setdefault(physical,rank)==rank
            offset=rp+12+physical*stride+6;before=struct.unpack_from('>H',source,offset)[0]
            struct.pack_into('>H',out,offset,rank)
            rows.append(dict(logical=logical,physical=physical,previous_rank=before,english_rank=rank))
        actual=parse_fixed(out);assert actual.strings==data.strings and actual.logical_indices==data.logical_indices
        assert all(a==b or j in (6,7) for old,new in zip(data.records,actual.records) for j,(a,b) in enumerate(zip(old,new)))
        for physical,rank in seen.items():assert int.from_bytes(actual.records[physical][6:8],'big')==rank
        path.write_bytes(out)
        reports.append(dict(file=name,table=table,source_sha256=sha256(source),output_sha256=sha256(out),physical_records=len(seen),rows=rows,native_evidence=disassemble(load,load+0x20)+'\n'+disassemble(getter-0x38,getter+0x40)))
    (OUT/'english_sort_order_report.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    print(json.dumps(dict(tables=2,physical_records=sum(r['physical_records'] for r in reports))))

if __name__=='__main__':build()
