"""Correct scenario 40's two native menu titles, preserving every other byte."""
import hashlib
import struct

ENTRY = '/Dat/FixedData/StageData.dat'
BEFORE = "HAGWANE'S CRISIS"
AFTER = "HAGANE'S CRISIS"
STRUCTURE = '305995f569cd1d56f68ce289a500362f2a1251fb0d9ac4c47fef67eb6b5ff8e8'


def validate_release_fix(release):
    correction = release.get('stage_title_corrections', {})
    expected = dict(entry=ENTRY, scenario=40, count=2, title=AFTER)
    if any(correction.get(key) != value for key, value in expected.items()):
        raise ValueError('Incomplete Hagane stage-title correction.')
    checksum = correction.get('table_sha256', '')
    if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError('Missing corrected stage-title table checksum.')
    return correction


def fix_english_stage_titles(source):
    """Leave untranslated Japanese tables alone in an English edits-only build."""
    from gilliam_title_correction import fix_gilliam_title
    source, gilliam_review = fix_gilliam_title(source, english_only=True)
    from fixed_data import parse_fixed
    fixed = parse_fixed(source)
    if len(fixed.logical_indices) <= 40:
        return source, gilliam_review
    physical = fixed.logical_indices[40]
    if physical == 0xffffffff or physical >= len(fixed.records):
        return source, gilliam_review
    if len(fixed.records[physical]) != 20:
        return source, gilliam_review
    indices = [fixed.records[physical][offset] for offset in (3, 5)]
    if not any(fixed.strings[index] in (BEFORE, AFTER) for index in indices):
        return source, gilliam_review
    result, review = fix_stage_titles(source)
    return result, gilliam_review + review


def fix_stage_titles(source):
    from fixed_data import parse_fixed
    fixed = parse_fixed(source)
    records = []
    for raw in fixed.records:
        if len(raw) != 20:
            raise ValueError('Unexpected StageData record size.')
        record = bytearray(raw)
        for offset in (3, 5, 6):
            record[offset] = 0
        records.append(record)
    signature = struct.pack(f'>{len(fixed.logical_indices)}I', *fixed.logical_indices) + b''.join(records)
    if hashlib.sha256(signature).hexdigest() != STRUCTURE:
        raise ValueError('Unsupported StageData structure or scenario mapping.')
    physical = fixed.logical_indices[40]
    indices = {fixed.records[physical][offset] for offset in (3, 5)}
    sp, ss = fixed.chunks[b'SOFS']
    tp, _ = fixed.chunks[b'STRI']
    offsets = struct.unpack_from(f'>{ss // 4}I', source, sp + 8)
    out = bytearray(source)
    review = []
    for index in sorted(indices):
        before = fixed.strings[index]
        if before == AFTER:
            continue
        if before != BEFORE or fixed.string_headers[index] != struct.pack('>HHH', 1, len(BEFORE), 0):
            raise ValueError('Expected the English scenario 40 title.')
        start = tp + 12 + offsets[index]
        # Shorter spelling fits the existing native string slot. Keep SOFS,
        # STRI size, all record pointers and all unrelated strings untouched.
        struct.pack_into('>H', out, start + 2, len(AFTER))
        text_start = start + 6
        out[text_start:text_start + len(BEFORE) + 1] = AFTER.encode('ascii') + b'\0\0'
        review.append(dict(scenario=40, physical=physical, string_index=index, before=before, after=AFTER))
    result = bytes(out)
    actual = parse_fixed(result)
    assert len(result) == len(source)
    assert actual.records == fixed.records and actual.logical_indices == fixed.logical_indices
    assert actual.strings == [AFTER if i in indices else text for i, text in enumerate(fixed.strings)]
    return result, review
