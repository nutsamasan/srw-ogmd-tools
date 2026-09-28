"""Regenerate the bundled defaults and fingerprint from pristine BLJS10335 data."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from weapon_editor.fixed_data import parse_fixed
from weapon_editor.weapon_data import structure, profile


def main():
    root = Path(__file__).resolve().parent.parent
    raw = (root/'work/extracted/ps3_logic/Dat/FixedData/WeaponData.dat').read_bytes()
    fixed = parse_fixed(raw)
    english = parse_fixed((root/'work/poc/full_english_20260906/fixed/WeaponData.dat').read_bytes())
    units = parse_fixed((root/'work/poc/full_english_20260906/fixed/UnitData.dat').read_bytes())
    assert structure(fixed) == structure(english)
    items = {}
    for i, row in enumerate(fixed.records):
        unit, slot = int.from_bytes(row[:2], 'big'), row[2]
        if unit == slot == 0:
            continue
        owner = 'Equippable weapon'
        if unit:
            unit_row = units.records[units.logical_indices[unit]]
            owner = units.strings[int.from_bytes(unit_row[2:4], 'big')]
        name = english.strings[int.from_bytes(english.records[i][4:6], 'big')]
        items[i] = dict(unit=unit, slot=slot, name=name, owner=owner, defaults=asdict(profile(row)))
    doc = dict(version=1, title_id='BLJS10335', structure=structure(fixed),
               source_sha256=hashlib.sha256(raw).hexdigest(), weapons=items)
    target = Path(__file__).parent/'weapon_editor/catalog.json'
    target.write_text(json.dumps(doc, indent=2, ensure_ascii=False)+'\n', encoding='utf8')
    print(f'Built {len(items)} weapon definitions.')


if __name__ == '__main__':
    main()
