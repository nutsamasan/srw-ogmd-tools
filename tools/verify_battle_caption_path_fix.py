"""Execute the discovered battle caller, measure its text and inspect glyph quads."""
import json
import struct
from build_battle_caption_path_fix import ROOT,BASE,OUT,HOOK,FULL_CAP,COMPACT_CAP
import verify_battle_text_fit as old
from diagnose_battle_fit import FONT,TEXT
from trace_battle_glyphs import trace
from core import NativeMetrics,atomic_json
from native_eboot import sha
from build_ogmd_native_eboot import file_offset
from verify_ogmd_spacing_patch import snapshot
from capstone import Cs,CS_ARCH_PPC,CS_MODE_64,CS_MODE_BIG_ENDIAN
from unicorn import UC_HOOK_CODE
import unicorn.ppc_const as p

PARENT=0x2200000
RETURN=0x10008
ENTRY=0x106dfc


def run(elf,text=TEXT,compact=False,index=0,origin_x=0,cached=-1,name='Azuki'):
    previous=old.ELF;old.ELF=elf
    try:vm=old.vm_init(343,(-1,-1,-1))
    finally:old.ELF=previous
    vm.mem_map(PARENT,0x10000)
    font=bytearray((ROOT/'script_editor/assets/font.bin').read_bytes())
    for page in range(256):
        at=0x54+page*4;value=struct.unpack_from('>I',font,at)[0]
        if value:struct.pack_into('>I',font,at,FONT+value)
    vm.mem_map(FONT,(len(font)+4095)&~4095);vm.mem_write(FONT,bytes(font))
    for obj in old.FONTS:
        vm.mem_write(obj+0x18,struct.pack('>I',FONT))
        vm.mem_write(obj+0xfc,struct.pack('>f',cached))
    vm.mem_write(PARENT,struct.pack('>I',old.OBJ))
    vm.mem_write(PARENT+0x8000,text.encode('utf8')+b'\0')
    vm.mem_write(PARENT+0x9000,name.encode('utf8')+b'\0')
    vm.mem_write(PARENT+0x6740+index*4,struct.pack('>I',PARENT+0x9000))
    vm.mem_write(PARENT+0x6748+index*4,struct.pack('>I',PARENT+0x8000))
    for reg,value in ((3,PARENT),(4,index),(5,origin_x),(6,423 if compact else 504),(8,int(compact))):
        vm.reg_write(p.UC_PPC_REG_0+reg,value)
    vm.reg_write(p.UC_PPC_REG_FPR1,old.bits(1))
    vm.reg_write(p.UC_PPC_REG_LR,RETURN)
    before=snapshot(vm)
    decoder=Cs(CS_ARCH_PPC,CS_MODE_64|CS_MODE_BIG_ENDIAN);decoder.skipdata=True
    ops={}
    for a,b in ((ENTRY,0x107240),(0x23e318,0x23e4a4)):
        for i in decoder.disasm(elf[file_offset(elf,a):file_offset(elf,b)],a):
            word=int.from_bytes(i.bytes,'big')
            op=i.mnemonic
            if word>>26==31 and (word>>1)&1023==519:op='lvlx'
            if op in ('vxor','lvx','stvx','lvlx','vspltw'):ops[i.address]=(op,word)
    vectors={};draws=[];hook_hits=[]
    def cstring(ptr,maximum=1024):
        result=bytearray()
        for off in range(maximum):
            b=vm.mem_read(ptr+off,1)
            if b==b'\0':return bytes(result)
            result.extend(b)
        raise AssertionError('Unterminated test input')
    def callback(vm,addr,size,_):
        if addr==HOOK:
            hook_hits.append(dict(mode=vm.reg_read(p.UC_PPC_REG_26),object=vm.reg_read(p.UC_PPC_REG_31)))
        if addr in ops:
            op,word=ops[addr];vd,ra,rb=(word>>21)&31,(word>>16)&31,(word>>11)&31
            if op=='vxor':vectors[vd]=bytes(a^b for a,b in zip(vectors.get(ra,bytes(16)),vectors.get(rb,bytes(16))))
            elif op=='vspltw':
                value=vectors.get(rb,bytes(16));vectors[vd]=value[(ra&3)*4:(ra&3)*4+4]*4
            else:
                ea=(vm.reg_read(p.UC_PPC_REG_0+ra) if ra else 0)+vm.reg_read(p.UC_PPC_REG_0+rb)
                if op=='lvlx':vectors[vd]=bytes(vm.mem_read(ea,16-(ea&15)))+bytes(ea&15)
                elif op=='lvx':vectors[vd]=bytes(vm.mem_read(ea&~15,16))
                else:vm.mem_write(ea&~15,vectors.get(vd,bytes(16)))
            vm.reg_write(p.UC_PPC_REG_PC,addr+4);return
        ret=None
        if addr in (0xb4a9b0,0xb4a980,0xb4ab30):
            sp=vm.reg_read(p.UC_PPC_REG_1)
            vm.mem_write(sp+0x28,struct.pack('>Q',old.TOC))
            r3=vm.reg_read(p.UC_PPC_REG_3);r4=vm.reg_read(p.UC_PPC_REG_4)
            if addr==0xb4a9b0:
                vm.mem_write(r3,bytes([r4&255])*vm.reg_read(p.UC_PPC_REG_5));ret=r3
            elif addr==0xb4a980:
                vm.mem_write(r3,cstring(r4)+b'\0');ret=r3
            else:
                found=cstring(r3).find(bytes([r4&255]));ret=r3+found if found>=0 else 0
        elif addr==0xb7c980:
            obj=vm.reg_read(p.UC_PPC_REG_3)
            raw=bytes(vm.mem_read(obj,0x170))
            line=cstring(vm.reg_read(p.UC_PPC_REG_4)).decode('utf8')
            cell=struct.unpack_from('>f',raw,0x48)[0]
            cap=struct.unpack_from('>i',raw,0x50)[0]
            width=struct.unpack_from('>f',raw,0xfc)[0]
            x=old.number(vm.reg_read(p.UC_PPC_REG_FPR1));y=old.number(vm.reg_read(p.UC_PPC_REG_FPR2))
            glyphs=trace(line,cell,cap,width,elf=elf,unbounded=True,x=x,y=y,font_object=raw)
            draws.append(dict(text=line,x=x,y=y,cell=cell,cap=cap,cached=width,
                advance=glyphs['advance'],right=max([x]+[max(q) for q in glyphs['quads']]),
                glyph_count=len(glyphs['quads'])))
            ret=0
        if ret is not None:
            vm.reg_write(p.UC_PPC_REG_3,ret)
            vm.reg_write(p.UC_PPC_REG_PC,vm.reg_read(p.UC_PPC_REG_LR))
    vm.hook_add(UC_HOOK_CODE,callback)
    try:vm.emu_start(ENTRY,RETURN,count=1000000)
    except Exception as exc:raise RuntimeError(f'Caller PC={vm.reg_read(p.UC_PPC_REG_PC):x}') from exc
    assert vm.reg_read(p.UC_PPC_REG_PC)==RETURN
    after=snapshot(vm)
    assert after['gpr'][1]==before['gpr'][1] and after['gpr'][14:]==before['gpr'][14:]
    assert after['fpr'][14:]==before['fpr'][14:]
    assert struct.unpack('>i',vm.mem_read(old.OBJ+0x50,4))[0]==-1
    assert struct.unpack('>2f',vm.mem_read(old.OBJ+0x48,8))==(32,32)
    assert len(hook_hits)==1 and hook_hits[0]==dict(mode=int(compact),object=PARENT)
    return draws


def verify():
    elf=(OUT/'EBOOT.elf').read_bytes();base=(BASE/'EBOOT.elf').read_bytes()
    metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    cases=[]
    for compact in (False,True):
        for text in (TEXT,'Short line','W'*100,'I'*120,"'"*90,TEXT+'/Second short line/'+"I'm "*50,'「短い日本語」',''):
            for index in (0,1):
                draws=run(elf,text,compact,index)
                captions=draws if compact else draws[1:]
                cap=COMPACT_CAP if compact else FULL_CAP
                cell=20 if compact else 28
                x=392 if compact else 343
                y=428 if compact else 576
                pitch=20 if compact else 32
                if not compact:assert draws[0]['text']=='Azuki' and draws[0]['cap']==-1
                for i,(line,d) in enumerate(zip(text.split('/'),captions)):
                    assert (d['text'],d['x'],d['y'],d['cell'],d['cap'])==(line,x,y+pitch*i,cell,cap)
                    natural=metrics.width(line,cell)
                    assert abs(d['cached']-natural)<0.003
                    assert abs(d['advance']-min(natural,cap))<0.003
                    assert d['right']<=x+(744 if compact else 793)+0.003,(line,d)
                assert len(captions)==len(text.split('/'))
                cases.append(dict(compact=compact,index=index,text=text,draws=draws))
    # Reproduce the screenshot's overflow through the same complete caller.
    before=run(base)
    after=run(elf)
    assert abs(before[1]['right']-1199.625)<0.003
    assert abs(after[1]['right']-1111)<0.003
    assert before[0]==after[0]
    # Position changes move the box and its text together; cap stays a width.
    shifted=run(elf,origin_x=30)
    assert shifted[1]['cap']==FULL_CAP and abs(shifted[1]['right']-1141)<0.003
    atomic_json(OUT/'verification.json',dict(status='passed',native_caller_cases=len(cases)+3,
        elf_sha256=sha(elf),
        cases=cases,reported_line_before=before[1],reported_line_after=after[1],
        speaker_name_unchanged=True,font_limit_reset_on_return=True,
        nonvolatile_registers_preserved=True,source_text_preserved=True,
        limits=dict(full=FULL_CAP,compact=COMPACT_CAP),in_game_visual_test=False,
        limitations=['Native caller, font reset, font size, measurement and caption wrapper execute offline.',
          'Native glyph positioning executes in a separate VM using actual draw parameters and font state.',
          'C string library calls and GPU submission are simulated; live appearance still requires a user boot.']))
    print(f'PASS: {len(cases)+3} complete native caller cases; reported line right edge {before[1]["right"]} -> {after[1]["right"]}.')


if __name__=='__main__':verify()
