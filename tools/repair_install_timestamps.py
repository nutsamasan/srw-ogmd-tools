"""Repair verified test archive dates without changing contents or controlling RPCS3."""
import argparse
import ctypes
import hashlib
import json
import os
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/startup_fault_20260907'
STATE=OUT/'timestamp_repair.json'
INSTALL=ROOT/'reports/full_english_install_20260907.json'
LOG=ROOT/'work/rpcs3_runtime_stage000_english_test/log/RPCS3.log'


def read_shared(path):
    """RPCS3 shares its log for read/write/delete; match all sharing flags."""
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,
                                ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    handle=kernel.CreateFileW(str(path),0x80000000,7,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    with os.fdopen(fd,'rb') as stream:return stream.read()


def require_emulation_stopped():
    log=read_shared(LOG).decode('utf8','replace')
    # No UI operations. A stopped emulator can remain open in its game list.
    stop=log.rfind('SYS: Stopping emulator...')
    boot=max(log.rfind('SYS: Booting'),log.rfind('SYS: Elf path:'))
    assert stop>boot>=0 and 'Deleting old game window' in log[stop:], 'Stop emulation before changing installed dates.'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def native_compare(size_a,mtime_a,size_b,mtime_b):
    """Execute the actual pristine comparison block offline in Unicorn.

    Inputs are the size and canonical timestamp already prepared by the
    native stat/time conversion calls. Zero means accepted, one rejected.
    """
    sys.path.insert(0,str(ROOT/'work/analysis_pydeps'))
    from unicorn import Uc,UC_ARCH_PPC,UC_MODE_PPC64,UC_MODE_BIG_ENDIAN,UC_TLB_VIRTUAL
    import unicorn.ppc_const as ppc
    v=Uc(UC_ARCH_PPC,UC_MODE_PPC64|UC_MODE_BIG_ENDIAN)
    v.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
    v.mem_map(0x230000,0x2000)
    elf=(ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
    v.mem_write(0x230000,elf[0x220000:0x222000])
    v.mem_map(0x5000000,0x2000)
    sp,obj=0x5000000,0x5001000
    v.mem_write(sp+0x78,struct.pack('>Q',mtime_b))
    v.mem_write(sp+0xa4,struct.pack('>Q',size_b))
    v.mem_write(obj+8,struct.pack('>Q',size_a))
    v.mem_write(obj+0x18,struct.pack('>Q',mtime_a))
    v.reg_write(ppc.UC_PPC_REG_MSR,0x8000000000002000)
    v.reg_write(ppc.UC_PPC_REG_1,sp)
    v.reg_write(ppc.UC_PPC_REG_27,obj)
    v.emu_start(0x230988,0x2308c8,count=40)
    assert v.reg_read(ppc.UC_PPC_REG_PC)==0x2308c8
    return v.reg_read(ppc.UC_PPC_REG_3)


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    install=json.loads(INSTALL.read_text(encoding='utf8'))
    assert install['verified']
    rows=[]
    for name in ['Logic','Common','General2d','Battle','General3d']:
        items=[x for x in install['items'] if x['archive']==name]
        assert len(items)==2 and items[0]['after']==items[1]['after']
        disc,hdd=[Path(x['target']) for x in items]
        expected=items[0]['after']
        assert digest(disc)==digest(hdd)==expected
        ds,hs=disc.stat(),hdd.stat()
        a,b=ds.st_mtime_ns//1_000_000_000,hs.st_mtime_ns//1_000_000_000
        assert ds.st_size==hs.st_size
        before=native_compare(ds.st_size,a*1_000_000_000,hs.st_size,b*1_000_000_000)
        after=native_compare(ds.st_size,a*1_000_000_000,hs.st_size,a*1_000_000_000)
        assert after==0
        rows.append(dict(archive=name,disc=str(disc),installed=str(hdd),sha256=expected,
                         size=ds.st_size,disc_mtime_ns=ds.st_mtime_ns,
                         installed_mtime_ns_before=hs.st_mtime_ns,installed_atime_ns=hs.st_atime_ns,
                         native_comparison_before=before,native_comparison_after=after))
    # Negative controls exercise both branches in the shipped comparison.
    assert native_compare(100,1_000_000_000,100,2_000_000_000)==1
    assert native_compare(100,1_000_000_000,101,1_000_000_000)==1
    assert native_compare(100,1_000_000_000,100,1_000_000_000)==0
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),applied=False,
                native_comparison='EBOOT 0x230988-0x2309b8',rows=rows)
    OUT.mkdir(parents=True,exist_ok=True)
    if args.apply:
        assert not STATE.exists(),'A repair report already exists; inspect it before reapplying.'
        require_emulation_stopped()
        STATE.write_text(json.dumps(report,indent=2),encoding='utf8')
        try:
            for row in rows:
                require_emulation_stopped()
                p=Path(row['installed'])
                assert p.stat().st_mtime_ns==row['installed_mtime_ns_before']
                os.utime(p,ns=(row['installed_atime_ns'],row['disc_mtime_ns']))
            for row in rows:
                p=Path(row['installed'])
                assert p.stat().st_mtime_ns==Path(row['disc']).stat().st_mtime_ns
                assert digest(p)==row['sha256']
        except Exception:
            for row in rows:
                os.utime(row['installed'],ns=(row['installed_atime_ns'],row['installed_mtime_ns_before']))
            report['restored_original_dates']=True
            STATE.write_text(json.dumps(report,indent=2),encoding='utf8')
            raise
        report.update(applied=True,contents_unchanged=True,dates_match=True)
        STATE.write_text(json.dumps(report,indent=2),encoding='utf8')
    else:
        (OUT/'timestamp_check.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(applied=report['applied'],archives=len(rows),
                         native_rejections_before=sum(x['native_comparison_before'] for x in rows),
                         native_rejections_after=sum(x['native_comparison_after'] for x in rows))))


if __name__=='__main__':main()
