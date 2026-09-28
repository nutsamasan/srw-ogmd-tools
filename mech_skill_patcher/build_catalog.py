"""Build original skill defaults and layout guards from the pristine PS3 tables."""
import hashlib
import json
from pathlib import Path
import struct

from fixed_data import parse_fixed

ROOT = Path(__file__).resolve().parent.parent


def structure(fixed, kind):
    records = []
    for raw in fixed.records:
        row = bytearray(raw)
        if kind == 'unit':
            row[2:4] = bytes(2)  # Translated name pointer.
            row[6:8] = bytes(2)  # Translated sort order.
            row[0x46:0x4B] = bytes(5)
        else:
            row[1] = row[2] = row[10] = 0  # Name, category and description pointers.
        records.append(row)
    return hashlib.sha256(struct.pack('>'+str(len(fixed.logical_indices))+'I', *fixed.logical_indices)
                          + b''.join(records)).hexdigest()


def main():
    base = ROOT/'work/extracted/ps3_logic/Dat/FixedData'
    units = parse_fixed((base/'UnitData.dat').read_bytes())
    skills = parse_fixed((base/'AbilityData.dat').read_bytes())
    labels = json.loads((ROOT/'save_editor/mechs.json').read_text(encoding='utf8'))
    # Repair punctuation in the display catalog only; game text is never edited.
    def clean(text):
        for old, new in [('�i', '('), ('�j', ')'), ('�u', '"'), ('�v', '"'), ('�`', '-')]:
            text = text.replace(old, new)
        return ' '.join(text.split())
    result = dict(version=1, title_id='BLJS10335', unit_structure=structure(units, 'unit'),
                  ability_structure=structure(skills, 'ability'), units={}, skills={},
                  original_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (base/'UnitData.dat', base/'AbilityData.dat')})
    for uid, index in enumerate(units.logical_indices):
        if index != 0xFFFFFFFF:
            result['units'][str(uid)] = dict(name=labels['units'][str(uid)]['name'],
                                            defaults=list(units.records[index][0x46:0x4B]))
    result['skills']['0'] = dict(name='Empty', description='No built-in skill in this slot.')
    for sid in range(1, 48):
        result['skills'][str(sid)] = {k: clean(v) for k, v in labels['builtins'][str(sid)].items()}
    (Path(__file__).parent/'catalog.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(f"Catalog: {len(result['units'])-1} mechs/forms; 47 skills; pristine defaults.")


if __name__ == '__main__':
    main()
