"""Run the 0x119d10 caption wrapper up to its native glyph renderer.

This executes native code with synthetic caller state. Its relationship to the
reported live Azuki scene is unconfirmed; the first candidate failed visually.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'script_editor'), str(ROOT/'work/analysis_pydeps')]
import verify_battle_text_fit as old
from core import NativeMetrics
from unicorn import UC_HOOK_CODE
import unicorn.ppc_const as p
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

TEXT = '「All hands,brace for impact and deploy anti-glare measures!」'
FONT = 0x6000000


def run(text=TEXT, cached=0, cell=28, x=343, elf=None, lines=None):
    previous = old.ELF
    if elf is not None:
        old.ELF = elf
    try:
        vm = old.vm_init(x, (-1, -1, -1))
    finally:
        old.ELF = previous
    # Unicorn's PPC64 AltiVec execution crashes on this Windows build.
    # Interpret the wrapper's color-vector moves; text math still runs natively.
    decoder = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    decoder.skipdata = True
    vector_ops = {}
    data = elf or old.ELF
    for a,b in ((0x247574,0x248600),(0x243e60,0x244950)):
        for ins in decoder.disasm(data[old.file_offset(data,a):old.file_offset(data,b)],a):
            if ins.mnemonic in ('vxor','lvx','stvx'):
                vector_ops[ins.address] = (ins.mnemonic, int.from_bytes(ins.bytes,'big'))
    vectors = {}
    font = bytearray((ROOT/'script_editor/assets/font.bin').read_bytes())
    for page in range(256):
        at = 0x54 + page*4
        value = struct.unpack_from('>I', font, at)[0]
        if value:
            struct.pack_into('>I', font, at, FONT+value)
    vm.mem_map(FONT, (len(font)+4095)&~4095)
    vm.mem_write(FONT, bytes(font))
    for obj in old.FONTS:
        vm.mem_write(obj+0x18, struct.pack('>I', FONT))
        vm.mem_write(obj+0x48, struct.pack('>ff', cell, cell))
        vm.mem_write(obj+0xfc, struct.pack('>f', cached))
    for offset, line in zip((0x3fec,0x41ec,0x43ec), lines or (text, '', '')):
        vm.mem_write(old.OBJ+offset, line.encode('utf8')+b'\0')
    draws = []
    def stub(vm, addr, size, _):
        if addr in vector_ops:
            op,word = vector_ops[addr]
            vd,ra,rb = (word>>21)&31,(word>>16)&31,(word>>11)&31
            if op == 'vxor':
                vectors[vd] = bytes(a^b for a,b in zip(vectors.get(ra,bytes(16)),vectors.get(rb,bytes(16))))
            else:
                ea = ((vm.reg_read(p.UC_PPC_REG_0+ra) if ra else 0)+vm.reg_read(p.UC_PPC_REG_0+rb))&~15
                if op == 'lvx':vectors[vd] = bytes(vm.mem_read(ea,16))
                else:vm.mem_write(ea,vectors.get(vd,bytes(16)))
            vm.reg_write(p.UC_PPC_REG_PC,addr+4)
            return
        ret = None
        if addr in (0x3326ec, 0x32dd18):
            ret = old.OBJ
        elif addr == 0x34ca78:
            ret = 0
        elif addr == 0xb4ab30:  # strchr, used only to find markup '<'
            vm.mem_write(vm.reg_read(p.UC_PPC_REG_1)+0x28,struct.pack('>Q',old.TOC))
            start = vm.reg_read(p.UC_PPC_REG_3)
            char = vm.reg_read(p.UC_PPC_REG_4)&255
            data = bytes(vm.mem_read(start, 512)).split(b'\0',1)[0]
            index = data.find(bytes([char]))
            ret = start+index if index >= 0 else 0
        elif addr == 0xb7a198:
            obj = vm.reg_read(p.UC_PPC_REG_3)
            limit = struct.unpack('>i', vm.mem_read(obj+0x50,4))[0]
            cache = struct.unpack('>f', vm.mem_read(obj+0xfc,4))[0]
            draws.append(dict(limit=limit,cached=cache,x=old.number(vm.reg_read(p.UC_PPC_REG_FPR1)),
                draw_r8=vm.reg_read(p.UC_PPC_REG_8),draw_r9=vm.reg_read(p.UC_PPC_REG_9),
                font_flags=list(vm.mem_read(obj+0xf4,2))))
            ret = 0
        if ret is not None:
            vm.reg_write(p.UC_PPC_REG_3, ret)
            vm.reg_write(p.UC_PPC_REG_PC, vm.reg_read(p.UC_PPC_REG_LR))
    vm.hook_add(UC_HOOK_CODE, stub)
    try:
        vm.emu_start(old.START, old.END+4, count=500000)
    except Exception as exc:
        raise RuntimeError(f'PC={vm.reg_read(p.UC_PPC_REG_PC):x}') from exc
    assert vm.reg_read(p.UC_PPC_REG_PC) == old.END+4
    assert old.cap_values(vm) == [-1,-1,-1]
    return draws


if __name__ == '__main__':
    for cached in (0, 500, 793, 856.625, 1000):
        print(json.dumps(dict(initial_cached=cached,draws=run(cached=cached))))
