"""Build supported-game fingerprints and original pilot settings from local sources."""
import hashlib
import json
from pathlib import Path
import struct
from fixed_data import parse_fixed

ROOT = Path(__file__).resolve().parent.parent
SPIRIT_OFFSETS = tuple(0x72 + i * 6 for i in range(6))
EDIT_OFFSETS = {0x13} | {base + off for base in SPIRIT_OFFSETS for off in (0, 2, 3, 4, 5)}


def structure(fixed, kind):
    rows = []
    for source in fixed.records:
        row = bytearray(source)
        if kind == 'pilot':
            for start, length in ((2, 2), (6, 2), (12, 4), (306, 2)):
                row[start:start+length] = bytes(length)
            for off in EDIT_OFFSETS:
                row[off] = 0
        else:
            row[1] = row[10] = 0
        rows.append(row)
    return hashlib.sha256(struct.pack('>'+str(len(fixed.logical_indices))+'I', *fixed.logical_indices)
                          + b''.join(rows)).hexdigest()


def profile(row):
    return dict(personality=row[0x13], spirits=[dict(command=row[o], cost=int.from_bytes(row[o+2:o+4], 'big'),
                level=int.from_bytes(row[o+4:o+5], 'big', signed=True),
                flag=int.from_bytes(row[o+5:o+6], 'big', signed=True)) for o in SPIRIT_OFFSETS])


def main():
    base = ROOT/'work/extracted/ps3_logic/Dat/FixedData'
    pilot_raw = (base/'PilotData.dat').read_bytes()
    spirit_raw = (base/'SpiritData.dat').read_bytes()
    pilots, spirits = parse_fixed(pilot_raw), parse_fixed(spirit_raw)
    english = parse_fixed((ROOT/'work/poc/full_english_20260906/fixed/SpiritData.dat').read_bytes())
    names = json.loads((Path(__file__).parent/'names.json').read_text(encoding='utf8'))
    print('Name catalog keys:', list(names))
    # Use the current editor's reconciled names, including manual terminology corrections.
    labels = {int(k): v for k, v in names['pilots'].items()}
    data = dict(version=1, title_id='BLJS10335', pilot_structure=structure(pilots, 'pilot'),
                spirit_structure=structure(spirits, 'spirit'), pilots={}, spirits={}, personalities={},
                original_files={'PilotData.dat': hashlib.sha256(pilot_raw).hexdigest(),
                                'SpiritData.dat': hashlib.sha256(spirit_raw).hexdigest()})
    for pid, physical in enumerate(pilots.logical_indices):
        if pid == 0 or physical == 0xffffffff:
            continue
        row = pilots.records[physical]
        data['pilots'][pid] = dict(name=labels.get(pid) or 'Unnamed pilot', defaults=profile(row))
    data['spirits'][0] = dict(name='Empty', description='No command in this slot.')
    for sid, physical in enumerate(english.logical_indices):
        if sid < 2 or physical == 0xffffffff:
            continue
        row = english.records[physical]
        data['spirits'][sid] = dict(name=english.strings[row[1]], description=english.strings[row[10]])
    # Choose examples by verified membership instead of trusting donor ID guesses.
    preferred = {0: ['Eita','Azuki'], 1: ['Kyosuke','Ryusei'], 2: ['Kusuha','Akimi'],
        3: ['Rai','Latooni'], 4: ['Russel','Ibis'], 5: ['Excellen','Arado'], 6: ['Lefina','Mizuho'],
        7: ['Katina'], 8: ['Helluga','Gu-Landon'], 9: ['Rishu','Shu'],
        10: ['Kinaha','Crystal Dragoon'], 11: ['Kalo-Ran','So-Des']}
    elf = (ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
    for kind in sorted({p['defaults']['personality'] for p in data['pilots'].values()}):
        examples = [p['name'] for p in data['pilots'].values() if p['defaults']['personality'] == kind]
        selected = [n for n in preferred[kind] if n in examples] or examples[:2]
        data['personalities'][kind] = dict(name=' / '.join(selected),
            examples=selected, native_response_values=list(struct.unpack_from('>6i', elf, 0xdc3ef0-0x10000+0x5c4+24*kind)))
    (Path(__file__).parent/'catalog.json').write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf8')
    print('Catalog:', len(data['pilots']), 'pilots;', len(data['spirits'])-1, 'commands;', len(data['personalities']), 'Will profiles')


if __name__ == '__main__':
    main()
