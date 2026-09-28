"""Regression: actual caption measurement followed by native shrink selection."""
import json
import math
import struct
from pathlib import Path
from diagnose_battle_fit import ROOT, TEXT, run, old, p
from build_battle_fit_cache_fix import OUT, HOOKS
from core import NativeMetrics, atomic_json
from unicorn import UC_HOOK_CODE


def renderer_scale(draw, cell):
    """Execute the renderer's original cap comparison and shrink setup."""
    vm = old.vm_init(draw['x'],(draw['limit'],)*3)
    vm.reg_write(p.UC_PPC_REG_31,old.OBJ)
    vm.reg_write(p.UC_PPC_REG_FPR0+27,old.bits(cell/32))
    vm.mem_write(old.OBJ+0xfc,struct.pack('>f',draw['cached']))
    vm.mem_write(old.OBJ+0x48,struct.pack('>ff',cell,cell))
    vm.mem_write(old.TOC-0x5210,struct.pack('>I',old.OBJ+0x9000))
    def stub(vm,addr,size,_):
        if addr==0x34ca78:
            vm.reg_write(p.UC_PPC_REG_3,0)
            vm.reg_write(p.UC_PPC_REG_PC,vm.reg_read(p.UC_PPC_REG_LR))
    vm.hook_add(UC_HOOK_CODE,stub)
    vm.emu_start(0xb7a40c,0xb7a444,count=1000)
    assert vm.reg_read(p.UC_PPC_REG_PC)==0xb7a444
    shrunk=struct.unpack('>I',vm.mem_read(old.SP+0x12c,4))[0]
    return old.number(vm.reg_read(p.UC_PPC_REG_FPR0+27)) if shrunk else 1.0


def verify():
    elf=(OUT/'EBOOT.elf').read_bytes()
    metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    repro=[]
    for cached in (0,500,793,856.625,1000):
        before=run(cached=cached)[0]
        after=run(cached=cached,elf=elf)[0]
        natural=metrics.width(TEXT,28)
        before_right=343+natural*renderer_scale(before,28)
        after_right=343+natural*renderer_scale(after,28)
        assert after['cached']==natural and abs(after_right-1136)<.002
        repro.append(dict(initial_cached=cached,before_right=before_right,after_right=after_right))
    assert repro[-1]['before_right']>1199
    cases=[]
    sequences=[(TEXT,TEXT,TEXT),("「Go!」",TEXT,"「I'm not done yet!」"),
               ('W'*80,"「短い日本語」",TEXT),('',TEXT,''),(TEXT,'','W'*90)]
    for cell,x in ((28,343),(28,343.5),(20,392)):
        for cached in (0,856.625,2000):
            for lines in sequences:
                draws=run(elf=elf,cell=cell,x=x,cached=cached,lines=lines)
                visible=[s for s in lines if s]
                assert len(draws)==len(visible)
                for line,draw in zip(visible,draws):
                    natural=metrics.width(line,cell)
                    assert abs(draw['cached']-natural)<.002,(line,draw,natural)
                    scale=renderer_scale(draw,cell)
                    width=natural*scale
                    assert abs(width-min(natural,int(1136-x)))<.003,(line,draw,width)
                    assert x+width<=1136.003
                cases.append(dict(cell=cell,x=x,initial_cached=cached,lines=list(lines),draws=draws))
    # Each reset preserves the live registers, and the existing cap is restored.
    hook_checks=0
    prior=old.ELF
    old.ELF=elf
    try:
        for hook in HOOKS:
            vm=old.vm_init(343,(-1,902,903))
            for font in old.FONTS:vm.mem_write(font+0xfc,struct.pack('>f',999))
            before=old.snapshot(vm)
            vm.emu_start(hook,hook+4,count=300)
            assert old.snapshot(vm)==before
            assert all(bytes(vm.mem_read(font+0xfc,4))==bytes(4) for font in old.FONTS)
            hook_checks+=1
        # Reuse the finished-executable tests for caps, caller state, and all 12 VWF hooks.
        old.REPORT={'asset':json.loads((OUT/'native_eboot/assets.json').read_text())}
        old.OUT=OUT/'legacy_checks';old.OUT.mkdir(exist_ok=True)
        old.run()
    finally:old.ELF=prior
    result=dict(status='passed',reproduction=repro,wrapper_cases=len(cases),
        draw_cases=sum(len(c['draws']) for c in cases),reset_hook_checks=hook_checks,cases=cases,
        limitations=['Offline PowerPC execution; no RPCS3 screenshot yet.',
            'Font getters, strchr and final GPU submission stubbed; color-vector copies interpreted.',
            'Native formatted-text wrapper, UTF-8 measurement, cap selection and shrink setup executed.'],
        in_game_visual_test=False)
    atomic_json(OUT/'verification.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__=='__main__':verify()
