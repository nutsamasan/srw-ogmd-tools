"""Guarded installation/rollback of the complete test build. Never controls RPCS3."""
import argparse,json,os,shutil,subprocess,hashlib
from datetime import datetime,timezone
from pathlib import Path
from package_full_english import ROOT,OUT,ARCHIVES,digest
BACKUP=ROOT/'work/backups/full_english_20260907'
TARGET_DIRS=[ROOT/'work/rpcs3_stage000_english_poc/PS3_GAME/USRDIR/PSARC',ROOT/'work/rpcs3_runtime_stage000_english_test/dev_hdd0/game/BLJS10335/USRDIR/PSARC']
STATE=ROOT/'reports/full_english_install_20260907.json'
JOURNAL=ROOT/'reports/full_english_install_journal.json'
PROTECTED={
 'work/rpcs3_runtime_stage000_english_test/patches/imported_patch.yml':'328c6e0815c8d4685fbbc86f9466c84bae37c8ad46f2c026b0f031470cff44f8',
 'work/rpcs3_runtime_stage000_english_test/config/patch_config.yml':'61f2e154205c8d7a2b778948ac9a0cf857377add63935c4dafeede3d14f71a4d',
 'work/rpcs3_stage000_english_poc/PS3_GAME/USRDIR/EBOOT.BIN':'38ac2f2cac4d2ce76423bb800ea46c7d8c80bad874298dfd11954936685add09',
}

def game_closed():
    # Read-only process query. The user alone starts/stops emulation.
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"if (Get-Process -Name rpcs3 -ErrorAction SilentlyContinue) { exit 4 }"],capture_output=True)
    if r.returncode!=0:raise RuntimeError('RPCS3 is open. Installation requires the user to close it first.')

def atomic_copy(source,target,expected,mtime_ns=None):
    source=Path(source)
    source_stat=source.stat()
    tmp=target.with_name(target.name+'.full-english.tmp')
    assert not tmp.exists(),str(tmp)
    with Path(source).open('rb') as src,tmp.open('xb') as dst:
        shutil.copyfileobj(src,dst,1048576);dst.flush();os.fsync(dst.fileno())
    assert digest(tmp)==expected
    # The native installation check compares modification time as well as
    # size (EBOOT 0x230988-0x2309b8). Both copies must retain the same date.
    if mtime_ns is None:mtime_ns=source_stat.st_mtime_ns
    os.utime(tmp,ns=(source_stat.st_atime_ns,mtime_ns))
    os.replace(tmp,target)
    assert digest(target)==expected
    assert target.stat().st_mtime_ns==mtime_ns


def installation_icon_item():
    # Native TOC -0x52f0 maps this archived image to the loose HDD ICON0.PNG.
    # Its rounded size participates in the mandatory installation-size check.
    from package_full_english import Psarc,SOURCE
    source=Psarc(SOURCE/'Common.psarc')
    original=source._read_file(next(e for e in source.entries if e.name=='/Dat/SaveData/sys_icon.png'))
    build=OUT/'ui/Common/Dat/SaveData/sys_icon.png'
    return dict(archive='InstallIcon',target=str(TARGET_DIRS[1].parents[1]/'ICON0.PNG'),
                backup=str(BACKUP/'ICON0.PNG'),build=str(build),
                before=hashlib.sha256(original).hexdigest(),after=digest(build),
                mtime_reference=str(TARGET_DIRS[1]/'Common.psarc.sdat'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--rollback',action='store_true');p.add_argument('--check',action='store_true');args=p.parse_args()
    game_closed()
    for file,expected in PROTECTED.items():assert digest(ROOT/file)==expected,('Accepted spacing changed',file)
    doc=json.loads((OUT/'build_manifest.json').read_text());items=[]
    for a in ARCHIVES:
        source=next(x for x in doc['archives'] if x['name']==a)
        rows=[r for r in doc['overrides'] if r['archive']==a]
        fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        report=json.loads((OUT/'archives'/(a+'.verification.json')).read_text())
        assert report['manifest_fingerprint']==fingerprint and report['source_sha256']==source['source_sha256']
        assert report['sdat_all_block_hashes_and_plaintext_verified'] and report['exact_native_sizes']
        assert report['replaced_entries_verified']==len(rows)
        build=OUT/'archives'/(a+'.psarc.sdat');backup=BACKUP/(a+'.psarc.sdat')
        after=report['sdat_sha256'];before='d032ae8b7a589e0a471cdf668c502da3557e898d355b85a3b8b9a0297d9fc546' if a=='Logic' else source['template_sha256']
        assert digest(build)==after
        for r in rows:assert digest(r['file'])==r['sha256']
        for directory in TARGET_DIRS:
            target=directory/(a+'.psarc.sdat');expected=after if args.rollback else before
            assert digest(target)==expected,('Unexpected active revision',str(target))
            items.append(dict(archive=a,target=str(target),backup=str(backup),build=str(build),before=before,after=after))
    icon=installation_icon_item()
    icon_payload=next(r for r in doc['overrides'] if r['entry']=='/Dat/SaveData/sys_icon.png')
    assert icon['after']==icon_payload['sha256']
    assert digest(icon['target'])==(icon['after'] if args.rollback else icon['before'])
    items.append(icon)
    if args.check:print(json.dumps(dict(ready=True,files=len(items),game_closed=True,accepted_spacing_unchanged=True)));return
    BACKUP.mkdir(parents=True,exist_ok=True)
    for item in items[::2]:
        backup=Path(item['backup'])
        if backup.exists():assert digest(backup)==item['before']
        else:
            assert not args.rollback
            atomic_copy(item['target'],backup,item['before'])
    record=dict(started_utc=datetime.now(timezone.utc).isoformat(),rollback=args.rollback,items=items,completed=[])
    JOURNAL.write_text(json.dumps(record,indent=2),encoding='utf8')
    completed=[]
    try:
        for item in items:
            game_closed()
            expected=item['after'] if args.rollback else item['before']
            assert digest(item['target'])==expected
            completed.append(item)
            mtime=Path(item['mtime_reference']).stat().st_mtime_ns if 'mtime_reference' in item else None
            atomic_copy(item['backup'] if args.rollback else item['build'],Path(item['target']),item['before'] if args.rollback else item['after'],mtime_ns=mtime)
            record['completed'].append(item['target']);JOURNAL.write_text(json.dumps(record,indent=2),encoding='utf8')
            print('Verified '+item['target'],flush=True)
    except Exception:
        for item in reversed(completed):
            expected=item['after'] if args.rollback else item['before']
            if digest(item['target'])!=expected:
                mtime=Path(item['mtime_reference']).stat().st_mtime_ns if 'mtime_reference' in item else None
                atomic_copy(item['build'] if args.rollback else item['backup'],Path(item['target']),expected,mtime_ns=mtime)
        # Common is restored after the icon when recovering in reverse order.
        # Reconcile the icon date only once its archive has reached final state.
        if any(item.get('mtime_reference') for item in completed):
            target=Path(icon['target']);stamp=Path(icon['mtime_reference']).stat().st_mtime_ns
            os.utime(target,ns=(target.stat().st_atime_ns,stamp))
        record['recovered_to_starting_state']=True;JOURNAL.write_text(json.dumps(record,indent=2),encoding='utf8');raise
    for item in items:assert digest(item['target'])==(item['before'] if args.rollback else item['after'])
    for a in ARCHIVES:
        assert (TARGET_DIRS[0]/(a+'.psarc.sdat')).stat().st_mtime_ns==(TARGET_DIRS[1]/(a+'.psarc.sdat')).stat().st_mtime_ns
    assert Path(icon['target']).stat().st_mtime_ns==Path(icon['mtime_reference']).stat().st_mtime_ns
    required_kb=sum(((TARGET_DIRS[1]/(a+'.psarc.sdat')).stat().st_size+1023)//1024 for a in ARCHIVES)
    required_kb+=(Path(icon['target']).stat().st_size+1023)//1024
    installed_kb=sum((p.stat().st_size+1023)//1024 for p in Path(icon['target']).parent.rglob('*') if p.is_file())
    assert installed_kb>required_kb,('Native installation total-size guard',installed_kb,required_kb)
    for file,expected in PROTECTED.items():assert digest(ROOT/file)==expected
    record.update(finished_utc=datetime.now(timezone.utc).isoformat(),verified=True,spacing_and_executable_unchanged=True)
    target=STATE.with_name(STATE.stem+'_rollback.json') if args.rollback else STATE
    target.write_text(json.dumps(record,indent=2),encoding='utf8');JOURNAL.write_text(json.dumps(record,indent=2),encoding='utf8')
    print(json.dumps(dict(installed=not args.rollback,rolled_back=args.rollback,files=len(items),verified=True,report=str(target))),flush=True)

if __name__=='__main__':main()
