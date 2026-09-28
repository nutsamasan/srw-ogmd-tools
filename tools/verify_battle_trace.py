"""Execute the diagnostic hooks and check bounded logging and preserved state."""
import json
import struct
from build_battle_trace import ROOT, OUT, SOURCE, HOOKS, MATCH_OFFSET
import verify_battle_text_fit as old
from verify_ogmd_spacing_patch import snapshot
from diagnose_battle_fit import run, TEXT
from core import atomic_json
from read_battle_trace import decode_record
from unicorn import UC_HOOK_MEM_WRITE
import unicorn.ppc_const as p


def verify():
    elf = (OUT/'EBOOT.elf').read_bytes()
    report = json.loads((OUT/'build.json').read_text(encoding='utf8'))
    previous = old.ELF
    old.ELF = elf
    checks = 0
    try:
        for meta in report['hooks']:
            hook, bank = meta['address'], meta['bank']
            vm = old.vm_init(343,(-1,-1,-1))
            text = old.OBJ+0x4000
            vm.mem_write(text,TEXT.encode('utf8')+b'\0')
            vm.reg_write(p.UC_PPC_REG_4,text)
            if hook == 0xb7a198:
                vm.reg_write(p.UC_PPC_REG_5,old.OBJ+0x6000)
                vm.mem_write(old.OBJ+0x6000,struct.pack('>I',text+len(TEXT.encode('utf8'))))
            vm.reg_write(p.UC_PPC_REG_8,1)
            vm.reg_write(p.UC_PPC_REG_9,0xffffffff)
            vm.reg_write(p.UC_PPC_REG_FPR1,old.bits(343))
            vm.reg_write(p.UC_PPC_REG_FPR2,old.bits(576))
            vm.mem_write(old.OBJ+0x48,struct.pack('>ff',28,28))
            vm.mem_write(old.OBJ+0xfc,struct.pack('>f',856.625))
            memory = bytes(vm.mem_read(old.OBJ,0x10000))
            before = snapshot(vm)
            flags = {r:vm.reg_read(r) for r in (p.UC_PPC_REG_CR,p.UC_PPC_REG_LR,
                     p.UC_PPC_REG_CTR,p.UC_PPC_REG_XER,p.UC_PPC_REG_FPSCR)}
            writes = []
            vm.hook_add(UC_HOOK_MEM_WRITE,lambda _v,_a,address,size,_value,_user:writes.append((address,size)))
            vm.emu_start(hook,hook+4,count=10000)
            after = snapshot(vm)
            expected = {k:list(v) if isinstance(v,list) else v for k,v in before.items()}
            if hook == 0x247574:
                expected['gpr'][12] = flags[p.UC_PPC_REG_CR]
            else:
                expected['gpr'][1] -= 0x410 if hook==0xb7a198 else 0x400
            assert after == expected,(hex(hook),[(k,after[k],expected[k]) for k in after if after[k]!=expected[k]])
            assert all(vm.reg_read(r)==v for r,v in flags.items())
            assert bytes(vm.mem_read(old.OBJ,0x10000)) == memory
            assert all(bank<=a and a+n<=bank+0x10000 or old.STACK<=a and a+n<=old.STACK+0x10000 for a,n in writes)
            slot = bytes(vm.mem_read(bank+0x100,256))
            assert struct.unpack_from('>3I',slot) == (0x12345678,1,hook)
            assert struct.unpack_from('>2f',slot,32) == (343,576)
            assert struct.unpack_from('>2fif',slot,44) == (28,28,-1,856.625)
            assert slot[64:].split(b'\0',1)[0].decode('utf8') == TEXT
            decoded=decode_record(slot)
            assert (decoded['text'],decoded['x'],decoded['y'],decoded['cap'],decoded['cached_width'])==(TEXT,343,576,-1,856.625)
            assert decoded['arguments']['r5']==hex(vm.reg_read(p.UC_PPC_REG_5)&0xffffffff)
            assert bytes(vm.mem_read(bank+MATCH_OFFSET,256)) == slot
            checks += 1
            # Later text can replace the call-site record, never the retained match.
            vm.reg_write(p.UC_PPC_REG_1,old.SP)
            vm.mem_write(text,b'Another caption\0')
            vm.emu_start(hook,hook+4,count=10000)
            assert bytes(vm.mem_read(bank+MATCH_OFFSET,256)) == slot
            assert bytes(vm.mem_read(bank+0x140,16)) == b'Another caption\0'
            checks += 1
            # A full table drops new call sites without writing beyond its bank.
            for i in range(128):vm.mem_write(bank+0x100+i*256,struct.pack('>I',0x1000+i*4))
            vm.reg_write(p.UC_PPC_REG_1,old.SP)
            vm.emu_start(hook,hook+4,count=10000)
            assert struct.unpack('>I',vm.mem_read(bank+4,4))[0] == 1
            assert bytes(vm.mem_read(bank+MATCH_OFFSET,256)) == slot
            checks += 1
            for value in (b'',b'x'*600):
                vm.mem_write(bank+0x100,bytes(256))
                vm.mem_write(text,value+b'\0')
                if hook == 0xb7a198:
                    vm.mem_write(old.OBJ+0x6000,struct.pack('>I',text+len(value)))
                vm.reg_write(p.UC_PPC_REG_1,old.SP)
                vm.emu_start(hook,hook+4,count=10000)
                rec=bytes(vm.mem_read(bank+0x100,256))
                assert rec[64:224].split(b'\0',1)[0] == value[:159]
                checks += 1
            if hook == 0xb7a198:
                # The span ends at an unmapped page, with no NUL available.
                page=0x7000000
                vm.mem_map(page,4096)
                vm.mem_write(page+4091,b'ABCDE')
                vm.mem_write(old.OBJ+0x6000,struct.pack('>I',page+4096))
                for start,expected_text in ((page+4091,b'ABCDE'),(page+4096,b'')):
                    vm.mem_write(bank+0x100,bytes(256))
                    vm.reg_write(p.UC_PPC_REG_4,start)
                    vm.reg_write(p.UC_PPC_REG_1,old.SP)
                    vm.emu_start(hook,hook+4,count=10000)
                    rec=bytes(vm.mem_read(bank+0x100,256))
                    assert rec[64:224].split(b'\0',1)[0]==expected_text
                    checks+=1
        # The real wrapper follows its original fitting path with tracing enabled.
        wrapper_cases = 0
        baseline = (SOURCE/'EBOOT.elf').read_bytes()
        for text in (TEXT,'Short line','W'*100,'「短い日本語」'):
            for cached in (0,856.625,1000):
                assert run(text=text,cached=cached,elf=elf)==run(text=text,cached=cached,elf=baseline)
                wrapper_cases += 1
        atomic_json(OUT/'verification.json',dict(status='passed',hook_cases=checks,
            actual_wrapper_cases=wrapper_cases,registers_and_flags_preserved=True,
            text_and_font_objects_unchanged=True,logging_bounded=True,
            reported_caption_retained=True,visual_fix_claimed=False,
            limitations=['Offline PPC execution; GPU submission and selected native services stubbed.',
                         'A fresh user-started run is required to capture the actual caption path.']))
        print(f'PASS: {checks} hook cases; {wrapper_cases} real wrapper comparisons.')
    finally: old.ELF=previous


if __name__=='__main__':verify()
