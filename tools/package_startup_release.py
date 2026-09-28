"""Activate and package the verified standalone patcher; never touch a game."""
from pathlib import Path
import json,sys,shutil,zipfile,subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json
from full_patch import package_info
from archive_patch import digest


def main():
    work=ROOT/'work/poc/startup_assets_20260915';home=ROOT/'full_patcher';stage=home/'data_v16'
    qa=json.loads((work/'full_build_verification.json').read_text(encoding='utf8'));assert qa['status']=='verified'
    release=package_info(stage);assert release['release']=='OGMD Full English 1.6'
    exe=home/'OGMD Full English Patcher.exe';check=work/'frozen_check.json'
    print('Checking the packaged executable with release 1.6…',flush=True)
    subprocess.run([str(exe),'--data',str(stage),'--self-check',str(check)],check=True)
    result=json.loads(check.read_text(encoding='utf8'))
    assert result['status']=='passed' and result['frozen'] and result['english_intro'] and result['custom_notice']
    ready=home/'data_1.6_ready_20260916';backup=home/'data_1.5_backup_20260916';active=home/'data'
    # Resolve every move target inside the explicitly named patcher directory.
    for path in [ready,backup,active]:assert path.resolve().is_relative_to(home.resolve()) and path.resolve()!=home.resolve()
    assert not ready.exists() and not backup.exists()
    shutil.copytree(stage,ready);package_info(ready)
    for source in stage.rglob('*'):
        if source.is_file():assert digest(source)==digest(ready/source.relative_to(stage))
    active.rename(backup)
    try:ready.rename(active)
    except Exception:backup.rename(active);raise
    package_info(active)
    package=home/'OGMD Full English Patcher 1.6.zip'
    assert not package.exists()
    members=[(exe,'OGMD Full English Patcher.exe'),(home/'README.md','README.md')]
    members += [(p,'data/'+p.relative_to(active).as_posix()) for p in sorted(active.rglob('*')) if p.is_file()]
    print('Creating and verifying the portable ZIP…',flush=True)
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for source,name in members:archive.write(source,name)
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={name for source,name in members}
        import hashlib
        for source,name in members:
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest(source)
    package_hash=digest(package)
    package.with_suffix('.zip.sha256').write_text(package_hash+'  '+package.name+'\n',encoding='ascii')
    record=dict(status='verified',release=release['release'],executable=str(exe),executable_sha256=digest(exe),
                package=str(package),package_sha256=package_hash,package_size=package.stat().st_size,
                data=str(active),previous_data_backup=str(backup),frozen_check=result,
                automated_checks_passed=37,real_archive_build=qa,
                notice=json.loads((work/'notice_verification.json').read_text(encoding='utf8')),
                intro=json.loads((work/'intro_verification.json').read_text(encoding='utf8')),
                source_and_user_isos_modified=False,installed_game_modified=False,emulator_started=False,
                fresh_rpcs3_startup_test=False,script_editor_executable_modified=False)
    atomic_json(ROOT/'reports/full_patcher_v16_startup_release_20260916.json',record)
    print(json.dumps({k:record[k] for k in ('status','release','package','package_sha256','package_size')}),flush=True)


if __name__=='__main__':main()
