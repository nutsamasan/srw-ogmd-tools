"""Regression checks for the menu's native sub-string-zero reads."""
import copy
import struct
import unittest

from fixed_data import parse_fixed
from pilot_development import DESCRIPTIONS, fix_descriptions, validate_release_fix


def fixture():
    records = [struct.pack('>HH', i, i) for i in range(222)]
    payload = bytearray()
    offsets = []
    for i in range(222):
        offsets.append(len(payload))
        first = "Pilot's stat description." if i in DESCRIPTIONS else f'Unrelated text {i}'
        second = 'The complete second line.'
        a, b = first.encode(), second.encode()
        payload.extend(struct.pack('>HHHHH', 2, len(first), 0, len(second), len(a)+1))
        payload.extend(a+b'\0'+b+b'\0')
    payload.extend(bytes((-len(payload)) % 4))
    return (struct.pack('>4sI', b'FIXH', 0)
            + struct.pack('>4sI222I', b'DOFS', 222*4, *range(222))
            + struct.pack('>4sII', b'DATA', 222*4, 222)+b''.join(records)
            + struct.pack('>4sI222I', b'SOFS', 222*4, *offsets)
            + struct.pack('>4sII', b'STRI', len(payload), 222)+payload)


class PilotDevelopmentTests(unittest.TestCase):
    def test_caller_reads_both_lines_and_other_native_records_stay_identical(self):
        source = fixture()
        before = parse_fixed(source)
        result, review = fix_descriptions(source)
        after = parse_fixed(result)
        self.assertEqual(before.records, after.records)
        self.assertEqual(before.logical_indices, after.logical_indices)
        self.assertEqual(len(review), 10)
        sp, size = after.chunks[b'SOFS']; tp, _ = after.chunks[b'STRI']
        for i in range(222):
            if i not in DESCRIPTIONS:
                self.assertEqual(before.strings[i], after.strings[i])
                self.assertEqual(before.string_headers[i], after.string_headers[i])
                continue
            at = tp+12+struct.unpack_from('>I', result, sp+8+i*4)[0]
            count, chars, offset = struct.unpack_from('>HHH', result, at)
            complete = result[at+6+offset:result.index(0, at+6+offset)].decode('utf8')
            self.assertEqual(count, 1)
            self.assertEqual(chars, len(complete))
            self.assertEqual(complete, DESCRIPTIONS[i])
            self.assertEqual(complete.count('\n'), 1)
        self.assertEqual(fix_descriptions(result)[0], result)

    def test_unexpected_target_text_is_rejected_without_modifying_source(self):
        source = fixture().replace(b"Pilot's stat", b"Other's stat")
        snapshot = bytes(source)
        with self.assertRaises(ValueError): fix_descriptions(source)
        self.assertEqual(source, snapshot)

    def test_release_requires_complete_correction_and_measured_width(self):
        release = dict(pilot_development_descriptions=dict(
            entry='/Dat/FixedData/ProgStrData.dat', count=10,
            logical_records=list(range(212,222)), native_substrings=1,
            display_lines=2, width_limit=768, font_cell_size=24,
            user_confirmed_in_game=True, maximum_line_width=690,
            table_sha256='a'*64))
        self.assertEqual(validate_release_fix(release)['count'], 10)
        for key, value in [('count',9),('native_substrings',2),
                           ('maximum_line_width',769),('table_sha256','bad')]:
            broken = copy.deepcopy(release)
            broken['pilot_development_descriptions'][key] = value
            with self.assertRaises(ValueError): validate_release_fix(broken)


if __name__ == '__main__': unittest.main()
