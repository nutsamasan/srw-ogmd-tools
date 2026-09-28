"""Fit battle captions on the plain-text path identified by the live trace."""
import json
import struct
import zlib
from build_battle_trace import ROOT
from native_eboot import extract_elf,sha
from build_ogmd_native_eboot import program_headers,file_offset,branch
from build_battle_text_fit import ppu_hash
from core import atomic_json
from keystone import Ks,KS_ARCH_PPC,KS_MODE_PPC64,KS_MODE_BIG_ENDIAN

BASE=ROOT/'work/poc/battle_trace_20260920_v2'
OUT=ROOT/'work/poc/battle_caption_path_fix_20260920_v2'
HOOK=0x106fac
# Reserve a right inset: the last glyph's textured quad can extend beyond its
# proportional advance. The visible box allows 793/744 pixels respectively.
FULL_CAP=768
COMPACT_CAP=720
ASSEMBLY=f'''stdu 1,-64(1)
std 0,16(1)
std 11,24(1)
mfcr 0
stw 0,32(1)
lwz 11,0(31)
li 0,{FULL_CAP}
cmpwi 26,0
beq set_limit
li 0,{COMPACT_CAP}
set_limit:
stw 0,80(11)
li 0,0
stw 0,252(11)
lwz 0,32(1)
mtcrf 255,0
ld 0,16(1)
ld 11,24(1)
addi 1,1,64
li 22,0'''


def build():
    raw=(BASE/'EBOOT.BIN').read_bytes()
    assert sha(raw)=='9d2d334ba7b1878337cb872a7a1b012b411acac629eef96a4f067da5b5bce307'
    elf=extract_elf(raw)
    info=json.loads((BASE/'native_eboot/assets.json').read_text(encoding='utf8'))
    prior=json.loads((BASE/'build.json').read_text(encoding='utf8'))
    h,ss=program_headers(elf)
    offset=file_offset(elf,HOOK)
    assert elf[offset:offset+4].hex()=='3ac00000'
    cursor=ss[0][2]+ss[0][5]
    target=ss[0][3]+cursor-ss[0][2]
    ks=Ks(KS_ARCH_PPC,KS_MODE_PPC64|KS_MODE_BIG_ENDIAN)
    code=bytes(ks.asm(ASSEMBLY,target)[0])
    payload=code+branch(target+len(code),HOOK+4)
    assert cursor+len(payload)<ss[1][2] and not any(elf[cursor:cursor+len(payload)])
    result=bytearray(elf)
    result[offset:offset+4]=branch(HOOK,target)
    result[cursor:cursor+len(payload)]=payload
    end=(cursor+len(payload)+15)&~15
    struct.pack_into('>QQ',result,h[5]+32,end-ss[0][2],end-ss[0][2])
    section_at=h[6]+(h[12]-1)*h[11]
    section=struct.unpack_from('>IIQQQQIIQQ',elf,section_at)
    assert section[1:3]==(1,6)
    struct.pack_into('>Q',result,section_at+32,end-section[4])
    changes=[(offset,4),(cursor,len(payload)),(h[5]+32,16),(section_at+32,8)]
    mask=bytearray(len(elf))
    for at,size in changes:mask[at:at+size]=b'\1'*size
    assert len(result)==len(elf) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(elf,result)))
    boot=raw[:info['elf_offset']]+result
    packed=zlib.compress(boot,9)
    meta={**info,'sha256':sha(boot),'elf_sha256':sha(result),'ppu':ppu_hash(result),
          'compressed_sha256':sha(packed),'caption_trace_only':False,
          'plain_battle_caption_fitting':True,'battle_fit_visual_tested':False}
    assets=OUT/'native_eboot';assets.mkdir(parents=True,exist_ok=True)
    for path,data in ((OUT/'EBOOT.elf',result),(OUT/'EBOOT.BIN',boot),(assets/'EBOOT.BIN.zlib',packed)):
        if path.exists():assert path.read_bytes()==data,f'Refusing to replace different {path}'
        else:path.write_bytes(data)
    atomic_json(assets/'assets.json',meta)
    atomic_json(OUT/'build.json',{**prior,'asset':meta,'status':'built; offline checks pending',
        'purpose':'Fit the live plain-text battle caption path; retain diagnostics for the user test.',
        'caption_fit_hook':dict(address=HOOK,payload_address=target,size=len(payload),assembly=ASSEMBLY,
                                full_cap=FULL_CAP,compact_cap=COMPACT_CAP),
        'source_eboot_sha256':sha(raw),'allowed_changes':[list(c) for c in changes]})
    print(json.dumps(meta,indent=2))


if __name__=='__main__':build()
