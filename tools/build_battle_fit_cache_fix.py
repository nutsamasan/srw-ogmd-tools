"""Build an isolated battle-width-cache correction; preserve release assets."""
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'work/analysis_pydeps')]
from native_eboot import load_asset, extract_elf, sha
from core import atomic_json
from build_ogmd_native_eboot import program_headers, file_offset, branch
from build_battle_text_fit import ppu_hash
from keystone import Ks, KS_ARCH_PPC, KS_MODE_PPC64, KS_MODE_BIG_ENDIAN

OUT = ROOT/'work/poc/battle_fit_cache_20260918'
BASE_SHA = 'af51c360ea1da41e22c2ec61bc38f6d4376691503b923c103bff3fd5357ab662'
HOOKS = (0x11a028, 0x11a088, 0x11a0e8)
ASSEMBLY = '''stdu 1,-64(1)
std 0,16(1)
std 11,24(1)
li 0,0
stw 0,252(3)
lwz 11,12(3)
stw 0,252(11)
lwz 11,16(3)
stw 0,252(11)
ld 0,16(1)
ld 11,24(1)
addi 1,1,64'''


def build():
    info,raw = load_asset(ROOT/'script_editor/assets/native_eboot')
    assert sha(raw) == BASE_SHA
    elf = extract_elf(raw)
    header,segments = program_headers(elf)
    segment = segments[0]
    cursor = segment[2]+segment[5]
    assert cursor%16 == 0
    result = bytearray(elf)
    allowed = []
    hooks = []
    ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64|KS_MODE_BIG_ENDIAN)
    for hook in HOOKS:
        offset = file_offset(elf,hook)
        old_word = struct.unpack_from('>I',elf,offset)[0]
        if hook == HOOKS[0]:
            assert old_word & 0xfc000003 == 0x48000000
            delta = old_word & 0x03fffffc
            if delta & 0x02000000:delta -= 0x04000000
            resume = hook+delta  # Continue through the existing cap/save hook.
        else:
            assert old_word == 0x60000000
            resume = hook+4
        address = segment[3]+cursor-segment[2]
        code = bytes(ks.asm(ASSEMBLY,address)[0])
        payload = code+branch(address+len(code),resume)
        assert cursor+len(payload)<segments[1][2] and not any(elf[cursor:cursor+len(payload)])
        result[cursor:cursor+len(payload)] = payload
        result[offset:offset+4] = branch(hook,address)
        allowed += [(offset,4),(cursor,len(payload))]
        hooks.append(dict(address=hook,payload_address=address,resume=resume,size=len(payload),assembly=ASSEMBLY))
        cursor = (cursor+len(payload)+15)&~15
    struct.pack_into('>QQ',result,header[5]+32,cursor-segment[2],cursor-segment[2])
    allowed.append((header[5]+32,16))
    section_at = header[6]+(header[12]-1)*header[11]
    section = struct.unpack_from('>IIQQQQIIQQ',elf,section_at)
    assert section[1:3] == (1,6)
    struct.pack_into('>Q',result,section_at+32,cursor-section[4])
    allowed.append((section_at+32,8))
    mask = bytearray(len(elf))
    for at,size in allowed:mask[at:at+size] = b'\1'*size
    assert len(result)==len(elf) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(elf,result)))
    patched = raw[:info['elf_offset']]+result
    packed = zlib.compress(patched,9)
    assets = OUT/'native_eboot'
    assets.mkdir(parents=True,exist_ok=True)
    (assets/'EBOOT.BIN.zlib').write_bytes(packed)
    (OUT/'EBOOT.BIN').write_bytes(patched)
    (OUT/'EBOOT.elf').write_bytes(result)
    meta = {**info,'elf_sha256':sha(result),'ppu':ppu_hash(result),'sha256':sha(patched),
        'compressed_sha256':sha(packed),'previous_elf_sha256':info['elf_sha256'],
        'previous_eboot_sha256':info['sha256'],'battle_width_cache_reset':True,
        'battle_fit_visual_tested':False}
    atomic_json(assets/'assets.json',meta)
    atomic_json(OUT/'build.json',dict(status='built; offline checks pending',asset=meta,
        hooks=hooks,allowed_changes=[list(a) for a in allowed],source_preserved=True,
        main_dialogue_and_backlog_code_unchanged=True))
    print(json.dumps(meta,indent=2))


if __name__ == '__main__':build()
