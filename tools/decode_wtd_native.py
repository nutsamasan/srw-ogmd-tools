"""Execute the stock serialized UI readers offline, with allocation stubs only."""
from pathlib import Path
import json
import struct
import sys
from collections import Counter, deque
from inspect_native_ui import disassemble

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'work/analysis_pydeps'))
from unicorn import Uc, UC_ARCH_PPC, UC_MODE_PPC64, UC_MODE_BIG_ENDIAN, UC_TLB_VIRTUAL, UC_HOOK_CODE
import unicorn.ppc_const as ppc

OUT = ROOT/'work/poc/full_english_20260906'
WTD_PATH = OUT/'native_ui/General2d/Dat/Window/WindowToolData/windowdataMain.wtd'
BASE, HEAP, STACK, SP, STOP, OBJ, CONTEXT = 0x6000000, 0x8000000, 0x5000000, 0x5080000, 0x5000000, 0x5100000, 0x5110000
TOC = 0xEEDC64


class Decoder:
    def __init__(self, data):
        self.data = data
        self.vm = v = Uc(UC_ARCH_PPC, UC_MODE_PPC64 | UC_MODE_BIG_ENDIAN)
        v.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
        v.mem_map(0x10000, 0x1800000)
        v.mem_write(0x10000, (ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes())
        for addr, size in [(STACK,0x100000),(OBJ,0x100000),(BASE,0x800000),(HEAP,0x4000000)]:
            v.mem_map(addr,size)
        v.mem_write(BASE,data)
        v.reg_write(ppc.UC_PPC_REG_MSR,0x8000000000002000)
        self.heap = HEAP
        self.properties=[]
        self.objects=[]
        self.groups=[]
        self.pending=[]
        self.trace=deque(maxlen=20)
        self.calls=Counter()
        self.vectors=[bytes(16) for _ in range(32)]
        self.vector_ops={}
        for line in disassemble(0xA60000,0xA90000).splitlines():
            pc,mn,args=line.split(' ',2)
            if mn in ('vxor','lvx','stvx'):
                self.vector_ops[int(pc,16)]=(mn,[int(x.strip().lstrip('vr')) for x in args.split(',')])
        # Stock property arrays use this existing allocator singleton.
        ptr=self.u32(TOC-0x66e0)
        self.word(ptr, CONTEXT+0x8000)
        v.hook_add(UC_HOOK_CODE,self.hook)

    def reg(self,n): return self.vm.reg_read(ppc.UC_PPC_REG_0+n)
    def setreg(self,n,value): self.vm.reg_write(ppc.UC_PPC_REG_0+n,value)
    def u32(self,p): return int.from_bytes(self.vm.mem_read(p,4),'big')
    def word(self,p,n): self.vm.mem_write(p,struct.pack('>I',n))
    def ret(self,value=None):
        if value is not None: self.setreg(3,value)
        self.vm.reg_write(ppc.UC_PPC_REG_PC,self.vm.reg_read(ppc.UC_PPC_REG_LR))

    def hook(self,v,pc,size,_):
        self.trace.append(pc)
        if pc in self.vector_ops:
            mn,(a,b,c)=self.vector_ops[pc]
            if mn=='vxor': self.vectors[a]=bytes(x^y for x,y in zip(self.vectors[b],self.vectors[c]))
            else:
                address=((self.reg(b) if b else 0)+self.reg(c))&~15
                if mn=='lvx': self.vectors[a]=bytes(v.mem_read(address,16))
                else: v.mem_write(address,self.vectors[a])
            v.reg_write(ppc.UC_PPC_REG_PC,pc+4)
            return
        if pc in (0xB4DED0,0xB4E050):
            amount=self.reg(3 if pc==0xB4DED0 else 5)
            assert 0<amount<0x1000000, (hex(pc),amount)
            addr=self.heap
            self.heap += (amount+31)&~31
            assert self.heap<HEAP+0x4000000
            # External thunks save r2 for their caller.
            v.mem_write(self.reg(1)+0x28,struct.pack('>Q',self.reg(2)))
            self.calls[hex(pc)]+=1
            self.ret(addr)
        elif pc==0xB4DEC0 or pc==0xB4E030:
            v.mem_write(self.reg(1)+0x28,struct.pack('>Q',self.reg(2)))
            self.ret()
        elif pc==0xA743A4:
            self.objects.append(dict(offset=self.reg(4)-BASE,object=self.reg(3),version=self.reg(5)))
        elif pc==0xA63DE8:
            self.groups.append(dict(offset=self.reg(4)-BASE,object=self.reg(3)))
        elif pc==0xA7087C:
            self.pending.append((v.reg_read(ppc.UC_PPC_REG_LR),self.reg(3),self.reg(4)))
        elif self.pending and pc==self.pending[-1][0]:
            _,output,start=self.pending.pop()
            self.properties.append(dict(offset=start-BASE,end=self.reg(3)-BASE,
                flags=self.u32(output),text=self.u32(output+0x30)-BASE if self.u32(output+0x30) else None,
                value=bytes(v.mem_read(output,0x60)).hex()))
        elif not (0xA60000<=pc<0xA90000 or pc==STOP):
            raise RuntimeError(f'Unstubbed code {pc:x}; lr={v.reg_read(ppc.UC_PPC_REG_LR):x}; regs={[hex(self.reg(i)) for i in range(3,10)]}')

    def window(self,offset):
        v=self.vm
        v.mem_write(OBJ,bytes(0x240))
        for n,value in [(1,SP),(2,TOC),(3,OBJ),(4,BASE+offset),(5,16),(6,CONTEXT),(7,CONTEXT+0x1000),(8,CONTEXT+0x2000),(9,CONTEXT+0x3000)]:
            self.setreg(n,value)
        v.reg_write(ppc.UC_PPC_REG_LR,STOP)
        v.emu_start(0xA8596C,STOP,count=3000000)
        assert v.reg_read(ppc.UC_PPC_REG_PC)==STOP
        return self.reg(3)-BASE


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--count',type=int,default=403)
    args=p.parse_args()
    data=WTD_PATH.read_bytes()
    dec=Decoder(data)
    offset=0x718
    windows=[]
    try:
        for i in range(args.count):
            size=int.from_bytes(data[offset:offset+4],'big')
            actual=dec.window(offset)
            assert actual==offset+size,(i,hex(offset),hex(actual),hex(offset+size))
            windows.append(dict(index=i,offset=offset,size=size,decoded_end=actual))
            offset=actual
    except Exception:
        print('window',len(windows),'trace',list(map(hex,dec.trace)))
        raise
    report=dict(windows=windows,groups=dec.groups,objects=dec.objects,properties=dec.properties,allocations=dec.calls)
    (OUT/'wtd_native_decode.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(windows=len(windows),end=offset,groups=len(dec.groups),objects=len(dec.objects),properties=len(dec.properties),texts=sum(x['text'] is not None for x in dec.properties),allocations=dec.calls)))


if __name__=='__main__': main()
