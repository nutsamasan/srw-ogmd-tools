"""Stage a scoped battle-caption cap on top of the tested embedded font ELF."""
from pathlib import Path
import hashlib,json,struct,sys,zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
sys.path.insert(0,str(ROOT/'work/analysis_pydeps'))
from core import atomic_json
from native_eboot import load_asset,extract_elf,sha
from build_ogmd_native_eboot import program_headers,file_offset,branch
from keystone import Ks,KS_ARCH_PPC,KS_MODE_PPC64,KS_MODE_BIG_ENDIAN

OUT=ROOT/'work/poc/editor_v39_20260914/battle_fit'
RIGHT=1136  # Native 1280-wide frame: reserve room for glyph overhang before its inner edge.
START,END=0x11a028,0x11a128


def ppu_hash(elf):
    # RPCS3 PPUModule.cpp: hash BE type/flags, then LOAD vaddr/memsz and file bytes.
    h=hashlib.sha1()
    for p in program_headers(elf)[1]:
        h.update(struct.pack('>II',p[0],p[1]))
        if p[0]==1 and p[6]:h.update(struct.pack('>QQ',p[3],p[6]));h.update(elf[p[2]:p[2]+p[5]])
    return 'PPU-'+h.hexdigest()


def main():
    baseline=OUT.parent/'backups/native_eboot'
    if not baseline.exists():baseline=ROOT/'script_editor/assets/native_eboot'
    info,raw=load_asset(baseline);elf=extract_elf(raw)
    assert ppu_hash(elf)==info['ppu']
    OUT.mkdir(exist_ok=True)
    before='''stdu 1,-96(1)
std 0,16(1)
std 11,24(1)
std 12,32(1)
stfd 0,40(1)
mffs 0
stfd 0,48(1)
lis 0,17550
stw 0,56(1)
lfs 0,56(1)
fsubs 0,0,27
fctiwz 0,0
stfd 0,56(1)
lwz 11,60(1)
stw 3,284(1)
lwz 0,80(3)
stw 0,280(1)
stw 11,80(3)
lwz 12,12(3)
lwz 0,80(12)
stw 0,272(1)
stw 11,80(12)
lwz 12,16(3)
lwz 0,80(12)
stw 0,276(1)
stw 11,80(12)
lfd 0,48(1)
mtfsf 255,0
lfd 0,40(1)
ld 0,16(1)
ld 11,24(1)
ld 12,32(1)
addi 1,1,96'''
    assert struct.unpack('>f',struct.pack('>I',17550<<16))[0]==RIGHT
    after='''stdu 1,-64(1)
std 0,16(1)
std 11,24(1)
std 12,32(1)
lwz 12,252(1)
lwz 0,248(1)
stw 0,80(12)
lwz 11,12(12)
lwz 0,240(1)
stw 0,80(11)
lwz 11,16(12)
lwz 0,244(1)
stw 0,80(11)
ld 0,16(1)
ld 11,24(1)
ld 12,32(1)
addi 1,1,64'''
    header,segments=program_headers(elf);segment=segments[0]
    cursor=segment[2]+segment[5];assert cursor%16==0
    sections=[struct.unpack_from('>IIQQQQIIQQ',elf,header[6]+i*header[11]) for i in range(header[12])]
    section=sections[-1];assert section[1:3]==(1,6) and section[4]+section[5]<=cursor
    ks=Ks(KS_ARCH_PPC,KS_MODE_PPC64|KS_MODE_BIG_ENDIAN);result=bytearray(elf);hooks=[];allowed=[]
    for hook,assembly in [(START,before),(END,after)]:
        address=segment[3]+cursor-segment[2];offset=file_offset(elf,hook)
        assert elf[offset:offset+4]==bytes.fromhex('60000000')
        code=bytes(ks.asm(assembly,address)[0]);payload=code+branch(address+len(code),hook+4)
        assert not any(elf[cursor:cursor+len(payload)]) and cursor+len(payload)<segments[1][2]
        result[cursor:cursor+len(payload)]=payload;result[offset:offset+4]=branch(hook,address)
        allowed.extend([(offset,4),(cursor,len(payload))])
        hooks.append(dict(address=hook,payload_address=address,offset=cursor,size=len(payload),assembly=assembly))
        cursor=(cursor+len(payload)+15)&~15
    struct.pack_into('>QQ',result,header[5]+32,cursor-segment[2],cursor-segment[2]);allowed.append((header[5]+32,16))
    section_size=header[6]+(header[12]-1)*header[11]+32
    struct.pack_into('>Q',result,section_size,cursor-section[4]);allowed.append((section_size,8))
    mask=bytearray(len(elf))
    for at,size in allowed:mask[at:at+size]=b'\1'*size
    assert len(result)==len(elf) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(elf,result)))
    patched=raw[:info['elf_offset']]+result;packed=zlib.compress(patched,9)
    (OUT/'EBOOT.elf').write_bytes(result);(OUT/'EBOOT.BIN').write_bytes(patched)
    assets=OUT/'native_eboot';assets.mkdir(exist_ok=True);(assets/'EBOOT.BIN.zlib').write_bytes(packed)
    meta={**info,'elf_sha256':sha(result),'ppu':ppu_hash(result),'sha256':sha(patched),'compressed_sha256':sha(packed),
        'executable_code_identical_to_user_test':False,'font_code_identical_to_user_test':True,'battle_text_right_edge':RIGHT,
        'battle_fit_visual_tested':False,'previous_elf_sha256':info['elf_sha256'],'previous_eboot_sha256':info['sha256']}
    atomic_json(assets/'assets.json',meta)
    atomic_json(OUT/'build.json',dict(status='built; offline execution pending',hooks=hooks,allowed_changes=[list(x) for x in allowed],
        baseline=info,asset=meta,source_preserved=True,main_dialogue_and_backlog_unchanged=True,
        ppu_hash_source='https://github.com/RPCS3/rpcs3/blob/master/rpcs3/Emu/Cell/PPUModule.cpp'))
    print(json.dumps(meta,indent=2))


if __name__=='__main__':main()
