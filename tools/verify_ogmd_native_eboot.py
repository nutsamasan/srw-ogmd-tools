"""Execute the branches and payload read from the finished native ELF.

Reuse the existing register/font fixtures, but do not map their synthetic code
caves for the native runs. The real PT_LOAD bytes supply every embedded hook.
"""
from __future__ import annotations

import json
import struct

import build_ogmd_native_eboot as native
import build_ogmd_apostrophe_patch as v3
import verify_ogmd_spacing_patch as single
import verify_ogmd_line_measurement as lines
from unicorn import Uc, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC


def branch_target(instruction, pc):
    word = struct.unpack('>I', instruction)[0]
    assert word >> 26 == 18 and word & 3 == 0  # Relative, no link register write.
    delta = word & 0x03fffffc
    if delta & 0x02000000:
        delta -= 0x04000000
    return pc + delta


def main():
    report = json.loads((native.OUT / 'build_report.json').read_text())
    original = native.SOURCE.read_bytes()
    elf = (native.OUT / 'EBOOT.elf').read_bytes()
    self_data = (native.OUT / 'EBOOT.BIN').read_bytes()
    assert native.sha(original) == report['source_elf_sha256']
    assert native.sha(elf) == report['patched_elf_sha256']
    assert native.sha(self_data) == report['test_eboot_sha256']
    assert struct.unpack_from('<H', self_data, 8)[0] == 0x80
    assert self_data[struct.unpack_from('>Q', self_data, 0x10)[0]:] == elf
    h, original_segments = native.program_headers(original)
    ph, segments = native.program_headers(elf)
    assert all(ph[i] == h[i] for i in range(len(h)) if i not in (6, 12))
    assert ph[12] == h[12] + 1 and segments[1:] == original_segments[1:]
    assert segments[0][:5] == original_segments[0][:5]
    assert segments[0][5:7] == (report['new_code_segment_size'],) * 2
    assert segments[0][7] == original_segments[0][7]
    compiled = v3.compile_hooks()
    hook_map = {h.address: (h, code) for h, code, _ in compiled}
    for entry in report['hooks']:
        address, pos = entry['code_address'], entry['code_file_offset']
        hook, code = hook_map[entry['hook_address']]
        assert native.file_offset(elf, address, len(code) + 4) == pos
        assert elf[pos:pos + len(code)] == code
        assert native.sha(code) == entry['code_sha256']
        assert branch_target(elf[entry['hook_file_offset']:entry['hook_file_offset'] + 4], hook.address) == address
        assert branch_target(elf[pos + len(code):pos + len(code) + 4], address + len(code)) == hook.address + 4
        assert original[entry['hook_file_offset']:entry['hook_file_offset'] + 4].hex() == hook.expected
    allowed = bytearray(len(elf))
    for pos, size in report['allowed_changes']:
        allowed[pos:pos + size] = b'\x01' * size
    assert len(elf) - len(original) == report['added_metadata_bytes']
    assert all(a == b or allowed[i] for i, (a, b) in enumerate(zip(original, elf)))
    assert not any(original[report['gap_start_file_offset']:report['next_segment_file_offset']])
    old_sections = [struct.unpack_from('>IIQQQQIIQQ', original, h[6] + n * h[11]) for n in range(h[12])]
    sections = [struct.unpack_from('>IIQQQQIIQQ', elf, ph[6] + n * ph[11]) for n in range(ph[12])]
    assert all(sections[n] == old_sections[n] for n in range(h[12]) if n != h[13])
    strings = sections[ph[13]]
    assert elf[strings[4]:strings[4] + old_sections[h[13]][5]] == original[old_sections[h[13]][4]:old_sections[h[13]][4] + old_sections[h[13]][5]]
    added = sections[-1]
    assert added[1:3] == (1, 6) and added[3] == report['hooks'][0]['code_address']
    assert added[4] == report['payload_start_file_offset'] and added[4] + added[5] == report['payload_end_file_offset']
    assert elf[strings[4] + added[0]:strings[4] + strings[5]] == b'.ogmd_vwf\0'
    analysis_end = max(s[3] + s[5] for s in sections if s[1] == 1 and s[2] & 4)
    assert analysis_end == segments[0][3] + segments[0][5]

    page = report['hooks'][0]['code_address'] & ~0xffff
    segment = segments[0]
    page_offset = page - segment[3] + segment[2]
    loaded_tail = elf[page_offset:segment[2] + segment[5]]
    visits = set()
    entries = {x['code_address'] for x in report['hooks']}

    class EmbeddedVM:
        def __init__(self, *args):
            self.vm = Uc(*args)

        def __getattr__(self, name):
            return getattr(self.vm, name)

        def mem_map(self, address, size, *args):
            if address == 0x1200000:
                return  # No RPCS3-style temporary code allocation exists.
            return self.vm.mem_map(address, size, *args)

        def mem_write(self, address, data):
            if 0x1200000 <= address < 0x1300000:
                return
            return self.vm.mem_write(address, data)

        def emu_start(self, *args, **kwargs):
            self.vm.mem_map(page, 0x10000)
            self.vm.mem_write(page, loaded_tail)
            self.vm.mem_protect(page, 0x10000, UC_PROT_READ | UC_PROT_EXEC)
            for entry in report['hooks']:
                pos = entry['hook_file_offset']
                self.vm.mem_write(entry['hook_address'], elf[pos:pos + 4])
            def track(vm, address, size, unused):
                if address in entries:
                    visits.add(address)
            self.vm.hook_add(UC_HOOK_CODE, track, begin=page, end=page + 0xffff)
            return self.vm.emu_start(*args, **kwargs)

    cases = [dict(char=c, cell=cell) for c in range(32, 127) for cell in (24.0, 32.0, 19.5)]
    cases += [dict(char=39, width=w) for w in range(34)]
    cases += [dict(char=c, **extra) for c, extra in [
        (0, {}), (31, {}), (127, {}), (128, {}), (0x2019, {'class': 3}),
        (0x300c, {'class': 3}), (39, {'class': 2}), (39, {'class': 3}),
        (39, {'no_font': True}), (39, {'no_page': True}), (39, {'base_width': 24}),
        (65, {'no_font': True}), (65, {'no_page': True}), (65, {'width': 0}), (65, {'width': 33}),
    ]]
    executions = 0
    for hook, code, _ in compiled:
        for case in cases:
            single.Uc = Uc
            expected = single.execute(hook, code, case)
            single.Uc = EmbeddedVM
            actual = single.execute(hook, code, case)
            assert actual == expected, (hex(hook.address), case)
            executions += 1
        print(f'PASS native ELF {hook.address:#x}: {len(cases)} cases', flush=True)
    single.Uc = Uc
    assert visits == entries

    examples = ["'", "I'm", "Let's", "Commander's", "don't", "'quoted'",
                '「日本語、句読点。」「＇」「’」', '‘’“”', '', 'iW iW',
                ''.join(chr(i) for i in range(32, 127)),
                "「To be called to that Commander's office,it's probably",
                "「Let's play it by ear.Any other questions?」", "「No,I'm just starting...」"]
    opening = json.loads((native.ROOT / 'reports/stage000_linebreaks_20260905.json').read_text(encoding='utf8'))['rows']
    examples += [line for row in opening[:2] for line in row['ps3_text'].split('@')]
    lines.compile_hooks = lambda: compiled
    comparisons = []
    routines = 0
    for text in examples + ['W' * 100, "I'm " * 60]:
        for cell in (24.0, 32.0):
            natural = lines.native_width(text, cell) - text.count("'") * cell * 9 / 32
            cached = natural if text in ('W' * 100, "I'm " * 60) else 0.0
            for entry in (0xb7f808, 0xb7fc20):
                lines.Uc = Uc
                reference = lines.measure(text, entry, 'v3', cell=cell, cached=cached)
                lines.Uc = EmbeddedVM
                actual = lines.measure(text, entry, 'embedded', cell=cell, cached=cached)
                assert actual == reference, (text, entry, actual, reference)
                assert abs(actual - (768 if cached else natural)) < 0.002
                comparisons.append(dict(text=text, cell=cell, entry=hex(entry), width=actual, overflow=bool(cached)))
                routines += 1
    lines.Uc = Uc
    result = dict(status='passed', patched_elf_sha256=native.sha(elf),
                  test_eboot_sha256=native.sha(self_data), hooks=12,
                  native_hook_executions=executions, v3_hook_reference_executions=executions,
                  native_full_routine_executions=routines, v3_full_routine_reference_executions=routines,
                  assertions=['Only 12 hook words, PT_LOAD sizes, padding and section metadata changed',
                              'Original code/data sections and offsets preserved; new .ogmd_vwf section covers payload',
                              'RPCS3 section-derived analysis boundary includes all embedded routines',
                              'All native hook bodies equal the confirmed v3 implementation',
                              'Every branch target and return decoded independently',
                              'Executed code and branches read from finished ELF',
                              'No temporary code caves mapped in native execution',
                              'Added code memory is readable/executable and not writable',
                              'Register preservation and caller/font memory checks pass',
                              'ASCII, apostrophe, Japanese, missing metrics and overflow agree with v3'],
                  comparisons=comparisons,
                  limitations=['Unicorn PPC64 instruction execution is not physical Cell validation',
                               'Full measurement fixtures stub the external font-mode query',
                               'RPCS3 debug SELF wrapper is not console signed',
                               'Fresh user game boot remains pending'])
    (native.OUT / 'verification_report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k != 'comparisons'}, indent=2))


if __name__ == '__main__':
    main()
