"""Read the isolated caption trace from RPCS3 without writing process memory."""
import argparse
import ctypes
import datetime
import json
import struct
from ctypes import wintypes as w
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'work/poc/battle_trace_20260920_v2'


def decode_record(raw):
    caller,count,entry,font,text,r8,r9,r10=struct.unpack_from('>8I',raw)
    if not caller:return None
    x,y,z,cw,ch,cap,cached,flags=struct.unpack_from('>5fifI',raw,32)
    r30,r31,r26,sp,target,r5,r6,r7=struct.unpack_from('>8I',raw,224)
    return dict(caller=hex(caller-4),return_address=hex(caller),count=count,
                entry=hex(entry),font=hex(font),text_pointer=hex(text),
                x=x,y=y,z=z,cell_width=cw,cell_height=ch,cap=cap,cached_width=cached,
                font_flags=hex(flags),text=raw[64:224].split(b'\0',1)[0].decode('utf8',errors='replace'),
                arguments=dict(r5=hex(r5),r6=hex(r6),r7=hex(r7),r8=r8,r9=r9,r10=r10),
                caller_state=dict(r26=hex(r26),r30=hex(r30),r31=hex(r31),sp=hex(sp),target=hex(target)))


def inspect(pid,build=BUILD):
    build=Path(build)
    report=json.loads((build/'build.json').read_text(encoding='utf8'))
    elf=(build/'EBOOT.elf').read_bytes()
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE]
    k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    handle=k.OpenProcess(0x1010,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    def read(addr,size):
        data=ctypes.create_string_buffer(size);n=ctypes.c_size_t()
        if not k.ReadProcessMemory(handle,addr,data,size,ctypes.byref(n)) or n.value!=size:
            raise ctypes.WinError(ctypes.get_last_error())
        return data.raw
    try:
        base=None
        expected_hooks=report['hooks']+([report['caption_fit_hook']] if 'caption_fit_hook' in report else [])
        for candidate in (0x400000000,0x300000000,0x200000000):
            try:
                if all(read(candidate+h['address'],4)==elf[h['address']-0x10000:h['address']-0x10000+4] for h in expected_hooks):
                    base=candidate;break
            except OSError:pass
        if base is None:raise RuntimeError('The selected diagnostic executable is not loaded in this process.')
        now=datetime.datetime.now(datetime.timezone.utc)
        out=build/('capture_'+now.strftime('%Y%m%dT%H%M%S%fZ'))
        out.mkdir()
        result=dict(pid=pid,host_base=hex(base),captured_at=now.isoformat(),memory_modified=False,
                    executable_sha256=report['asset']['sha256'],banks=[])
        for h in report['hooks']:
            raw=read(base+h['bank'],0x10000)
            (out/f"bank_{h['address']:x}.bin").write_bytes(raw)
            calls,dropped,matches=struct.unpack_from('>3I',raw)
            records=[decode_record(raw[0x100+i*256:0x200+i*256]) for i in range(128)]
            result['banks'].append(dict(entry=hex(h['address']),calls=calls,dropped=dropped,
                reported_caption_draws=matches,reported_caption=decode_record(raw[0x9000:0x9100]),
                callers=[r for r in records if r]))
        (out/'capture.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
        print(json.dumps(dict(output=str(out/'capture.json'),banks=[{k:v for k,v in b.items() if k!='callers'} for b in result['banks']]),indent=2,ensure_ascii=False))
    finally:k.CloseHandle(handle)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('pid',type=int)
    parser.add_argument('--build',type=Path,default=BUILD)
    args=parser.parse_args()
    inspect(args.pid,args.build)
