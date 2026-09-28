"""Build a separate RPCS3 caption diagnostic; leave released game files intact."""
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'work/analysis_pydeps')]
from native_eboot import extract_elf, sha
from core import atomic_json
from build_ogmd_native_eboot import program_headers, file_offset, branch
from build_battle_text_fit import ppu_hash
from keystone import Ks, KS_ARCH_PPC, KS_MODE_PPC64, KS_MODE_BIG_ENDIAN

SOURCE = ROOT/'work/poc/battle_fit_cache_20260918'
OUT = ROOT/'work/poc/battle_trace_20260920_v2'
HOOKS = ((0x247574, '7d800026'), (0xb7a198, 'f821fbf1'), (0xb7c980, 'f821fc01'))
BANK_SIZE = 0x10000
RECORD_SIZE = 256
RECORD_COUNT = 128
MATCH_OFFSET = 0x9000
MATCH_PREFIX = '「All hands,brace'.encode('utf8')[:16]


def address(reg, value):
    return [f'lis {reg},{value >> 16}', f'ori {reg},{reg},{value & 65535}']


def assembly(hook, bank):
    # A distinct BSS extension holds bounded diagnostic records. No existing
    # font, text, game object, save, installed archive or executable code is written.
    a = ['stdu 1,-128(1)']
    registers = (0, 5, 6, 7, 11, 12)
    a += [f'std {r},{16+i*8}(1)' for i, r in enumerate(registers)]
    a += ['mfcr 0', 'stw 0,64(1)', 'mflr 0']
    a += address(11, bank)
    a += ['lwz 5,0(11)', 'addi 5,5,1', 'stw 5,0(11)',
          'cmpwi 4,0', 'beq restore']
    if hook == 0xb7a198:
        # This renderer accepts a span whose end is pointed to by r5. It need
        # not be NUL terminated, so never inspect bytes at or after that end.
        a += ['ld 5,24(1)', 'cmpwi 5,0', 'beq restore', 'lwz 5,0(5)',
              'cmplw 4,5', 'bge restore', 'stw 5,72(1)']
    a += ['lbz 5,0(4)', 'cmpwi 5,0', 'beq restore',
          'addi 12,11,256', 'li 7,128', 'search:',
          'lwz 5,0(12)', 'cmpw 5,0', 'beq record', 'cmpwi 5,0', 'beq record',
          'addi 12,12,256', 'addi 7,7,-1', 'cmpwi 7,0', 'bne search',
          'lwz 5,4(11)', 'addi 5,5,1', 'stw 5,4(11)', 'b restore',
          'record:', 'stw 0,0(12)', 'lwz 5,4(12)', 'addi 5,5,1', 'stw 5,4(12)']
    a += address(5, hook)
    a += ['stw 5,8(12)', 'stw 3,12(12)', 'stw 4,16(12)',
          'stw 8,20(12)', 'stw 9,24(12)', 'stw 10,28(12)',
          'stfs 1,32(12)', 'stfs 2,36(12)', 'stfs 3,40(12)']
    for src, dst in ((0x48,44),(0x4c,48),(0x50,52),(0xfc,56),(0xf4,60),(0xe0,240)):
        a += [f'lwz 5,{src}(3)', f'stw 5,{dst}(12)']
    a += ['stw 30,224(12)', 'stw 31,228(12)', 'stw 26,232(12)',
          'addi 5,1,128', 'stw 5,236(12)']
    # Restore incoming argument values from our private frame for the record.
    a += ['lwz 5,28(1)', 'stw 5,244(12)', 'lwz 5,36(1)', 'stw 5,248(12)',
          'lwz 5,44(1)', 'stw 5,252(12)',
          'li 6,0', 'addi 5,12,64', 'copy_text:']
    if hook == 0xb7a198:
        a += ['add 7,4,6', 'lwz 0,72(1)', 'cmplw 7,0', 'bge end_span']
    a += ['lbzx 7,4,6', 'stbx 7,5,6', 'cmpwi 7,0', 'beq match',
          'addi 6,6,1', 'cmpwi 6,159', 'blt copy_text',
          'end_span:', 'li 7,0', 'stbx 7,5,6', 'match:']
    # Keep the exact reported caption even if later menus reuse its call site.
    for i in range(0,16,4):
        a += address(5, int.from_bytes(MATCH_PREFIX[i:i+4], 'big'))
        a += [f'lwz 7,{64+i}(12)', 'cmpw 7,5', 'bne restore']
    a += address(7, bank+MATCH_OFFSET)
    a += ['li 6,0', 'copy_match:', 'lwzx 5,12,6', 'stwx 5,7,6',
          'addi 6,6,4', 'cmpwi 6,256', 'blt copy_match',
          'lwz 5,8(11)', 'addi 5,5,1', 'stw 5,8(11)', 'restore:',
          'lwz 0,64(1)', 'mtcrf 255,0']
    a += [f'ld {r},{16+i*8}(1)' for i, r in enumerate(registers)]
    a += ['addi 1,1,128']
    return '\n'.join(a)


def build():
    raw = (SOURCE/'EBOOT.BIN').read_bytes()
    assert sha(raw) == '5732c4c733fe90e989a9efdfbfe91a931794b9f5e66975a6e38485d4b5bc90dc'
    elf = extract_elf(raw)
    info = json.loads((SOURCE/'native_eboot/assets.json').read_text(encoding='utf8'))
    header, segments = program_headers(elf)
    code, data = segments[:2]
    bank_start = (data[3]+data[6]+0xffff)&~0xffff
    bank_end = bank_start+len(HOOKS)*BANK_SIZE
    assert bank_end < 0x02000000
    result = bytearray(elf)
    cursor = code[2]+code[5]
    allowed, hooks = [], []
    ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64|KS_MODE_BIG_ENDIAN)
    for n, (hook, expected) in enumerate(HOOKS):
        offset = file_offset(elf, hook)
        assert elf[offset:offset+4].hex() == expected
        bank = bank_start+n*BANK_SIZE
        target = code[3]+cursor-code[2]
        source = assembly(hook, bank)
        payload = bytes(ks.asm(source,target)[0])+bytes.fromhex(expected)
        payload += branch(target+len(payload), hook+4)
        assert cursor+len(payload) < segments[1][2]
        assert not any(elf[cursor:cursor+len(payload)])
        result[cursor:cursor+len(payload)] = payload
        result[offset:offset+4] = branch(hook,target)
        allowed += [(offset,4),(cursor,len(payload))]
        hooks.append(dict(address=hook, payload_address=target, size=len(payload),
                          bank=bank, original=expected, assembly=source))
        cursor = (cursor+len(payload)+15)&~15
    struct.pack_into('>QQ',result,header[5]+32,cursor-code[2],cursor-code[2])
    struct.pack_into('>Q',result,header[5]+header[9]+40,bank_end-data[3])
    section_at = header[6]+(header[12]-1)*header[11]
    section = struct.unpack_from('>IIQQQQIIQQ',elf,section_at)
    assert section[1:3] == (1,6)
    struct.pack_into('>Q',result,section_at+32,cursor-section[4])
    allowed += [(header[5]+32,16),(header[5]+header[9]+40,8),(section_at+32,8)]
    mask = bytearray(len(elf))
    for at,size in allowed: mask[at:at+size] = b'\1'*size
    assert len(result)==len(elf) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(elf,result)))
    boot = raw[:info['elf_offset']]+result
    packed = zlib.compress(boot,9)
    assets = OUT/'native_eboot'
    assets.mkdir(parents=True,exist_ok=True)
    meta = {**info, 'elf_sha256':sha(result),'ppu':ppu_hash(result),'sha256':sha(boot),
            'compressed_sha256':sha(packed),'caption_trace_only':True,
            'battle_fit_visual_tested':False}
    for path, content in ((OUT/'EBOOT.BIN',boot),(OUT/'EBOOT.elf',result),(assets/'EBOOT.BIN.zlib',packed)):
        if path.exists(): assert path.read_bytes()==content, f'Refusing to replace different {path}'
        else: path.write_bytes(content)
    atomic_json(assets/'assets.json',meta)
    report = dict(status='built; offline checks pending', asset=meta, hooks=hooks,
                  bank_start=bank_start,bank_end=bank_end,record_count=RECORD_COUNT,
                  record_size=RECORD_SIZE,match_offset=MATCH_OFFSET,
                  allowed_changes=[list(v) for v in allowed],
                  purpose='Identify the live caption caller and width state; no new fitting change.')
    atomic_json(OUT/'build.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('hooks','allowed_changes')},indent=2))


if __name__ == '__main__': build()
