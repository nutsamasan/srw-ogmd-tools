"""Execute the finished battle hooks and all three caption call sites offline."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script_editor'),str(ROOT/'work/analysis_pydeps')]
from build_battle_text_fit import OUT,START,END,RIGHT,ppu_hash
from build_ogmd_native_eboot import program_headers,file_offset
from core import atomic_json,NativeMetrics
from unicorn import Uc,UC_ARCH_PPC,UC_MODE_PPC64,UC_MODE_BIG_ENDIAN,UC_TLB_VIRTUAL,UC_HOOK_CODE
import unicorn.ppc_const as p
from verify_ogmd_spacing_patch import bits,number,snapshot
import verify_ogmd_line_measurement as lines
import build_ogmd_apostrophe_patch as v3

ELF=(OUT/'EBOOT.elf').read_bytes()
REPORT=json.loads((OUT/'build.json').read_text())
STACK=0x2000000;SP=STACK+0x8000;OBJ=0x2100000;FONTS=(OBJ,OBJ+0x1000,OBJ+0x2000)
TOC=0xeddc88

def vm_init(x,caps):
    vm=Uc(UC_ARCH_PPC,UC_MODE_PPC64|UC_MODE_BIG_ENDIAN);vm.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
    for s in program_headers(ELF)[1]:
        if s[0]!=1 or not s[6]:continue
        start=s[3]&~0xfff;size=(s[3]+s[6]+0xfff&~0xfff)-start
        vm.mem_map(start,size);vm.mem_write(s[3],ELF[s[2]:s[2]+s[5]])
    vm.mem_map(STACK,0x10000);vm.mem_map(OBJ,0x10000)
    vm.reg_write(p.UC_PPC_REG_MSR,0x8000000000002000)
    for i in range(32):
        vm.reg_write(p.UC_PPC_REG_0+i,0x1122334400000000+i)
        vm.reg_write(p.UC_PPC_REG_FPR0+i,bits(i+0.125))
    for reg,value in [(1,SP),(2,TOC),(3,OBJ),(25,OBJ+0x8000),(26,OBJ),(27,1),(28,0),(30,OBJ+0x8000)]:vm.reg_write(p.UC_PPC_REG_0+reg,value)
    for reg,value in [(26,576),(27,x),(29,32)]:vm.reg_write(p.UC_PPC_REG_FPR0+reg,bits(value))
    for addr,value in [(OBJ+12,FONTS[1]),(OBJ+16,FONTS[2]),(OBJ+0x8000,OBJ)]+[(font+0x50,cap&0xffffffff) for font,cap in zip(FONTS,caps)]:vm.mem_write(addr,struct.pack('>I',value))
    vm.reg_write(p.UC_PPC_REG_LR,0x12345678)
    return vm

def cap_values(vm):return [struct.unpack('>i',vm.mem_read(f+0x50,4))[0] for f in FONTS]

def run():
    executions=0;draw_cases=[]
    for x in (343,392,343.5):
        for caps in ((-1,-1,-1),(901,902,903),(0,1,0)):
            vm=vm_init(x,caps);before=snapshot(vm);fpscr=vm.reg_read(p.UC_PPC_REG_FPSCR)
            vm.emu_start(START,START+4,count=200)
            assert vm.reg_read(p.UC_PPC_REG_PC)==START+4
            assert snapshot(vm)==before and vm.reg_read(p.UC_PPC_REG_FPSCR)==fpscr
            assert cap_values(vm)==[int(RIGHT-x)]*3
            before=snapshot(vm);vm.emu_start(END,END+4,count=200)
            assert snapshot(vm)==before and cap_values(vm)==list(caps)
            executions+=2
            vm=vm_init(x,caps);draws=[]
            def stub(vm,addr,size,_):
                if addr in (0x3326ec,0x32dd18):vm.reg_write(p.UC_PPC_REG_3,OBJ)
                elif addr==0x247574:
                    draws.append(dict(text_pointer=vm.reg_read(p.UC_PPC_REG_4),x=number(vm.reg_read(p.UC_PPC_REG_FPR1)),y=number(vm.reg_read(p.UC_PPC_REG_FPR2)),limits=cap_values(vm)))
                    # A real callee can use volatile registers and its own full frame.
                    for i in (0,3,4,5,6,7,8,9,10,11,12):vm.reg_write(p.UC_PPC_REG_0+i,0xdeadbeef)
                else:return
                vm.reg_write(p.UC_PPC_REG_PC,vm.reg_read(p.UC_PPC_REG_LR))
            vm.hook_add(UC_HOOK_CODE,stub)
            vm.emu_start(START,END+4,count=2000)
            assert vm.reg_read(p.UC_PPC_REG_PC)==END+4 and cap_values(vm)==list(caps)
            assert [d['text_pointer'] for d in draws]==[OBJ+n for n in (0x3fec,0x41ec,0x43ec)]
            assert [d['y'] for d in draws]==[576,608,640]
            assert all(d['x']==x and d['limits']==[int(RIGHT-x)]*3 for d in draws)
            draw_cases.append(dict(x=x,original_limits=list(caps),draws=draws));executions+=1
    # Read all 12 previous hook branches and payloads from this finished ELF.
    previous=json.loads((ROOT/'work/poc/native_eboot_20260910_v2/build_report.json').read_text())
    segment=program_headers(ELF)[1][0];page=previous['hooks'][0]['code_address']&~0xffff
    tail=ELF[file_offset(ELF,page):segment[2]+segment[5]]
    class EmbeddedVM:
        def __init__(self,*args):self.vm=Uc(*args)
        def __getattr__(self,k):return getattr(self.vm,k)
        def mem_map(self,address,size,*args):
            if address!=0x1200000:return self.vm.mem_map(address,size,*args)
        def mem_write(self,address,data):
            if not 0x1200000<=address<0x1300000:return self.vm.mem_write(address,data)
        def emu_start(self,*args,**kwargs):
            self.vm.mem_map(page,0x10000);self.vm.mem_write(page,tail)
            for h in previous['hooks']:self.vm.mem_write(h['hook_address'],ELF[h['hook_file_offset']:h['hook_file_offset']+4])
            return self.vm.emu_start(*args,**kwargs)
    lines.compile_hooks=v3.compile_hooks;lines.Uc=EmbeddedVM
    metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    texts=["「I don't know where it belongs to!But I won't let you interfere",'　with that Super Robot!」','「短い日本語」','W'*100,'',"I'm "*100]
    measurements=[]
    for cell,x in ((28,343),(20,392)):
        for text in texts:
            natural=metrics.width(text,cell);maximum=int(RIGHT-x)
            for entry in (0xb7f808,0xb7fc20):
                actual=lines.measure(text,entry,'embedded',cell=cell,maximum=maximum,cached=natural)
                assert abs(actual-min(natural,maximum))<.002,(text,actual,natural)
                measurements.append(dict(cell=cell,text=text,natural=natural,maximum=maximum,actual=actual))
    assert ppu_hash(ELF)==REPORT['asset']['ppu']
    atomic_json(OUT/'verification.json',dict(status='passed',hook_and_caller_executions=executions,measurement_executions=len(measurements),draw_cases=draw_cases,measurements=measurements,
        elf_sha256=REPORT['asset']['elf_sha256'],font_code_preserved=True,limits_restored=True,
        limitations=['Offline PPC64 execution; font getters and renderer boundary stubbed for caller tests','Native width and shrink routines executed separately','Fresh RPCS3 battle visual check pending']))
    print(f'PASS: {executions} hook/caller executions; {len(measurements)} finished-ELF measurement executions')

if __name__=='__main__':run()
