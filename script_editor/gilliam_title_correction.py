"""Correct scenario 21's shared native title without changing its layout."""
import hashlib
import struct
from stage_title_correction import ENTRY, STRUCTURE

BEFORE = "GUILLIAM'S UNDERTAKING"
AFTER = "GILLIAM'S UNDERTAKING"


def correct_title_label(text):
    return text.replace(BEFORE, AFTER)


def validate_release_fix(release):
    correction = release.get('gilliam_stage_title_correction', {})
    expected = dict(entry=ENTRY, scenario=21, count=1, title=AFTER)
    if any(correction.get(key) != value for key, value in expected.items()):
        raise ValueError('Incomplete Gilliam stage-title correction.')
    checksum = correction.get('table_sha256', '')
    if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError('Missing corrected Gilliam stage-title table checksum.')
    return correction


def fix_gilliam_title(source, *, english_only=False):
    from fixed_data import parse_fixed
    fixed = parse_fixed(source)
    if english_only:
        if len(fixed.logical_indices) <= 21:
            return source, []
        physical = fixed.logical_indices[21]
        if physical == 0xffffffff or physical >= len(fixed.records) or len(fixed.records[physical]) != 20:
            return source, []
        if not any(fixed.strings[fixed.records[physical][offset]] in (BEFORE, AFTER) for offset in (3, 5)):
            return source, []
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
    physical = fixed.logical_indices[21]
    indices = {fixed.records[physical][offset] for offset in (3, 5)}
    if len(indices) != 1:
        raise ValueError('Expected scenario 21 to share one native title string.')
    sp, ss = fixed.chunks[b'SOFS']
    tp, _ = fixed.chunks[b'STRI']
    offsets = struct.unpack_from(f'>{ss // 4}I', source, sp + 8)
    out = bytearray(source)
    review = []
    for index in indices:
        before = fixed.strings[index]
        if before == AFTER:
            continue
        if before != BEFORE or fixed.string_headers[index] != struct.pack('>HHH', 1, len(BEFORE), 0):
            raise ValueError('Expected the English scenario 21 title.')
        start = tp + 12 + offsets[index]
        struct.pack_into('>H', out, start + 2, len(AFTER))
        text_start = start + 6
        out[text_start:text_start + len(BEFORE) + 1] = AFTER.encode('ascii') + b'\0\0'
        review.append(dict(scenario=21, physical=physical, string_index=index, before=before, after=AFTER))
    result = bytes(out)
    actual = parse_fixed(result)
    assert len(result) == len(source)
    assert actual.records == fixed.records and actual.logical_indices == fixed.logical_indices
    assert actual.strings == [AFTER if i in indices else text for i, text in enumerate(fixed.strings)]
    return result, review
