"""Offline sanity checks and shader/FIFO-memory inspection of preserved states."""
import json
import struct
from pathlib import Path
import numpy as np
from inspect_savestate_vm import State

ROOT=(Path(__file__).resolve().parents[1] / 'work/investigation_title_20260904')

for index in range(3):
    state=State(ROOT/'savestates'/f'BLJS10335_1_{index}.SAVESTAT.zst')
    print('STATE',index,flush=True)
    start,size,region=next(a for a in state.allocations if a[0]==0xc0000000)
    for offset in range(0,size,0x100000):
        bits=region.bitmap[offset//1024:min(offset+0x100000,size)//1024]
        active=sum(int(b).bit_count() for b in bits)
        if active:
            print(f' VRAM {offset:08x}: {active*128} stored bytes')
    print('Shader at c0000400:',state.read(0xc0000400,128).hex())
    print('CPU data e70000:',state.read(0xe70000,64).hex())
    dma = state.read(0x40100040, 24)
    put,get,ref,unk0,unk1,unk2 = struct.unpack('>6I', dma)
    print('DMA control:', {"put":hex(put),"get":hex(get),"ref":hex(ref),
                           "unk0":hex(unk0),"unk1":hex(unk1),"unk2":hex(unk2)})
    mappings=[(0,0x100000,0x39c00000),(0x100000,0x100000,0x31400000),
              (0x200000,0x200000,0x31500000),(0x400000,0x1100000,0x30100000),
              (0x1500000,0x8800000,0x31300000)]
    for io,length,ea in mappings:
        if io <= get < io+length:
            print('FIFO around GET:',state.read(ea+get-io,128).hex())
            break
    # Independently verify a sparse read by a straightforward scalar decoder.
    offset=next(i for i,b in enumerate(region.bitmap) if b)*1024
    scalar=bytearray(1024)
    packed_index=sum(int(b).bit_count() for b in region.bitmap[:offset//1024])*128
    mask=int(region.bitmap[offset//1024])
    for bit in range(8):
        if mask & (1<<bit):
            scalar[bit*128:(bit+1)*128]=region.packed[packed_index:packed_index+128]
            packed_index+=128
    assert region.read(offset,1024)==scalar
    print('Sparse-reader scalar verification passed at',hex(offset))
    fxo=state.data[state.meta['fxo_start']:]
    # Display descriptors are BE u32 offset,pitch,width,height (verify in source).
    for pattern in [struct.pack('>4I',0x10000,5120,1280,720),
                    struct.pack('<4I',0x10000,5120,1280,720),
                    struct.pack('<4I',1280,720,5120,0x10000)]:
        hits=[]; pos=0
        while (pos:=fxo.find(pattern,pos))>=0:
            hits.append(pos); pos+=1
        print('Display-pattern',pattern.hex(),hits)
