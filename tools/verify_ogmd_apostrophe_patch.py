"""Execute the apostrophe hooks and complete native measurement routines."""
from __future__ import annotations

import hashlib
import json
import struct

import build_ogmd_apostrophe_patch as patch
import build_ogmd_spacing_patch as old
import verify_ogmd_spacing_patch as single_hook
import verify_ogmd_line_measurement as lines
import yaml


def main():
    compiled = patch.compile_hooks()
    previous = {h.address: code for h, code, _ in old.compile_hooks()}
    data = (patch.OUT / patch.PATCH_FILE).read_bytes()
    entries = yaml.safe_load(data)[patch.PPU_HASH][patch.PATCH_NAME]['Patch']
    pos = 0
    for hook, code, _ in compiled:
        count = len(code) // 4
        assert entries[pos] == ['calloc', hook.address, count]
        assert all(e[:2] == ['be32', 0] for e in entries[pos + 1:pos + 1 + count])
        assert b''.join(struct.pack('>I', e[2]) for e in entries[pos + 1:pos + 1 + count]) == code
        pos += count + 1
    assert pos == len(entries)

    cases = [dict(char=c, cell=cell) for c in range(32, 127) for cell in [24.0, 32.0, 19.5]]
    cases += [dict(char=39, width=w) for w in range(34)]
    cases += [dict(char=c, **extra) for c, extra in [
        (0, {}), (31, {}), (127, {}), (128, {}), (0x2019, {'class': 3}),
        (0x300C, {'class': 3}), (39, {'class': 2}), (39, {'class': 3}),
        (39, {'no_font': True}), (39, {'no_page': True}), (39, {'base_width': 24}),
        (65, {'no_font': True}), (65, {'no_page': True}), (65, {'width': 0}),
        (65, {'width': 33}),
    ]]
    count = 0
    for hook, code, _ in compiled:
        for case in cases:
            before, actual = single_hook.execute(hook, code, case)
            _, reference = single_hook.execute(hook, previous[hook.address], case)
            expected = {k: list(v) if isinstance(v, list) else v for k, v in reference.items()}
            active = (case['char'] == 39 and case.get('width', 22) == 22
                      and case.get('class', 1) == 1 and case.get('base_width', 32) == 32
                      and not case.get('no_font') and not case.get('no_page'))
            if active and hook.kind != 'bearing':
                advance = single_hook.single(case.get('cell', 32.0) * 13 / 32)
                if hook.kind == 'space':
                    expected['fpr'][30] = single_hook.bits(single_hook.single(single_hook.number(before['fpr'][30]) + advance))
                else:
                    expected['fpr'][hook.output_fpr] = single_hook.bits(advance)
            assert actual == expected, (hex(hook.address), case, actual, expected)
            count += 1
        print(f'PASS {hook.address:#x} {hook.kind}: {len(cases)} cases', flush=True)

    examples = [
        "「To be called to that Commander's office,it's probably",
        "「Let's play it by ear.Any other questions?」",
        "「No,I'm just starting...」",
        "'", "I'm", "Let's", "Commander's", "don't", "'quoted'",
        '「日本語、句読点。」「＇」「’」', '‘’“”', '', 'iW iW',
        ''.join(chr(i) for i in range(32, 127)),
    ]
    opening = json.loads((patch.ROOT / 'reports/stage000_linebreaks_20260905.json').read_text(encoding='utf8'))['rows']
    examples += [line for row in opening[:2] for line in row['ps3_text'].split('@')]
    comparisons = []
    routines = 0
    # Cache compiled instructions: the original ELF and hook implementations
    # still run in each VM, including UTF-8 decoding and bounded termination.
    old_compiled = old.compile_hooks()
    for text in examples:
        for cell in [24.0, 32.0]:
            result = dict(text=text, cell=cell, values={})
            for revision, hooks in [('v2', old_compiled), ('v3', compiled)]:
                lines.compile_hooks = lambda hooks=hooks: hooks
                expected = lines.native_width(text, cell)
                if revision == 'v3':
                    expected -= text.count("'") * cell * 9 / 32
                for entry in [0xB7F808, 0xB7FC20]:
                    actual = lines.measure(text, entry, revision, cell=cell)
                    assert abs(actual - expected) < 0.0001, (text, revision, entry, actual, expected)
                    result['values'][f'{revision}_{entry:x}'] = actual
                    routines += 1
            comparisons.append(result)
    lines.compile_hooks = lambda: compiled
    for text in ['W' * 100, "I'm " * 60]:
        natural = lines.native_width(text, 24.0) - text.count("'") * 24 * 9 / 32
        assert natural > 768
        for entry in [0xB7F808, 0xB7FC20]:
            actual = lines.measure(text, entry, 'v3', cached=natural)
            assert abs(actual - 768) < 0.002, actual
            routines += 1

    report = dict(status='passed', patch_sha256=hashlib.sha256(data).hexdigest(),
                  hooks=len(compiled), hook_executions=count, v2_reference_executions=count,
                  full_routine_executions=routines, comparisons=comparisons,
                  assertions=['serialized YAML equals executed code', 'only the native U+0027 advance changes',
                              'all other ASCII and fallback behavior matches v2',
                              'caller memory and non-output registers preserved',
                              'bounded and null-terminated measurement agree',
                              'both normal and overflow shrink paths pass',
                              'Japanese and Unicode punctuation retain v2 widths'],
                  runtime_status='Offline execution passed; fresh user game test pending')
    (patch.OUT / 'verification_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k != 'comparisons'}, indent=2))


if __name__ == '__main__':
    main()
