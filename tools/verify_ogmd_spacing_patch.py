"""Execute the generated hooks on a PPC64 emulator before game testing."""
from __future__ import annotations

import json
import struct
import sys

sys.dont_write_bytecode = True
from build_ogmd_spacing_patch import ROOT, OUT, PPU_HASH, PATCH_NAME, PATCH_FILE, compile_hooks
import yaml
from unicorn import Uc, UC_ARCH_PPC, UC_MODE_PPC64, UC_MODE_BIG_ENDIAN, UC_TLB_VIRTUAL
import unicorn.ppc_const as ppc

CODE, STACK, SP, OBJECT, FONT, PAGE, TEXT = (
    0x1200000, 0x100000, 0x108000, 0x200000, 0x210000, 0x210580, 0x220000
)
NATIVE_FONT = (ROOT / "work/poc/text_layout_20260905/ps3_font_original.bin").read_bytes()


def bits(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def number(value: int) -> float:
    return struct.unpack(">d", struct.pack(">Q", value))[0]


def single(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def execute(hook, code: bytes, case: dict, original: bool = False):
    vm = Uc(UC_ARCH_PPC, UC_MODE_PPC64 | UC_MODE_BIG_ENDIAN)
    # Use the default PPC64 CPU and direct mapped test memory. Unicorn 2.1.4's
    # explicit PPC64 model selection misses its model-table offset; the default
    # POWER10 otherwise requires a system MMU setup unrelated to these hooks.
    vm.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
    for addr in [CODE, hook.address & ~0xFFFF, STACK, OBJECT, FONT, TEXT]:
        vm.mem_map(addr, 0x10000)
    vm.reg_write(ppc.UC_PPC_REG_MSR, 0x8000000000002000)
    def branch(source, dest):
        delta = dest - source
        assert -(1 << 25) <= delta < (1 << 25) and delta % 4 == 0
        return struct.pack(">I", 0x48000000 | (delta & 0x03FFFFFC))
    if original:
        vm.mem_write(hook.address, bytes.fromhex(hook.expected))
    else:
        vm.mem_write(hook.address, branch(hook.address, CODE))
        vm.mem_write(CODE, code + branch(CODE + len(code), hook.address + 4))
    for register in range(32):
        vm.reg_write(ppc.UC_PPC_REG_0 + register, 0x1122334400100000 + register * 0x123)
        vm.reg_write(ppc.UC_PPC_REG_FPR0 + register, bits(0.25 + register * 1.125))
    vm.reg_write(ppc.UC_PPC_REG_1, SP)
    vm.reg_write(ppc.UC_PPC_REG_0 + hook.object_register, OBJECT)
    vm.reg_write(ppc.UC_PPC_REG_27, case.get("class", 1))
    vm.reg_write(ppc.UC_PPC_REG_29, case["char"])
    vm.reg_write(ppc.UC_PPC_REG_CR, 0x96a55a69)
    vm.reg_write(ppc.UC_PPC_REG_LR, 0x12345678)
    vm.reg_write(ppc.UC_PPC_REG_CTR, 0x89123456)
    vm.reg_write(ppc.UC_PPC_REG_XER, 0x20000000)
    vm.reg_write(ppc.UC_PPC_REG_FPR0, bits(case.get("cell", 32.0)))
    vm.reg_write(ppc.UC_PPC_REG_FPR0 + 27, bits(0.75))
    vm.mem_write(FONT, NATIVE_FONT[:0x980])
    def word(address, value):
        vm.mem_write(address, struct.pack(">I", value))
    word(OBJECT + 0x18, 0 if case.get("no_font") else FONT)
    vm.mem_write(OBJECT + 0x48, struct.pack(">f", case.get("cell", 32.0)))
    word(FONT + 8, case.get("base_width", 32))
    word(FONT + 0x54, 0 if case.get("no_page") else PAGE)
    char = case["char"]
    if 0 <= char <= 255 and "width" in case:
        vm.mem_write(PAGE + char * 4 + 1, bytes([case["width"]]))
    word(SP + 0x134, case.get("class", 1))
    word(SP + 0x13C, TEXT)
    word(SP + 0x100, 5)
    vm.mem_write(TEXT, b"start" + bytes([char & 255]) + b"end\x00")
    before = snapshot(vm)
    regions = [(OBJECT, 0x10000), (FONT, 0x10000), (TEXT, 0x10000), (SP, 0x400)]
    immutable = [bytes(vm.mem_read(a, z)) for a, z in regions]
    end = hook.address + 4
    try:
        vm.emu_start(hook.address, end, count=300)
    except Exception as exc:
        pc = vm.reg_read(ppc.UC_PPC_REG_PC)
        raise RuntimeError(f"{hook.address:#x} {case} original={original}, PC={pc:#x}, instruction={bytes(vm.mem_read(pc, 4)).hex()}") from exc
    if vm.reg_read(ppc.UC_PPC_REG_PC) != end:
        raise AssertionError("Hook did not reach its return instruction")
    for (a, z), data in zip(regions, immutable):
        assert bytes(vm.mem_read(a, z)) == data, f"Unexpected memory write at {a:#x}"
    return before, snapshot(vm)


def snapshot(vm):
    return {
        "gpr": [vm.reg_read(ppc.UC_PPC_REG_0 + i) for i in range(32)],
        "fpr": [vm.reg_read(ppc.UC_PPC_REG_FPR0 + i) for i in range(32)],
        "cr": vm.reg_read(ppc.UC_PPC_REG_CR),
        "lr": vm.reg_read(ppc.UC_PPC_REG_LR),
        "ctr": vm.reg_read(ppc.UC_PPC_REG_CTR),
        "xer": vm.reg_read(ppc.UC_PPC_REG_XER),
    }


def main():
    cases = [dict(char=c, cell=cell) for c in range(32, 127) for cell in [24.0, 32.0]]
    cases += [dict(char=c, **extra) for c, extra in [
        (0, {}), (31, {}), (127, {}), (128, {}), (227, {"class": 3}),
        (0x300C, {"class": 3}), (65, {"class": 2}),
        (65, {"no_font": True}), (65, {"no_page": True}),
        (65, {"base_width": 24}), (65, {"width": 0}), (65, {"width": 33}),
    ]]
    compiled = compile_hooks()
    entries = yaml.safe_load((OUT / PATCH_FILE).read_text(encoding="utf-8"))[PPU_HASH][PATCH_NAME]["Patch"]
    position = 0
    for hook, code, _ in compiled:
        count = len(code) // 4
        assert entries[position] == ["calloc", hook.address, count]
        encoded = entries[position + 1:position + 1 + count]
        assert all(entry[0] == "be32" and entry[1] == 0 for entry in encoded)
        assert b"".join(struct.pack(">I", entry[2]) for entry in encoded) == code
        position += count + 1
    assert position == len(entries)
    count = 0
    for hook, code, _ in compiled:
        for case in cases:
            before, actual = execute(hook, code, case)
            _, reference = execute(hook, code, case, original=True)
            expected = {k: list(v) if isinstance(v, list) else v for k, v in reference.items()}
            char = case["char"]
            width = case.get("width", NATIVE_FONT[0x580 + char * 4 + 1] if 0 <= char <= 255 else 0)
            active = (32 <= char <= 126 and case.get("class", 1) == 1
                      and case.get("base_width", 32) == 32 and 0 < width <= 32
                      and not case.get("no_font") and not case.get("no_page"))
            if active:
                if hook.kind == "bearing":
                    expected["fpr"][6] = before["fpr"][6]
                elif hook.kind == "space":
                    advance = single(number(before["fpr"][0]) * width / 32)
                    expected["fpr"][30] = bits(single(number(before["fpr"][30]) + advance))
                else:
                    expected["fpr"][hook.output_fpr] = bits(single(case.get("cell", 32.0) * width / 32))
            if actual != expected:
                raise AssertionError(json.dumps(dict(hook=hex(hook.address), case=case,
                    expected=expected, actual=actual), indent=2))
            count += 1
        print(f"PASS {hook.address:#x} {hook.kind}: {len(cases)} cases")
    report = dict(emulator="Unicorn 2.1.4 PPC64 default POWER10, virtual TLB", hook_executions=count,
                  original_reference_executions=count, hooks=len(compiled),
                  assertions=["serialized YAML matches verified instruction bytes and allocation counts",
                              "relocated code branches in and returns to original next instruction", "GPR/CR/LR/CTR/XER preservation",
                              "all non-output FPRs preserved", "ASCII width arithmetic",
                              "non-ASCII and unsupported-metric fallback", "caller and font data unchanged"],
                  runtime_status="Offline instruction checks passed; awaiting user game test")
    (OUT / "verification_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
