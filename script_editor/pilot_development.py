"""Repair Pilot Development descriptions without changing other native strings.

ProgStrData callers read sub-string zero. Display newlines must remain inside
that NUL-terminated string, as in the Japanese table, rather than becoming
separate STRI sub-strings.
"""
import struct


def validate_release_fix(release):
    correction = release.get('pilot_development_descriptions', {})
    expected = dict(entry='/Dat/FixedData/ProgStrData.dat', count=10,
                    logical_records=list(range(212, 222)), native_substrings=1,
                    display_lines=2, width_limit=768, font_cell_size=24,
                    user_confirmed_in_game=True)
    if any(correction.get(key) != value for key, value in expected.items()):
        raise ValueError('Incomplete Pilot Development description correction.')
    if not 0 < correction.get('maximum_line_width', 0) <= 768:
        raise ValueError('Pilot Development descriptions exceed their text box.')
    digest = correction.get('table_sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Missing corrected Pilot Development table checksum.')
    return correction

DESCRIPTIONS = {
    212: "Pilot's Melee ability. Raising it increases the damage\nof melee weapons.",
    213: "Pilot's Ranged ability. Raising it increases the damage\nof ranged weapons.",
    214: "Pilot's Skill. Raising it improves the Critical Rate\nand the activation rate of the special skill「Counter」.",
    215: "Pilot's Defense ability. Raising it reduces the damage\nreceived in battle.",
    216: "Pilot's Evade ability. Raising it improves the chance\nof successfully evading an attack.",
    217: "Pilot's Hit ability. Raising it improves the chance\nof successfully hitting the target.",
}
for logical, terrain in zip(range(218, 222), ('Air', 'Land', 'Sea', 'Space')):
    DESCRIPTIONS[logical] = (
        f"Pilot's {terrain} rating affects Hit, Evade and damage taken.\n"
        "Ranks: S, A, B, C, D. S provides the best compatibility.")


def fix_descriptions(source):
    # Import lazily so this helper also works in the original conversion tools.
    from fixed_data import parse_fixed
    fixed = parse_fixed(source)
    if any(len(r) != 4 for r in fixed.records):
        raise ValueError('Unexpected ProgStrData record size.')
    sp, ss = fixed.chunks[b'SOFS']
    tp, ts = fixed.chunks[b'STRI']
    offsets = list(struct.unpack_from(f'>{ss // 4}I', source, sp + 8))
    if offsets != sorted(set(offsets)) or offsets[0] != 0:
        raise ValueError('Unexpected native string ordering.')
    end_offsets = offsets[1:] + [ts]
    original = [source[tp+12+a:tp+12+b] for a, b in zip(offsets, end_offsets)]
    replacements = {}
    review = []
    for logical, text in DESCRIPTIONS.items():
        physical = fixed.logical_indices[logical]
        index = int.from_bytes(fixed.records[physical][2:4], 'big')
        before = fixed.strings[index]
        if not before.startswith("Pilot's "):
            raise ValueError(f'Expected the English Pilot Development text at {logical}.')
        if index in replacements:
            raise ValueError('Unexpected shared description index.')
        replacements[index] = struct.pack('>HHH', 1, len(text), 0) + text.encode('utf8') + b'\0'
        review.append(dict(logical=logical, physical=physical, string_index=index,
                           before=before, after=text,
                           before_substrings=struct.unpack_from('>H', original[index])[0],
                           after_substrings=1))
    payload = bytearray()
    new_offsets = []
    for index, raw in enumerate(original):
        new_offsets.append(len(payload))
        payload.extend(replacements.get(index, raw))
    payload.extend(bytes((-len(payload)) % 4))
    out = bytearray(source[:sp])
    out.extend(struct.pack('>4sI', b'SOFS', ss))
    out.extend(struct.pack(f'>{len(new_offsets)}I', *new_offsets))
    out.extend(struct.pack('>4sII', b'STRI', len(payload), len(offsets)))
    out.extend(payload)
    result = bytes(out)
    actual = parse_fixed(result)
    assert actual.records == fixed.records and actual.logical_indices == fixed.logical_indices
    assert result[:sp] == source[:sp]
    for index, text in enumerate(actual.strings):
        assert text == (next(r['after'] for r in review if r['string_index'] == index)
                        if index in replacements else fixed.strings[index])
        if index not in replacements:
            assert actual.string_headers[index] == fixed.string_headers[index]
    for row in review:
        index = row['string_index']
        # Model the caller's sub-string-zero read, not just the joined parser.
        start = sp + 8 + ss + 12 + new_offsets[index]
        count, chars, offset = struct.unpack_from('>HHH', result, start)
        native = result[start+6+offset:result.index(0, start+6+offset)].decode('utf8')
        assert count == 1 and chars == len(native) and native == row['after']
    return result, review
