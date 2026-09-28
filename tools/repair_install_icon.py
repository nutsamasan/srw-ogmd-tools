"""Restore the native sys_icon.png -> installed ICON0.PNG link for the English build."""
import argparse,json,struct,sys
from datetime import datetime,timezone
from pathlib import Path
from install_full_english import ROOT,OUT,BACKUP,TARGET_DIRS,atomic_copy,installation_icon_item,digest
from repair_install_timestamps import native_compare,require_emulation_stopped

REPORT=ROOT/'reports/startup_fault_20260907/icon_repair.json'


def native_size_check(installed_kb,required_kb):
    """Run the shipped strict total-size guard; zero=pass, -1=incomplete."""
    sys.path.insert(0,str(ROOT/'work/analysis_pydeps'))
    from unicorn import Uc,UC_ARCH_PPC,UC_MODE_PPC64,UC_MODE_BIG_ENDIAN,UC_TLB_VIRTUAL
    import unicorn.ppc_const as ppc
    v=Uc(UC_ARCH_PPC,UC_MODE_PPC64|UC_MODE_BIG_ENDIAN)
    v.ctl_set_tlb_mode(UC_TLB_VIRTUAL)
    v.mem_map(0x229000,0x1000)
    elf=(ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
    v.mem_write(0x229000,elf[0x219000:0x21a000])
    v.reg_write(ppc.UC_PPC_REG_MSR,0x8000000000002000)
    v.reg_write(ppc.UC_PPC_REG_9,installed_kb)
    v.reg_write(ppc.UC_PPC_REG_30,required_kb)
    v.emu_start(0x229cc4,0x229cd0,count=15)
    assert v.reg_read(ppc.UC_PPC_REG_PC)==0x229cd0
    return struct.unpack('>q',struct.pack('>Q',v.reg_read(ppc.UC_PPC_REG_3)))[0]


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    item=installation_icon_item();target=Path(item['target']);source=Path(item['build'])
    game=target.parent;common=Path(item['mtime_reference']);before=target.stat()
    assert digest(target)==item['before']
    manifest=json.loads((OUT/'build_manifest.json').read_text(encoding='utf8'))
    entry=next(r for r in manifest['overrides'] if r['entry']=='/Dat/SaveData/sys_icon.png')
    assert digest(source)==entry['sha256']==item['after']
    from package_full_english import Psarc
    archive=Psarc(OUT/'archives/Common.psarc')
    payload=archive._read_file(next(e for e in archive.entries if e.name==entry['entry']))
    assert payload==source.read_bytes()
    archives=[]
    installed=json.loads((ROOT/'reports/full_english_install_20260907.json').read_text(encoding='utf8'))
    for name in ['Common','Battle','General2d','Logic','General3d']:
        disc,hdd=[d/(name+'.psarc.sdat') for d in TARGET_DIRS]
        expected=next(x['after'] for x in installed['items'] if x['archive']==name)
        assert digest(disc)==digest(hdd)==expected
        ds,hs=disc.stat(),hdd.stat()
        assert ds.st_size==hs.st_size and ds.st_mtime_ns==hs.st_mtime_ns
        archives.append(dict(name=name,bytes=ds.st_size,rounded_kb=(ds.st_size+1023)//1024))
    installed_kb=sum((p.stat().st_size+1023)//1024 for p in game.rglob('*') if p.is_file())
    old_icon_kb=(before.st_size+1023)//1024
    new_icon_kb=(len(payload)+1023)//1024
    required_kb=sum(x['rounded_kb'] for x in archives)+new_icon_kb
    repaired_kb=installed_kb-old_icon_kb+new_icon_kb
    before_result=native_size_check(installed_kb,required_kb)
    after_result=native_size_check(repaired_kb,required_kb)
    assert before_result==-1 and after_result==0
    assert native_size_check(required_kb,required_kb)==-1
    assert native_size_check(required_kb+1,required_kb)==0
    stamp=common.stat().st_mtime_ns
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),applied=False,item=item,
                archived_source=entry['entry'],archives=archives,
                installed_kb_before=installed_kb,required_kb=required_kb,installed_kb_after=repaired_kb,
                native_size_check_before=before_result,native_size_check_after=after_result,
                icon_bytes_before=before.st_size,icon_bytes_after=len(payload),
                icon_mtime_ns_before=before.st_mtime_ns,icon_mtime_ns_after=stamp)
    if args.apply:
        assert not REPORT.exists(),'Inspect the existing repair before repeating.'
        require_emulation_stopped()
        backup=Path(item['backup'])
        BACKUP.mkdir(exist_ok=True)
        if backup.exists():assert digest(backup)==item['before']
        else:atomic_copy(target,backup,item['before'])
        REPORT.write_text(json.dumps(report,indent=2),encoding='utf8')
        require_emulation_stopped()
        try:
            atomic_copy(source,target,item['after'],mtime_ns=stamp)
            assert target.read_bytes()==payload
            actual_kb=sum((p.stat().st_size+1023)//1024 for p in game.rglob('*') if p.is_file())
            assert actual_kb==repaired_kb and native_size_check(actual_kb,required_kb)==0
            actual=target.stat()
            assert native_compare(len(payload),stamp//1_000_000_000*1_000_000_000,
                                  actual.st_size,actual.st_mtime_ns//1_000_000_000*1_000_000_000)==0
        except Exception:
            atomic_copy(backup,target,item['before'],mtime_ns=before.st_mtime_ns)
            report['restored_original_icon']=True
            REPORT.write_text(json.dumps(report,indent=2),encoding='utf8');raise
        report.update(applied=True,installed_icon_matches_archived_source=True,native_checks_pass=True)
        REPORT.write_text(json.dumps(report,indent=2),encoding='utf8')
    else:(REPORT.parent/'icon_check.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['item','archives']}))


if __name__=='__main__':main()
