"""Regression check: execute both complete native measurement routines.

Only the external font-mode query is stubbed (returns the native FTTF path).
The actual UTF-8 decoder, span limit, width loop, shrink path and return run.
"""
from __future__ import annotations

import json
import struct

from build_ogmd_spacing_patch import ROOT, OUT, compile_hooks
from verify_ogmd_spacing_patch import NATIVE_FONT, bits, number, single, snapshot
from unicorn import Uc, UC_ARCH_PPC, UC_MODE_PPC64, UC_MODE_BIG_ENDIAN, UC_TLB_VIRTUAL
import unicorn.ppc_const as ppc

ELF = (ROOT / "work/poc/text_layout_20260905/EBOOT.elf").read_bytes()
STACK, SP, OBJECT, FONT, TEXT, TOC, END, CAVE = 0x100000, 0x108000, 0x200000, 0x210000, 0x220000, 0x308000, 0x50000, 0x1200000


def branch(source, target):
    distance = target - source
    assert -(1 << 25) <= distance < (1 << 25)
    return struct.pack(">I", 0x48000000 | (distance & 0x3FFFFFC))


def measure(text, entry, revision, cell=24.0, maximum=768, cached=0.0):
    vm = Uc(UC_ARCH_PPC, UC_MODE_PPC64 | UC_MODE_BIG_ENDIAN)
    vm.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
    for address, size in [(STACK, 0x10000), (OBJECT, 0x10000), (FONT, 0x10000),
                          (TEXT, 0x10000), (0x300000, 0x10000), (END, 0x10000),
                          (0xB70000, 0x20000), (0x340000, 0x10000), (CAVE, 0x100000)]:
        vm.mem_map(address, size)
    vm.reg_write(ppc.UC_PPC_REG_MSR, 0x8000000000002000)
    vm.mem_write(0xB70000, ELF[0xB60000:0xB80000])
    # Font-mode query: li r3,0; blr. Calls and LR behavior still execute.
    vm.mem_write(0x34CA78, bytes.fromhex("386000004e800020"))
    for n, (hook, code, _) in enumerate(compile_hooks()):
        if revision == "stock" or revision == "v1" and hook.address in {0xB7F9A8, 0xB7F9B8}:
            continue
        address = CAVE + n * 0x10000
        vm.mem_write(hook.address, branch(hook.address, address))
        vm.mem_write(address, code + branch(address + len(code), hook.address + 4))

    def word(address, value):
        vm.mem_write(address, struct.pack(">I", value))

    vm.mem_write(FONT, NATIVE_FONT[:0x500])
    page_address = FONT + 0x1000
    for page in sorted({ord(c) >> 8 for c in text} | {0}):
        offset = struct.unpack_from(">I", NATIVE_FONT, 0x54 + page * 4)[0]
        if offset:
            vm.mem_write(page_address, NATIVE_FONT[offset:offset + 0x400])
            word(FONT + 0x54 + page * 4, page_address)
            page_address += 0x1000
        else:
            word(FONT + 0x54 + page * 4, 0)
    word(OBJECT + 0x18, FONT)
    word(OBJECT + 0x50, maximum)
    vm.mem_write(OBJECT + 0x48, struct.pack(">f", cell))
    vm.mem_write(OBJECT + 0xFC, struct.pack(">f", cached))
    vm.mem_write(TOC - 0x5288, struct.pack(">f", 0.0))
    encoded = text.encode("utf-8")
    vm.mem_write(TEXT, encoded + (b"TRAILING MUST NOT BE MEASURED" if entry == 0xB7F808 else b"") + b"\0")
    word(SP + 0x300, TEXT + len(encoded))
    for register in range(32):
        vm.reg_write(ppc.UC_PPC_REG_0 + register, 0x1122334400000000 + register)
        vm.reg_write(ppc.UC_PPC_REG_FPR0 + register, bits(register + 0.125))
    for register, value in [(1, SP), (2, TOC), (3, OBJECT), (4, TEXT), (5, SP + 0x300)]:
        vm.reg_write(ppc.UC_PPC_REG_0 + register, value)
    vm.reg_write(ppc.UC_PPC_REG_LR, END)
    before = snapshot(vm)
    vm.emu_start(entry, END, count=100000)
    assert vm.reg_read(ppc.UC_PPC_REG_PC) == END
    after = snapshot(vm)
    assert after["gpr"][1] == before["gpr"][1]
    assert after["gpr"][14:] == before["gpr"][14:]
    assert after["fpr"][14:] == before["fpr"][14:]
    return number(after["fpr"][1])


def native_width(text, cell):
    total = 0.0
    for c in text:
        code = ord(c)
        page = struct.unpack_from(">I", NATIVE_FONT, 0x54 + (code >> 8) * 4)[0]
        if not page:
            continue
        width = NATIVE_FONT[page + (code & 255) * 4 + 1]
        advance = single(cell * width / 32) if 32 <= code <= 126 and 0 < width <= 32 else cell
        total = single(total + advance)
    return total


def main():
    rows = json.loads((ROOT / "reports/stage000_linebreaks_20260905.json").read_text(encoding="utf-8"))["rows"]
    examples = [line for row in rows[:2] for line in row["ps3_text"].split("@")]
    cases = examples + ["".join(chr(i) for i in range(32, 127)), "\u300c\u3053\u3093\u306b\u3061\u306f\u300d", "", "iW iW"]
    comparisons = []
    for text in cases:
        results = {}
        for revision in ["v1", "v2"]:
            for entry in [0xB7F808, 0xB7FC20]:
                value = measure(text, entry, revision)
                results[f"{revision}_{entry:x}"] = value
                if revision == "v2":
                    assert value == native_width(text, 24.0), (text, entry, value, native_width(text, 24.0))
        comparisons.append(dict(text=text, values=results, v2_normal_scale=min(1.0, 768 / native_width(text, 24.0)) if text else 1.0))
    # A genuinely overflowing line must retain the existing shrink behavior.
    text = "W" * 100
    natural = native_width(text, 24.0)
    for entry in [0xB7F808, 0xB7FC20]:
        actual = measure(text, entry, "v2", cached=natural)
        assert abs(actual - 768.0) < 0.001, (entry, actual)
    report = dict(full_routine_executions=len(cases) * 4 + 2, comparisons=comparisons,
                  assertions=["bounded and null-terminated measurement agree", "expected native width",
                              "bounded function ignores trailing bytes", "empty and Japanese strings return safely",
                              "callee-saved registers and stack preserved", "genuine overflow still shrinks"],
                  limitation="Native mode query stubbed; this is an offline regression test, not a game screenshot")
    (OUT / "line_measurement_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
