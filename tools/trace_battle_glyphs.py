"""Execute native glyph positioning, recording quads before GPU submission."""
import json,struct
from diagnose_battle_fit import ROOT,FONT,TEXT,old,p
from core import NativeMetrics
from capstone import Cs,CS_ARCH_PPC,CS_MODE_64,CS_MODE_BIG_ENDIAN
from unicorn import UC_HOOK_CODE


def trace(text=TEXT,cell=28,maximum=793,cached=None,elf=None,unbounded=False,x=343,y=576,font_object=None):
    data=elf or (ROOT/'work/poc/battle_fit_cache_20260918/EBOOT.elf').read_bytes()
    previous=old.ELF;old.ELF=data
    try:vm=old.vm_init(343,(maximum,)*3)
    finally:old.ELF=previous
    metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    font=bytearray(metrics.data)
    for page in range(256):
        at=0x54+page*4;value=struct.unpack_from('>I',font,at)[0]
        if value:struct.pack_into('>I',font,at,FONT+value)
    vm.mem_map(FONT,(len(font)+4095)&~4095);vm.mem_write(FONT,bytes(font))
    vm.mem_map(0x6500000,0x10000)
    for n,off in enumerate(range(-0x5248,-0x51eb,4)):
        addr=0x6500000+n*0x100
        vm.mem_write(old.TOC+off,struct.pack('>I',addr))
        vm.mem_write(addr,struct.pack('>16f',*([0,0,0,1]*4)))
    obj=old.OBJ
    if font_object is not None:vm.mem_write(obj,bytes(font_object))
    vm.mem_write(obj+0x18,struct.pack('>I',FONT))
    vm.mem_write(obj+0x48,struct.pack('>ff',cell,cell))
    vm.mem_write(obj+0xfc,struct.pack('>f',metrics.width(text,cell) if cached is None else cached))
    if font_object is None:
        vm.mem_write(obj+0x60,struct.pack('>16f',0,0,0,1,0,cell,0,1,cell,0,0,1,cell,cell,0,1))
    encoded=text.encode('utf8');start=obj+0x4000
    vm.mem_write(start,encoded+b'\0')
    vm.mem_write(obj+0x7000,struct.pack('>I',start+len(encoded)))
    vm.mem_write(old.SP+0x13c,struct.pack('>I',start))
    vm.mem_write(old.SP+0x140,struct.pack('>Q',obj+0x7000))
    vm.mem_write(old.SP+0x148,struct.pack('>II',0,1))
    if unbounded:vm.mem_write(old.SP+0x140,struct.pack('>II',0,1))
    for reg,value in ((14,obj),(31,obj),(29,720)):vm.reg_write(p.UC_PPC_REG_0+reg,value)
    for reg,value in ((26,x),(28,y),(27,cell/32)):vm.reg_write(p.UC_PPC_REG_FPR0+reg,old.bits(value))
    decoder=Cs(CS_ARCH_PPC,CS_MODE_64|CS_MODE_BIG_ENDIAN);decoder.skipdata=True
    ops={i.address:(i.mnemonic,int.from_bytes(i.bytes,'big')) for i in decoder.disasm(
        data[old.file_offset(data,0xb7a198):old.file_offset(data,0xb7f154)],0xb7a198)
        if i.mnemonic in ('vxor','lvx','stvx')}
    vectors={};quads=[];advances=[];hooks=[]
    def callback(vm,addr,size,_):
        if addr in ops:
            op,word=ops[addr];vd,ra,rb=(word>>21)&31,(word>>16)&31,(word>>11)&31
            if op=='vxor':vectors[vd]=bytes(a^b for a,b in zip(vectors.get(ra,bytes(16)),vectors.get(rb,bytes(16))))
            else:
                ea=((vm.reg_read(p.UC_PPC_REG_0+ra) if ra else 0)+vm.reg_read(p.UC_PPC_REG_0+rb))&~15
                if op=='lvx':vectors[vd]=bytes(vm.mem_read(ea,16))
                else:vm.mem_write(ea,vectors.get(vd,bytes(16)))
            vm.reg_write(p.UC_PPC_REG_PC,addr+4)
        elif addr==0x34ca78:
            vm.reg_write(p.UC_PPC_REG_3,0);vm.reg_write(p.UC_PPC_REG_PC,vm.reg_read(p.UC_PPC_REG_LR))
        elif addr==0xb79e78:
            pts=vm.reg_read(p.UC_PPC_REG_4)
            values=struct.unpack('>16f',vm.mem_read(pts,64))
            quads.append(list(values[::4]))
            vm.reg_write(p.UC_PPC_REG_PC,vm.reg_read(p.UC_PPC_REG_LR))
        elif addr==0xb7b84c:
            advances.append(old.number(vm.reg_read(p.UC_PPC_REG_FPR0+30)))
        elif addr in (0xb7c81c,0xb7ba14,0xb7b848):
            sp=vm.reg_read(p.UC_PPC_REG_1)
            cls=struct.unpack('>I',vm.mem_read(sp+0x134,4))[0]
            index=struct.unpack('>I',vm.mem_read(sp+0x100,4))[0]
            hooks.append(dict(address=hex(addr),cls=cls,index=index,char=encoded[index] if index<len(encoded) else -1))
    vm.hook_add(UC_HOOK_CODE,callback)
    start,end=(0xb7cbe4,0xb7ced8) if unbounded else (0xb7a400,0xb7a6fc)
    try:vm.emu_start(start,end,count=1000000)
    except Exception as exc:raise RuntimeError(f'PC={vm.reg_read(p.UC_PPC_REG_PC):x}') from exc
    assert vm.reg_read(p.UC_PPC_REG_PC)==end
    return dict(advance=old.number(vm.reg_read(p.UC_PPC_REG_FPR0+30)),quads=quads,advances=advances,hooks=hooks)


if __name__=='__main__':
    for maximum in (-1,793,600):
        result=trace(maximum=maximum)
        print(json.dumps(dict(maximum=maximum,advance=result['advance'],last_quad=result['quads'][-1],count=len(result['quads']),hooks=result['hooks'][:5],advances=result['advances'][:5])))
