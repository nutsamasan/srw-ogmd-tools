"""Verify the completed 10-unit EBOOT through native PPC measurement/drawing."""
import json
import struct
from build_tighter_apostrophe_test import ROOT, BASE, OUT, NEW_WIDTH
from build_ogmd_native_eboot import file_offset, program_headers
import build_ogmd_apostrophe_patch as v3
import verify_ogmd_spacing_patch as single
import verify_ogmd_line_measurement as lines
from trace_battle_glyphs import trace
from native_eboot import sha
from core import atomic_json
from unicorn import Uc, UC_PROT_READ, UC_PROT_EXEC


def verify():
    report = json.loads((OUT/'build.json').read_text(encoding='utf8'))
    elf = (OUT/'EBOOT.elf').read_bytes()
    before_elf = (BASE/'EBOOT.elf').read_bytes()
    assert sha(elf) == report['asset']['elf_sha256']
    compiled = v3.compile_hooks()
    assert program_headers(elf) == program_headers(before_elf)
    assert [i for i, (a, b) in enumerate(zip(elf, before_elf)) if a != b] == sorted(report['changed_elf_bytes'])
    page = report['hooks'][0]['payload_address'] & ~0xffff
    _, segments = program_headers(elf)
    segment = segments[0]
    tail = elf[file_offset(elf, page):segment[2]+segment[5]]

    class EmbeddedVM:
        def __init__(self, *args):
            self.vm = Uc(*args)

        def __getattr__(self, name):
            return getattr(self.vm, name)

        def mem_map(self, address, size, *args):
            if address == 0x1200000:
                return
            return self.vm.mem_map(address, size, *args)

        def mem_write(self, address, data):
            if 0x1200000 <= address < 0x1300000:
                return
            return self.vm.mem_write(address, data)

        def emu_start(self, *args, **kwargs):
            self.vm.mem_map(page, 0x10000)
            self.vm.mem_write(page, tail)
            self.vm.mem_protect(page, 0x10000, UC_PROT_READ | UC_PROT_EXEC)
            for entry in report['hooks']:
                at = file_offset(elf, entry['hook_address'])
                self.vm.mem_write(entry['hook_address'], elf[at:at+4])
            return self.vm.emu_start(*args, **kwargs)

    cases = [dict(char=c, cell=cell) for c in range(32, 127) for cell in (24., 32., 19.5)]
    cases += [dict(char=39, width=w) for w in range(34)]
    cases += [dict(char=c, **extra) for c, extra in [
        (0, {}), (31, {}), (127, {}), (128, {}), (0x2019, {'class': 3}),
        (0x300c, {'class': 3}), (39, {'class': 2}), (39, {'class': 3}),
        (39, {'no_font': True}), (39, {'no_page': True}), (39, {'base_width': 24}),
        (65, {'no_font': True}), (65, {'no_page': True}), (65, {'width': 0}), (65, {'width': 33})]]
    count = 0
    try:
        for hook, code, _ in compiled:
            for case in cases:
                single.Uc = Uc
                before, reference = single.execute(hook, code, case)
                expected = {k: list(v) if isinstance(v, list) else v for k, v in reference.items()}
                active = (case['char'] == 39 and case.get('width', 22) == 22
                          and case.get('class', 1) == 1 and case.get('base_width', 32) == 32
                          and not case.get('no_font') and not case.get('no_page'))
                if active and hook.kind != 'bearing':
                    advance = single.single(case.get('cell', 32.)*NEW_WIDTH/32)
                    if hook.kind == 'space':
                        expected['fpr'][30] = single.bits(single.single(single.number(before['fpr'][30])+advance))
                    else:
                        expected['fpr'][hook.output_fpr] = single.bits(advance)
                single.Uc = EmbeddedVM
                _, actual = single.execute(hook, code, case)
                assert actual == expected, (hex(hook.address), case)
                count += 1
            print(f'PASS embedded {hook.address:x}: {len(cases)} cases', flush=True)
    finally:
        single.Uc = Uc

    examples = ["adults' discussions!", "I've", "I'm", "Let's", "don't", "'quoted'",
                "Shiun's House", 'words with normal spaces', '\u300c\u65e5\u672c\u8a9e\u300d',
                '\u2018\u2019\u201c\u201d', '', ''.join(chr(c) for c in range(32, 127)),
                "supposed to interfere in the adults' discussions!"]
    measurements = []
    lines.compile_hooks = lambda: compiled
    try:
        lines.Uc = EmbeddedVM
        for text in examples + ['W'*100, "I'm "*60]:
            for cell in (24., 32.):
                natural = lines.native_width(text, cell)-text.count("'")*cell*(22-NEW_WIDTH)/32
                overflow = text in ('W'*100, "I'm "*60)
                for entry in (0xb7f808, 0xb7fc20):
                    actual = lines.measure(text, entry, 'embedded', cell=cell,
                                           cached=natural if overflow else 0,
                                           maximum=768 if overflow else 0xffffffff)
                    assert abs(actual-(768 if overflow else natural)) < 0.002
                    measurements.append(dict(text=text, cell=cell, entry=hex(entry), width=actual))
    finally:
        lines.Uc = Uc

    glyphs = []
    for text in ("adults' discussions!", "I've", "I'm", 'words with normal spaces'):
        for cell in (20, 24, 28, 32):
            for unbounded in (False, True):
                old = trace(text, cell=cell, maximum=-1, cached=0, elf=before_elf, unbounded=unbounded, x=0)
                new = trace(text, cell=cell, maximum=-1, cached=0, elf=elf, unbounded=unbounded, x=0)
                delta = text.count("'")*cell*(13-NEW_WIDTH)/32
                assert abs(old['advance']-new['advance']-delta) < 0.001
                assert len(old['quads']) == len(new['quads'])
                assert all(abs((a[2]-a[0])-(b[2]-b[0])) < 0.001
                           for a, b in zip(old['quads'], new['quads']))
                if "'" not in text:
                    assert old == new
                glyphs.append(dict(text=text, cell=cell, unbounded=unbounded,
                                   old_width=old['advance'], new_width=new['advance'],
                                   old_quads=old['quads'], new_quads=new['quads']))
    result = dict(status='passed', elf_sha256=sha(elf), native_hook_executions=count,
                  reference_hook_executions=count, native_measurement_executions=len(measurements),
                  native_glyph_loop_executions=len(glyphs)*2,
                  only_ten_immediate_bytes_changed=True, word_spaces_unchanged=True,
                  glyph_quad_widths_preserved=True,
                  real_game_visual_test=False, measurements=measurements, glyphs=glyphs)
    atomic_json(OUT/'verification.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('measurements', 'glyphs')}))


if __name__ == '__main__':
    verify()
