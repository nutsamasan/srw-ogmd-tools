"""Read-only PS4 SELF code/string inspection for localization mapping."""
from pathlib import Path
import argparse
import re
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work/analysis_pydeps'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_64

DATA=(ROOT/'work/ps4_base/CUSA04713/eboot.bin').read_bytes()
CODE=DATA[0x7b90:0x7b90+0xe50fd4]

def offset(va):
    if 0<=va<0xe50fd4:return va+0x7b90
    if 0xe54000<=va<0xea4d30:return va-0xe54000+0xe58e10
    raise ValueError(hex(va))

def string(va):
    start=offset(va)
    return DATA[start:DATA.index(0,start)].decode('utf8')

def disassemble(start,end):
    return '\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in Cs(CS_ARCH_X86,CS_MODE_64).disasm(CODE[start:end],start))

def calls(target):
    return [m.start() for m in re.finditer(rb'\xe8....',CODE,re.S) if m.start()+5+struct.unpack_from('<i',m[0],1)[0]==target]

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['disasm','string','calls'])
    p.add_argument('start',type=lambda v:int(v,0))
    p.add_argument('end',nargs='?',type=lambda v:int(v,0))
    a=p.parse_args()
    if a.mode=='disasm':print(disassemble(a.start,a.end))
    elif a.mode=='string':print(repr(string(a.start)))
    else:print([hex(x) for x in calls(a.start)])
