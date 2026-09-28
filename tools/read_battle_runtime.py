"""Read only the paused game's known battle-font state; never write memory."""
import argparse,ctypes,json,struct
from ctypes import wintypes as w
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/poc/battle_fit_runtime_20260918'


def inspect(pid):
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE]
    k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    class Region(ctypes.Structure):
        _fields_=[('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),('ap',w.DWORD),('partition',w.DWORD),('size',ctypes.c_size_t),('state',w.DWORD),('protect',w.DWORD),('type',w.DWORD)]
    k.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(Region),ctypes.c_size_t]
    k.VirtualQueryEx.restype=ctypes.c_size_t
    handle=k.OpenProcess(0x1010,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    def read_host(addr,size):
        buf=ctypes.create_string_buffer(size);n=ctypes.c_size_t()
        if not k.ReadProcessMemory(handle,addr,buf,size,ctypes.byref(n)) or n.value!=size:
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw
    try:
        base=None
        for candidate in (0x400000000,0x300000000,0x200000000):
            try:
                if read_host(candidate+0x11a088,4)==bytes.fromhex('48d4eca8'):
                    base=candidate;break
            except OSError:pass
        if base is None:raise RuntimeError('The expected test executable is not readable.')
        def read(addr,size):return read_host(base+addr,size)
        def word(addr):return struct.unpack('>I',read(addr,4))[0]
        singleton_slot=word(0xeddc88-0x6648)
        singleton=word(singleton_slot)
        manager=word(singleton+0x90)
        obj=manager+0x1b10
        fonts=[obj,word(obj+12),word(obj+16)]
        OUT.mkdir(parents=True,exist_ok=True)
        result=dict(pid=pid,base=hex(base),singleton_slot=hex(singleton_slot),singleton=hex(singleton),manager=hex(manager),fonts=[],memory_modified=False)
        for i,addr in enumerate(fonts):
            raw=read(addr,0x170)
            (OUT/f'font_object_{i}.bin').write_bytes(raw)
            font=word(addr+0x18)
            header=read(font,0x480)
            (OUT/f'font_header_{i}.bin').write_bytes(header)
            result['fonts'].append(dict(address=hex(addr),font=hex(font),cell=struct.unpack_from('>ff',raw,0x48),
                cap=struct.unpack_from('>i',raw,0x50)[0],cached=struct.unpack_from('>f',raw,0xfc)[0],
                flags=list(raw[0xf4:0xf6]),ascii_page=hex(word(font+0x54))))
        matches=[]
        needles=[('utf8',b'All hands'),('utf-16-be','All hands'.encode('utf-16-be')),('utf-16-le','All hands'.encode('utf-16-le'))]
        read_bytes=0
        at=base
        while at<base+0x100000000:
            region=Region()
            if not k.VirtualQueryEx(handle,at,ctypes.byref(region),ctypes.sizeof(region)):break
            end=min(region.base+region.size,base+0x100000000)
            if region.state==0x1000 and not region.protect&0x101:
                for start in range(max(at,region.base),end,0x100000):
                    try:block=read_host(start,min(0x100080,end-start))
                    except OSError:continue
                    read_bytes+=len(block)
                    for encoding,needle in needles:
                        index=0
                        while (found:=block.find(needle,index))>=0:
                            addr=start-base+found
                            text=block[found:found+160].decode(encoding,errors='replace').split('\0',1)[0]
                            matches.append(dict(address=hex(addr),encoding=encoding,text=text))
                            index=found+1
            at=end
        result['caption_matches']=matches
        result['caption_search_bytes']=read_bytes
        references=[]
        targets=[int(m['address'],16)-3 for m in matches if 'anti-glare' in m['text']]
        for target in targets:
            needle=struct.pack('>I',target)
            for at in range(0x30000000,0x40000000,0x10000):
                try:block=read(at,0x10000)
                except OSError:continue
                index=0
                while (found:=block.find(needle,index))>=0:
                    addr=at+found
                    references.append(dict(address=hex(addr),target=hex(target),words=[hex(v) for v in struct.unpack('>16I',read(addr-16,64))]))
                    index=found+1
        result['caption_references']=references
        (OUT/'runtime.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(json.dumps(result,indent=2))
    finally:k.CloseHandle(handle)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('pid',type=int)
    inspect(parser.parse_args().pid)
