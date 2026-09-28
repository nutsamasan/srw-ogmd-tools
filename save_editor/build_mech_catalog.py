"""Regenerate the standalone labels from the locally inspected native tables."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'script_editor'))
from fixed_data import parse_fixed


def main():
    source = ROOT/'work/poc/full_english_20260906/fixed'
    units = parse_fixed((source/'UnitData.dat').read_bytes())
    abilities = parse_fixed((source/'AbilityData.dat').read_bytes())
    edits_path = ROOT/'script_editor/edits/project.json'
    edits = json.loads(edits_path.read_text(encoding='utf8'))['collections']['06_Game_data/Mech_names']['rows']
    catalog = {'source':str(source.relative_to(ROOT)),
               'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'UnitData.dat',source/'AbilityData.dat')},
               'name_edits_source':str(edits_path.relative_to(ROOT)),
               'name_edits_sha256':hashlib.sha256(edits_path.read_bytes()).hexdigest(),
               'units':{},'builtins':{}}
    for logical,index in enumerate(units.logical_indices):
        if index==0xffffffff:
            continue
        record=units.records[index]
        name=units.strings[int.from_bytes(record[2:4],'big')]
        name=edits.get(f'UnitData_name:{logical:04d}',{}).get('en',name)
        catalog['units'][str(logical)]={'name':name,'builtins':list(record[0x46:0x4b])}
    for record in abilities.records:
        catalog['builtins'][str(record[0])]={'name':abilities.strings[record[1]],'description':abilities.strings[record[10]]}
    (ROOT/'save_editor/mechs.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f"Wrote {len(catalog['units'])} mech labels and {len(catalog['builtins'])} built-in ability labels.")


if __name__=='__main__':
    main()
