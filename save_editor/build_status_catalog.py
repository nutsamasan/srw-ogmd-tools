"""Build stock BLJS10335 growth/terrain profiles from verified local game data."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'script_editor').is_dir())
sys.path.insert(0, str(ROOT / 'script_editor'))
from fixed_data import parse_fixed


def main():
    raw = (ROOT / 'work/extracted/ps3_logic/Dat/FixedData/PilotData.dat').read_bytes()
    elf = (ROOT / 'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
    assert hashlib.sha256(elf).hexdigest() == '75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0'
    fixed = parse_fixed(raw)
    growth = struct.unpack_from('>I', elf, 0xeddc88 - 0x5a28 - 0x10000)[0]
    profiles = {}
    for pid, physical in enumerate(fixed.logical_indices):
        if not pid or physical == 0xffffffff:
            continue
        row = fixed.records[physical]
        stats = []
        for index in range(6):
            curve_id = row[0x11b + index]
            assert curve_id <= 2
            start = growth - 0x10000 + (index + 1) * 297 + curve_id * 99
            curve = list(elf[start:start + 99])
            assert len(curve) == 99 and curve[-1] > 0
            stats.append(dict(base=row[0x15 + index], curve=curve,
                              correction=struct.unpack_from('>b', row, 0x122 + index)[0]))
        profiles[str(pid)] = dict(stats=stats, terrain=list(row[0x2b:0x2f]))
    out = dict(title_id='BLJS10335', pilot_data_sha256=hashlib.sha256(raw).hexdigest(),
               elf_sha256=hashlib.sha256(elf).hexdigest(), pilots=profiles)
    (Path(__file__).parent / 'pilot_status.json').write_text(json.dumps(out, separators=(',', ':')) + '\n')
    print(f'Built {len(profiles)} pilot status profiles.')


if __name__ == '__main__':
    main()
