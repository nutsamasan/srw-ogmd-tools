"""Build a version-locked RPCS3 test patch for OGMD native Latin widths.

The target executable stays unchanged. RPCS3 allocates each hook's code,
inserts a branch, and provides the return to the original next instruction.
Dependencies are isolated under work/analysis_pydeps.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "work/analysis_pydeps"))
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN
from keystone import Ks, KS_ARCH_PPC, KS_MODE_PPC64, KS_MODE_BIG_ENDIAN

ELF_SHA256 = "75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0"
PPU_HASH = "PPU-e429bb11d03c2e6a046775179d21169cba555c47"
PATCH_NAME = "OGMD English dialogue native spacing v2"
GAME_NAME = "Super Robot Wars OG The Moon Dwellers"
OUT = ROOT / "work/poc/text_layout_20260905/spacing_v2"
PATCH_FILE = "ogmd_native_spacing_v2.yml"


@dataclass(frozen=True)
class Hook:
    address: int
    expected: str
    original: str
    kind: str
    object_register: int = 31
    output_fpr: int = 0


HOOKS = [
    # The formatted-dialogue wrapper measures text spans through b7f808.
    # v1 covered only its null-terminated sibling at b7fc20, leaving the
    # wrapper's cached width at a full cell per character and triggering shrink.
    Hook(0xB7F9A8, "c0fe0048", "lfs 7,72(30)", "measure", 30, 7),
    Hook(0xB7F9B8, "c0de0048", "lfs 6,72(30)", "measure", 30, 6),
    Hook(0xB7FDB4, "c0fe0048", "lfs 7,72(30)", "measure", 30, 7),
    Hook(0xB7FDC4, "c0de0048", "lfs 6,72(30)", "measure", 30, 6),
    Hook(0xB7B848, "efde002a", "fadds 30,30,0", "space"),
    Hook(0xB7E01C, "efde002a", "fadds 30,30,0", "space"),
    Hook(0xB7C81C, "c01f0048", "lfs 0,72(31)", "glyph", 31, 0),
    Hook(0xB7EFF0, "c01f0048", "lfs 0,72(31)", "glyph", 31, 0),
    Hook(0xB7BA14, "c3bf0048", "lfs 29,72(31)", "glyph", 31, 29),
    Hook(0xB7E1E8, "c3bf0048", "lfs 29,72(31)", "glyph", 31, 29),
    Hook(0xB7B970, "ecdb30fa", "fmadds 6,27,3,6", "bearing"),
    Hook(0xB7E144, "ecdb30fa", "fmadds 6,27,3,6", "bearing"),
]


def assembly(hook: Hook) -> str:
    # Own frame: never borrow the caller's live temporary stack slots.
    code = [
        "stdu 1,-256(1)",
        "std 0,16(1)", "std 9,24(1)", "std 10,32(1)",
        "std 11,40(1)", "std 12,48(1)",
        "mfcr 0", "stw 0,56(1)",
        "stfd 1,64(1)", "stfd 2,72(1)",
        f"lwz 9,24({hook.object_register})",
        "cmpwi 9,0", "beq fallback",
        "lwz 10,8(9)", "cmpwi 10,32", "bne fallback",
        "lwz 11,84(9)", "cmpwi 11,0", "beq fallback",
    ]
    if hook.kind == "measure":
        code += ["cmpwi 27,1", "bne fallback", "mr 12,29"]
    else:
        code += [
            "lwz 9,564(1)", "cmpwi 9,1", "bne fallback",  # old SP+0x134
            "lwz 9,572(1)", "lwz 10,512(1)",  # text + byte index
            "lbzx 12,9,10",
        ]
    code += [
        "cmplwi 12,32", "blt fallback",
        "cmplwi 12,126", "bgt fallback",
        "slwi 10,12,2", "add 9,11,10", "lbz 10,1(9)",
        "cmpwi 10,0", "beq fallback",
        "cmplwi 10,32", "bgt fallback",
    ]
    if hook.kind != "bearing":
        code += [
            "std 10,80(1)", "lfd 1,80(1)", "fcfid 1,1", "frsp 1,1",
            "lis 9,15616",  # float 1/32 == 0x3d000000
            "stw 9,88(1)", "lfs 2,88(1)", "fmuls 1,1,2",
        ]
        if hook.kind == "space":
            code += ["fmuls 2,0,1", "fadds 30,30,2"]
        else:
            code += [hook.original, f"fmuls {hook.output_fpr},{hook.output_fpr},1"]
    # The native loop adds half of (cell width - glyph width) to center each
    # glyph in a full-width cell. Omit that addition for proportional ASCII.
    code += [
        "b restore", "fallback:", hook.original, "restore:",
        "lfd 1,64(1)", "lfd 2,72(1)",
        "lwz 0,56(1)", "mtcrf 255,0",
        "ld 0,16(1)", "ld 9,24(1)", "ld 10,32(1)",
        "ld 11,40(1)", "ld 12,48(1)", "addi 1,1,256",
    ]
    return "\n".join(code) + "\n"


def compile_hooks() -> list[tuple[Hook, bytes, str]]:
    elf = (ROOT / "work/poc/text_layout_20260905/EBOOT.elf").read_bytes()
    if hashlib.sha256(elf).hexdigest() != ELF_SHA256:
        raise ValueError("Target ELF revision mismatch")
    ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64 | KS_MODE_BIG_ENDIAN)
    cs = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    compiled = []
    for hook in HOOKS:
        offset = hook.address - 0x10000
        if elf[offset:offset + 4].hex() != hook.expected:
            raise ValueError(f"Hook original mismatch at {hook.address:#x}")
        original, _ = ks.asm(hook.original)
        if bytes(original).hex() != hook.expected:
            raise ValueError(f"Original instruction assembly mismatch: {hook.original}")
        source = assembly(hook)
        encoded, _ = ks.asm(source, 0x10000)
        code = bytes(encoded)
        decoded = list(cs.disasm(code, 0x10000))
        if len(decoded) * 4 != len(code):
            raise ValueError("Incomplete disassembly")
        if any(i.mnemonic in {"bl", "bctrl", "blrl", "mtlr", "mtctr"} for i in decoded):
            raise ValueError("Hooks must preserve LR/CTR without calls")
        compiled.append((hook, code, source))
    return compiled


def main() -> None:
    compiled = compile_hooks()
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [
        "Version: 1.2", "", f"{PPU_HASH}:", f"  {json.dumps(PATCH_NAME)}:",
        "    Games:", f"      {json.dumps(GAME_NAME)}:", '        BLJS10335: [ "01.00" ]',
        "    Author: Codex", "    Patch Version: 2.0",
        "    Notes: >-",
        "      Test build. Uses the loaded PS3 font's native ASCII widths for measurement",
        "      and drawing, and removes fixed-cell centering for those glyphs.",
        "      Includes bounded-span measurement used by formatted dialogue.",
        "      Non-ASCII and unsupported font metrics retain the original behavior.",
        "      Requires a fresh game boot. EBOOT and font archives remain unchanged.",
        "    Patch:",
    ]
    cs = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    report = []
    for hook, code, source in compiled:
        name = f"{hook.address:08x}_{hook.kind}"
        (OUT / f"{name}.s").write_text(source, encoding="utf-8")
        (OUT / f"{name}.bin").write_bytes(code)
        disassembly = list(cs.disasm(code, 0x10000))
        lines += [f"      # {hook.kind} at 0x{hook.address:08x}: {hook.original}",
                  f"      - [ calloc, 0x{hook.address:08x}, {len(code) // 4} ]"]
        for i in disassembly:
            value = struct.unpack(">I", i.bytes)[0]
            lines.append(f"      - [ be32, 0x00000000, 0x{value:08x} ] # {i.mnemonic} {i.op_str}")
        report.append(dict(address=f"0x{hook.address:08x}", kind=hook.kind,
                           original=hook.expected, instruction_count=len(code) // 4,
                           code_sha256=hashlib.sha256(code).hexdigest()))
    (OUT / PATCH_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "build_report.json").write_text(json.dumps(dict(
        elf_sha256=ELF_SHA256, ppu_hash=PPU_HASH, hooks=report,
        runtime_status="Not yet tested in game"), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(output=str(OUT), hooks=len(report),
                          instructions=sum(x["instruction_count"] for x in report)), indent=2))


if __name__ == "__main__":
    main()
