"""Rewrap the tested ELF to fit the vanilla disc EBOOT extent exactly."""
from pathlib import Path
import json,struct,sys,zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json
from native_eboot import STOCK_SHA256,TESTED_SHA256,ELF_SHA256,PPU,sha,extract_elf


def main():
    stock=(ROOT/'work/ps3_disc/PS3_GAME/USRDIR/EBOOT.BIN').read_bytes()
    tested=(ROOT/'work/poc/native_eboot_20260910_v2/EBOOT.BIN').read_bytes()
    assert sha(stock)==STOCK_SHA256 and sha(tested)==TESTED_SHA256
    elf=extract_elf(tested);assert sha(elf)==ELF_SHA256
    offset=len(stock)-len(elf)
    assert offset==0x88
    # CheckDebugSelf reads the ELF offset from +0x10; there is no 4-KiB rule.
    wrapper=bytearray(offset)
    struct.pack_into('>IIHHIQQ',wrapper,0,0x53434500,2,0x8000,1,0,offset,len(elf))
    raw=bytes(wrapper)+elf
    assert len(raw)==len(stock) and extract_elf(raw)==extract_elf(tested)
    packed=zlib.compress(raw,9)
    out=ROOT/'script_editor/assets/native_eboot';out.mkdir(parents=True,exist_ok=True)
    (out/'EBOOT.BIN.zlib').write_bytes(packed)
    atomic_json(out/'assets.json',dict(version=1,source_sha256=STOCK_SHA256,tested_self_sha256=TESTED_SHA256,
        elf_sha256=ELF_SHA256,ppu=PPU,size=len(raw),sha256=sha(raw),compressed_sha256=sha(packed),
        elf_offset=offset,rpcs3_only=True,executable_code_identical_to_user_test=True))
    print(json.dumps(dict(size=len(raw),compressed_size=len(packed),elf_offset=offset,sha256=sha(raw))))


if __name__=='__main__':main()
