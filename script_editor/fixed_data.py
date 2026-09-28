"""Native fixed-data text fields; game records and shared text users stay separate."""
import hashlib
import struct

# Only these proven text pointers may be edited. Sort ranks are kept as installed.
SCHEMAS = {
    'PilotData': (336, {'short_name': (2, 2), 'family_name': (12, 2), 'given_name': (14, 2)}),
    'UnitData': (216, {'name': (2, 2)}),
    'KeyWordData': (12, {'term': (2, 2), 'definition_1': (8, 2), 'definition_2': (10, 2)}),
    'SpiritData': (12, {'name': (1, 1), 'description': (10, 1)}),
    'WeaponData': (84, {'name': (4, 2)}),
}

# BLJS10335 UnitData: legacy corpus fingerprint -> fingerprint with only the
# five built-in skill IDs masked. Derived from pristine UnitData.dat SHA-256
# e8f7833b9d85d32a55597a0db6268807b4535452b7590611b886885cf0720d93.
# Keep legacy corpus hashes unchanged so existing projects/bundles still load.
UNIT_SKILL_STRUCTURES = {
    '42ea5f55ad8a51903c8f406ea3e10e0650296674348c03f2de6fbc00d194bb3d':
    '53f52847f4f52c9f497d4749467c46b6e2d19387be40389a8e41127bea7a0f77',
}

# BLJS10335 PilotData, from pristine SHA-256
# 1710c1ffecb67f84a5f91e2a3df9503f87fac314750bb8c3d87625d20bf5bf02.
# Only the Pilot Editor's Will profile and six command settings are masked.
# The dummy record, reserved slot bytes, stats and skills remain guarded.
PILOT_SETTING_STRUCTURES = {
    'bd780025e1169b362c1cb3e2362b1c3fe365d7a0487683e5cbbac244e41215a2':
    '473997ce00bcc007a30e8cec5f2763f9e0992d99e780e9f3e698cf94ac192b8c',
}
PILOT_SPIRIT_OFFSETS = tuple(0x72 + slot * 6 for slot in range(6))
PILOT_SETTING_OFFSETS = frozenset({0x13} | {
    start + offset for start in PILOT_SPIRIT_OFFSETS for offset in (0, 2, 3, 4, 5)
})

# BLJS10335 WeaponData, from pristine SHA-256
# 6c6d4e84490321990e18e0aa36d9408e8f6962a8606659f53c45d0d3e02a0ce3.
# The Save Editor's weapon tool edits attack (u16), min/max range, ammo and EN.
# Preserve the dummy record and guard owners, slots and all other properties.
WEAPON_SETTING_STRUCTURES = {
    '5d30e9a37fc1fdcd4c3ee2ac0934d281b267505d679c22724332bb360f39a3b9':
    '6b4f51ee3d4945d89332aae838a4cef6ce2f395b1856551b08c8d3ba36a971ec',
}
WEAPON_SETTING_OFFSETS = frozenset((12, 13, 14, 15, 20, 21))


def structure_hash(fixed, table, *, mask_unit_skills=False, mask_pilot_settings=False,
                   mask_weapon_settings=False):
    stride, fields = SCHEMAS[table]
    records = []
    for record, raw in enumerate(fixed.records):
        if len(raw) != stride: raise ValueError('Unexpected '+table+' record size.')
        row = bytearray(raw)
        for offset, width in fields.values(): row[offset:offset+width] = bytes(width)
        if table == 'PilotData': row[306:308] = b'\0\0'  # Voice-actor text pointer, not exposed here.
        if table in ('PilotData', 'UnitData'): row[6:8] = b'\0\0'
        if table == 'UnitData' and mask_unit_skills: row[0x46:0x4B] = bytes(5)
        if table == 'PilotData' and mask_pilot_settings and record != 0:
            for offset in PILOT_SETTING_OFFSETS: row[offset] = 0
        if table == 'WeaponData' and mask_weapon_settings and record != 0:
            for offset in WEAPON_SETTING_OFFSETS: row[offset] = 0
        records.append(row)
    return hashlib.sha256(struct.pack('>'+str(len(fixed.logical_indices))+'I', *fixed.logical_indices)+b''.join(records)).hexdigest()


def supported_pilot_settings(fixed):
    for raw in fixed.records[1:]:
        if raw[0x13] >= 12:
            return False
        for offset in PILOT_SPIRIT_OFFSETS:
            command = raw[offset]
            cost = int.from_bytes(raw[offset+2:offset+4], 'big')
            level, condition = raw[offset+4:offset+6]
            if command == 0:
                if (cost, level, condition) != (65535, 255, 255):
                    return False
            elif not (2 <= command <= 43 and cost <= 999 and 1 <= level <= 99
                      and condition in (0, 255)):
                return False
    return True


def structure_matches(fixed, table, expected):
    if structure_hash(fixed, table) == expected:
        return True
    if table == 'PilotData' and expected in PILOT_SETTING_STRUCTURES:
        return (supported_pilot_settings(fixed)
                and structure_hash(fixed, table, mask_pilot_settings=True) == PILOT_SETTING_STRUCTURES[expected])
    if table == 'WeaponData' and expected in WEAPON_SETTING_STRUCTURES:
        # Attack, ammo and EN accept their full unsigned storage ranges.
        # Range must satisfy the weapon tool's minimum/maximum relationship.
        return (all(1 <= raw[14] <= raw[15] for raw in fixed.records[1:])
                and structure_hash(fixed, table, mask_weapon_settings=True) == WEAPON_SETTING_STRUCTURES[expected])
    # Accept the separate mech-skill patcher's supported IDs only. The mapping,
    # record count, stats and every other non-text byte must still match stock.
    return (table == 'UnitData' and expected in UNIT_SKILL_STRUCTURES
            and all(sid < 48 for raw in fixed.records for sid in raw[0x46:0x4B])
            and structure_hash(fixed, table, mask_unit_skills=True) == UNIT_SKILL_STRUCTURES[expected])


def compile_fixed(source, items, language, metrics, normalize):
    from patcher import supported_text
    fixed = parse_fixed(source)
    assignments = {}; review = []
    for item in items:
        row = item['row']; table = row['fixed_table']; field = row['fixed_field']
        if table not in SCHEMAS or field not in SCHEMAS[table][1]: raise ValueError('Unknown fixed-data text field.')
        if not structure_matches(fixed, table, row['fixed_structure_sha256']): raise ValueError('Fixed game records differ: '+row['id'])
        record = row['fixed_record']; logical = row['fixed_logical']
        if not 0 <= logical < len(fixed.logical_indices) or fixed.logical_indices[logical] != record:
            raise ValueError('Fixed record mapping changed: '+row['id'])
        offset, width = SCHEMAS[table][1][field]
        before = fixed.strings[int.from_bytes(fixed.records[record][offset:offset+width], 'big')]
        for lang, text in item['edits'].items():
            if lang != language: raise ValueError('No speaker field in menu or glossary data.')
            if '\0' in text: raise ValueError('NUL is not allowed in game text.')
            native = supported_text(text, metrics, normalize).replace('\r\n','\n').replace('\r','\n')
            if field in ('short_name','given_name','family_name','name','term') and any(c in native for c in '\n@<>'):
                raise ValueError('Names and glossary terms must be one line without control markers: '+row['id'])
            identity = (record, offset, width)
            if identity in assignments and assignments[identity] != native: raise ValueError('Conflicting shared fixed field: '+row['id'])
            assignments[identity] = native
            review.append(dict(id=row['id'],field=lang,before=before,after=native,normalized=native!=text))
    replacements = {}
    if items and items[0]['row']['fixed_table']=='SpiritData':
        # Both text references in each Spirit record are one-byte indices.
        # Reuse a string only when every user of it has the same requested edit,
        # so repeated edits cannot exhaust the 256-slot pointer range.
        users = {}
        for record, raw in enumerate(fixed.records):
            for offset, width in SCHEMAS['SpiritData'][1].values():
                index = int.from_bytes(raw[offset:offset+width], 'big')
                users.setdefault(index, set()).add((record, offset, width))
        for index, identities in users.items():
            if identities <= assignments.keys():
                values = {assignments[identity] for identity in identities}
                if len(values)==1: replacements[index] = values.pop()
    result = rebuild_fixed(fixed, replacements, [(*key, value) for key,value in assignments.items()])
    return result, review


from dataclasses import dataclass
from native_formats import read_cstring, align

@dataclass
class FixedData:
    source: bytes
    chunks: dict
    logical_indices: list
    records: list
    strings: list
    string_headers: list


def parse_fixed(data):
    chunks = {}
    p = 0
    while p < len(data):
        tag, size = struct.unpack_from(">4sI", data, p)
        if tag not in {b"FIXH", b"DOFS", b"DATA", b"SOFS", b"STRI"} or tag in chunks:
            raise ValueError(f"Unsupported FIXH chunk at {p:x}: {tag!r}")
        extra = 4 if tag in {b"DATA", b"STRI"} else 0
        end = p + 8 + extra + size
        if end > len(data):
            raise ValueError("Fixed-data chunk past EOF")
        chunks[tag] = (p, size)
        p = end
    assert list(chunks) in ([b"FIXH", b"DOFS", b"DATA", b"SOFS", b"STRI"],
                            [b"FIXH", b"DATA", b"SOFS", b"STRI"])
    rp, rs = chunks[b"DATA"]
    record_count = struct.unpack_from(">I", data, rp + 8)[0]
    if b"DOFS" in chunks:
        dp, ds = chunks[b"DOFS"]
        logical = list(struct.unpack_from(f">{ds // 4}I", data, dp + 8))
    else:
        logical = list(range(record_count))
    assert record_count and rs % record_count == 0
    stride = rs // record_count
    records = [data[rp + 12 + k * stride:rp + 12 + (k + 1) * stride] for k in range(record_count)]
    assert all(i == 0xFFFFFFFF or i < record_count for i in logical)
    sp, ss = chunks[b"SOFS"]
    tp, ts = chunks[b"STRI"]
    offsets = struct.unpack_from(f">{ss // 4}I", data, sp + 8)
    assert len(offsets) == struct.unpack_from(">I", data, tp + 8)[0]
    strings, headers = [], []
    for relative in offsets:
        record = tp + 12 + relative
        lines = struct.unpack_from(">H", data, record)[0]
        text_base = record + 2 + lines * 4
        values = []
        for line in range(lines):
            chars, offset = struct.unpack_from(">HH", data, record + 2 + line * 4)
            text = read_cstring(data, text_base + offset)
            assert text_base + offset + len(text.encode("utf-8")) + 1 <= tp + 12 + ts
            assert chars == len(text), (chars, len(text))
            values.append(text)
        strings.append("\n".join(values))
        headers.append(data[record:text_base])
    return FixedData(data, chunks, logical, records, strings, headers)


def rebuild_fixed(fixed, replacements, field_variants=()):
    sp, ss = fixed.chunks[b"SOFS"]
    tp, ts = fixed.chunks[b"STRI"]
    texts = [replacements.get(i, text) for i, text in enumerate(fixed.strings)]
    records = [bytearray(r) for r in fixed.records]
    added = {}
    for record, offset, width, text in field_variants:
        fmt = {1: ">B", 2: ">H"}[width]
        old = struct.unpack_from(fmt, fixed.records[record], offset)[0]
        assert old < len(fixed.strings)
        if texts[old] == text:
            continue
        key = (old, text)
        if key not in added:
            added[key] = len(texts)
            texts.append(text)
        new = added[key]
        if new >= 2 ** (width * 8):
            raise ValueError(f"Fixed-data variant index {new} does not fit {width} bytes")
        struct.pack_into(fmt, records[record], offset, new)
    out = bytearray(fixed.source[:sp])
    rp, rs = fixed.chunks[b"DATA"]
    out[rp + 12:rp + 12 + rs] = b"".join(records)
    out.extend(struct.pack(">4sI", b"SOFS", len(texts) * 4) + bytes(len(texts) * 4))
    tp = len(out)
    out.extend(struct.pack(">4sII", b"STRI", 0, len(texts)))
    payload = bytearray()
    for index, text in enumerate(texts):
        struct.pack_into(">I", out, sp + 8 + index * 4, len(payload))
        lines = text.split("\n")
        header = bytearray(struct.pack(">H", len(lines)))
        encoded = bytearray()
        for line in lines:
            assert len(line) <= 65535 and len(encoded) <= 65535
            header.extend(struct.pack(">HH", len(line), len(encoded)))
            encoded.extend(line.encode("utf-8") + b"\0")
        payload.extend(header + encoded)
    size = max(ts, align(len(payload), 4))
    struct.pack_into(">I", out, tp + 4, size)
    out.extend(payload + bytes(size - len(payload)))
    result = bytes(out)
    verified = parse_fixed(result)
    assert verified.records == [bytes(r) for r in records] and verified.logical_indices == fixed.logical_indices
    assert verified.strings == texts
    allowed = {(record, i) for record, offset, width, text in field_variants for i in range(offset, offset + width)}
    assert all(a == b or (k, i) in allowed for k, (old, new) in enumerate(zip(fixed.records, verified.records))
               for i, (a, b) in enumerate(zip(old, new)))
    for record, offset, width, text in field_variants:
        index = int.from_bytes(verified.records[record][offset:offset + width], "big")
        assert verified.strings[index] == text
    return result
