"""Translate button guide fields by the verified native localization hash."""
from pathlib import Path
import json
from collections import defaultdict
from ogmd_text_formats import parse_fixed,rebuild_fixed
from port_mltd_stage import mltd_lookup,localization_hash,sha256

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/poc/full_english_20260906'


def build():
    source=(ROOT/'work/extracted/ps3_logic/Dat/FixedData/KeyGuideData.dat').read_bytes()
    fixed=parse_fixed(source)
    tables={kind:mltd_lookup((ROOT/f'work/extracted/ps4_lang/Dat/MultiLanguage/@En/FixedData/KeyGuide{kind}.mltd').read_bytes()) for kind in ['Name','Description']}
    rows=[];replacements={};assignments=[];used=defaultdict(set)
    for physical,record in enumerate(fixed.records):
        assert len(record)==100
        for slot in range(12):
            for kind,field in [('Name',6),('Description',7)]:
                offset=4+8*slot+field;index=record[offset];jp=fixed.strings[index]
                if not jp:continue
                key=localization_hash(jp);entry=tables[kind][key];en=entry.text
                used[kind].add(key);replacements.setdefault(index,en);assignments.append((physical,offset,1,en))
                rows.append(dict(physical=physical,slot=slot,field=kind,index=index,japanese=jp,english=en))
    assert all(used[k]==set(v) for k,v in tables.items())
    result=rebuild_fixed(fixed,replacements,assignments)
    (OUT/'fixed/KeyGuideData.dat').write_bytes(result)
    report=dict(source_sha256=sha256(source),output_sha256=sha256(result),source_size=len(source),output_size=len(result),
                used_names=len(used['Name']),used_descriptions=len(used['Description']),all_button_icons_and_controls_preserved=True,rows=rows)
    (OUT/'fixed_reports/KeyGuideData.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


if __name__=='__main__':build()
