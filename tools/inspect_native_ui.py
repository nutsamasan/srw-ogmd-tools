"""Offline inspection of the pristine PS3 UI reader; never attaches to RPCS3."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'work/analysis_pydeps'))
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

ELF = ROOT / 'work/poc/text_layout_20260905/EBOOT.elf'
OUT = ROOT / 'work/poc/full_english_20260906'


def disassemble(start, end):
    data = ELF.read_bytes()
    decoder = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    decoder.skipdata = True
    return '\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}'
                     for i in decoder.disasm(data[start-0x10000:end-0x10000], start))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('start', type=lambda v: int(v, 0))
    parser.add_argument('end', type=lambda v: int(v, 0))
    parser.add_argument('--out')
    args = parser.parse_args()
    result = disassemble(args.start, args.end)
    if args.out:
        (OUT / args.out).write_text(result, encoding='utf8')
    else:
        print(result)
