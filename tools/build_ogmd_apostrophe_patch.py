"""Keep spacing v2, with the PS4 English advance for the native apostrophe."""
from __future__ import annotations

import hashlib
import json
import struct

import build_ogmd_spacing_patch as base

ROOT = base.ROOT
OUT = ROOT / 'work/poc/text_layout_20260909/spacing_v3_apostrophe'
PATCH_NAME = 'OGMD English dialogue native spacing v3 (apostrophe)'
PATCH_FILE = 'ogmd_native_spacing_v3_apostrophe.yml'
PPU_HASH, GAME_NAME = base.PPU_HASH, base.GAME_NAME
NATIVE_FONT_SHA256 = '777f45f05e8936bc75611e6cd59467620503e2b38b14c57199b51e05a50c71d2'
OLD_WIDTH, NEW_WIDTH = 22, 13


def assembly(hook):
    source = base.assembly(hook)
    marker = 'cmplwi 10,32\nbgt fallback\n'
    assert source.count(marker) == 1
    # Only change U+0027 in the known native 22-unit metric. The bitmap and
    # draw geometry still use the native descriptor. All other metrics retain
    # v2 behavior, including already narrow fonts and non-ASCII characters.
    addition = (
        'cmplwi 12,39\nbne width_ready\n'
        f'cmplwi 10,{OLD_WIDTH}\nbne width_ready\n'
        f'li 10,{NEW_WIDTH}\nwidth_ready:\n'
    )
    return source.replace(marker, marker + addition)


def compile_hooks():
    native = (ROOT / 'work/poc/text_layout_20260905/ps3_font_original.bin').read_bytes()
    assert hashlib.sha256(native).hexdigest() == NATIVE_FONT_SHA256
    donor = (ROOT / 'work/extracted/ps4_lang/Dat/Font/@En/font.bin').read_bytes()
    for font, expected in [(native, OLD_WIDTH), (donor, NEW_WIDTH)]:
        assert font[:4] == b'FTTF' and struct.unpack_from('>I', font, 8)[0] == 32
        page = struct.unpack_from('>I', font, 0x54)[0]
        assert font[page + 39 * 4 + 1] == expected
    ks = base.Ks(base.KS_ARCH_PPC, base.KS_MODE_PPC64 | base.KS_MODE_BIG_ENDIAN)
    cs = base.Cs(base.CS_ARCH_PPC, base.CS_MODE_64 | base.CS_MODE_BIG_ENDIAN)
    result = []
    # Also verifies the full ELF hash and every original hook instruction.
    for hook, _, _ in base.compile_hooks():
        source = assembly(hook)
        encoded, _ = ks.asm(source, 0x10000)
        code = bytes(encoded)
        decoded = list(cs.disasm(code, 0x10000))
        assert len(decoded) * 4 == len(code)
        assert not any(i.mnemonic in {'bl', 'bctrl', 'blrl', 'mtlr', 'mtctr'} for i in decoded)
        result.append((hook, code, source))
    return result


def main():
    compiled = compile_hooks()
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [
        'Version: 1.2', '', f'{PPU_HASH}:', f'  {json.dumps(PATCH_NAME)}:',
        '    Games:', f'      {json.dumps(GAME_NAME)}:', '        BLJS10335: [ "01.00" ]',
        '    Author: Codex', '    Patch Version: 3.0', '    Notes: >-',
        '      Retains v2 proportional ASCII rendering and both measurement routines.',
        '      U+0027 uses the official PS4 English 13-unit advance when the loaded',
        '      PS3 font reports 22. Other glyphs and metrics keep v2 behavior.',
        '      Replaces v2. Fresh game boot required; no script, font, or EBOOT edits.',
        '    Patch:',
    ]
    cs = base.Cs(base.CS_ARCH_PPC, base.CS_MODE_64 | base.CS_MODE_BIG_ENDIAN)
    hooks = []
    for hook, code, source in compiled:
        name = f'{hook.address:08x}_{hook.kind}'
        (OUT / (name + '.s')).write_text(source, encoding='utf8')
        (OUT / (name + '.bin')).write_bytes(code)
        lines += [f'      # {hook.kind} at 0x{hook.address:08x}: {hook.original}',
                  f'      - [ calloc, 0x{hook.address:08x}, {len(code) // 4} ]']
        for insn in cs.disasm(code, 0x10000):
            value = struct.unpack('>I', insn.bytes)[0]
            lines.append(f'      - [ be32, 0x00000000, 0x{value:08x} ] # {insn.mnemonic} {insn.op_str}')
        hooks.append(dict(address=hex(hook.address), kind=hook.kind,
                          code_sha256=hashlib.sha256(code).hexdigest()))
    payload = ('\n'.join(lines) + '\n').encode('utf8')
    (OUT / PATCH_FILE).write_bytes(payload)
    report = dict(elf_sha256=base.ELF_SHA256, native_font_sha256=NATIVE_FONT_SHA256,
                  donor_font_sha256=hashlib.sha256((ROOT / 'work/extracted/ps4_lang/Dat/Font/@En/font.bin').read_bytes()).hexdigest(),
                  patch_sha256=hashlib.sha256(payload).hexdigest(), hooks=hooks,
                  codepoint='U+0027', old_advance=OLD_WIDTH, new_advance=NEW_WIDTH,
                  runtime_status='Awaiting offline checks and fresh user game test')
    (OUT / 'build_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(output=str(OUT / PATCH_FILE), hooks=len(hooks))))


if __name__ == '__main__':
    main()
