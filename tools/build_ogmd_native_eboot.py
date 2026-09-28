"""Embed the confirmed v3 hooks in an isolated ELF; make an RPCS3 debug SELF.

The SELF wrapper is deliberately a test container, not a console-signed build.
No game, release package, or RPCS3 configuration is modified by this builder.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import build_ogmd_apostrophe_patch as patch
import build_ogmd_spacing_patch as base

ROOT = base.ROOT
OUT = ROOT / 'work/poc/native_eboot_20260910_v2'
SOURCE = ROOT / 'work/poc/text_layout_20260905/EBOOT.elf'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def program_headers(data):
    h = struct.unpack_from('>16sHHIQQQIHHHHHH', data)
    assert h[0][:7] == b'\x7fELF\x02\x02\x01' and h[1:4] == (2, 21, 1)
    assert h[9] == 56
    return h, [struct.unpack_from('>IIQQQQQQ', data, h[5] + n * h[9])
               for n in range(h[10])]


def file_offset(data, address, size=4):
    _, segments = program_headers(data)
    matches = [s[2] + address - s[3] for s in segments
               if s[0] == 1 and s[3] <= address and address + size <= s[3] + s[5]]
    assert len(matches) == 1, (hex(address), size, matches)
    return matches[0]


def branch(source, target):
    delta = target - source
    assert delta % 4 == 0 and -(1 << 25) <= delta < (1 << 25)
    return struct.pack('>I', 0x48000000 | (delta & 0x03fffffc))


def build():
    original = SOURCE.read_bytes()
    assert sha(original) == base.ELF_SHA256
    h, segments = program_headers(original)
    code_segment, data_segment = segments[:2]
    assert code_segment == (1, 0x400005, 0, 0x10000, 0x10000, 0xe58048, 0xe58048, 0x10000)
    old_end = code_segment[2] + code_segment[5]
    limit = data_segment[2]
    assert limit == 0xe60000 and not any(original[old_end:limit])
    # The selected bytes are outside every original file-backed section.
    for n in range(h[12]):
        section = struct.unpack_from('>IIQQQQIIQQ', original, h[6] + n * h[11])
        if section[1] != 8 and section[5]:
            assert not (max(old_end, section[4]) < min(limit, section[4] + section[5]))
    assert not (max(old_end, h[6]) < min(limit, h[6] + h[11] * h[12]))

    result = bytearray(original)
    cursor = (old_end + 15) & ~15
    start = cursor
    hooks = []
    changes = []
    for hook, code, _ in patch.compile_hooks():
        address = code_segment[3] + cursor - code_segment[2]
        hook_offset = file_offset(original, hook.address)
        assert original[hook_offset:hook_offset + 4].hex() == hook.expected
        payload = code + branch(address + len(code), hook.address + 4)
        assert cursor + len(payload) <= limit
        result[cursor:cursor + len(payload)] = payload
        result[hook_offset:hook_offset + 4] = branch(hook.address, address)
        changes.extend([(cursor, len(payload)), (hook_offset, 4)])
        hooks.append(dict(hook_address=hook.address, hook_file_offset=hook_offset,
                          code_address=address, code_file_offset=cursor,
                          code_size=len(code), return_address=hook.address + 4,
                          original_instruction=hook.expected, kind=hook.kind,
                          code_sha256=sha(code), payload_sha256=sha(payload)))
        cursor = (cursor + len(payload) + 15) & ~15
    new_size = cursor - code_segment[2]
    assert code_segment[3] + new_size <= data_segment[3]
    # Extend only PT_LOAD[0]'s file/memory sizes. All offsets remain stable.
    struct.pack_into('>QQ', result, h[5] + 32, new_size, new_size)
    changes.append((h[5] + 32, 16))
    # RPCS3's analyser uses executable SHT_PROGBITS sections to bound code.
    # Add a named section for the payload. Append metadata only; leave all
    # original loaded code/data and their file offsets in place.
    sections = [list(struct.unpack_from('>IIQQQQIIQQ', original, h[6] + n * h[11]))
                for n in range(h[12])]
    strings = sections[h[13]]
    names = original[strings[4]:strings[4] + strings[5]]
    new_name = len(names)
    names += b'.ogmd_vwf\0'
    strings[4], strings[5] = len(result), len(names)
    result.extend(names)
    result.extend(bytes((-len(result)) % 8))
    new_table_offset = len(result)
    sections.append([new_name, 1, 6, code_segment[3] + start, start,
                     cursor - start, 0, 0, 16, 0])
    for section in sections:
        result.extend(struct.pack('>IIQQQQIIQQ', *section))
    struct.pack_into('>Q', result, 0x28, new_table_offset)
    struct.pack_into('>H', result, 0x3c, len(sections))
    changes.extend([(0x28, 8), (0x3c, 2), (len(original), len(result) - len(original))])
    allowed = bytearray(len(result))
    for offset, size in changes:
        allowed[offset:offset + size] = b'\x01' * size
    assert all(a == b or allowed[i] for i, (a, b) in enumerate(zip(original, result)))

    # Matches RPCS3 Crypto/unself.cpp CheckDebugSelf: 0x8000, BE ELF offset.
    # This container is not a substitute for hardware signing/authentication.
    wrapper = bytearray(0x1000)
    struct.pack_into('>IIHHIQQ', wrapper, 0, 0x53434500, 2, 0x8000, 1, 0, len(wrapper), len(result))
    self_data = bytes(wrapper) + result
    report = dict(status='built; verification pending', source=str(SOURCE),
                  source_elf_sha256=sha(original), patched_elf_sha256=sha(result),
                  test_eboot_sha256=sha(self_data), elf_size=len(result),
                  wrapper='RPCS3 debug SELF; not console signed', wrapper_size=len(wrapper),
                  original_code_segment_size=code_segment[5], new_code_segment_size=new_size,
                  gap_start_file_offset=old_end, payload_start_file_offset=start,
                  payload_end_file_offset=cursor, next_segment_file_offset=limit,
                  original_gap_zero_bytes=limit-old_end, payload_code_bytes=sum(x['code_size'] for x in hooks),
                  added_metadata_bytes=len(result)-len(original), section_table_offset=new_table_offset,
                  added_section='.ogmd_vwf',
                  hooks=hooks, allowed_changes=changes,
                  yaml_sha256=sha((patch.OUT / patch.PATCH_FILE).read_bytes()),
                  runtime_status='Fresh user boot pending; physical PS3 not validated')
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [('EBOOT.elf', bytes(result)), ('EBOOT.BIN', self_data),
                       ('build_report.json', (json.dumps(report, indent=2) + '\n').encode())]:
        path = OUT / name
        if path.exists():
            assert path.read_bytes() == data, f'Refusing to overwrite different output: {path}'
        else:
            path.write_bytes(data)
    assert sha(SOURCE.read_bytes()) == base.ELF_SHA256
    print(json.dumps({k: v for k, v in report.items() if k not in {'hooks', 'allowed_changes'}}, indent=2))


if __name__ == '__main__':
    build()
