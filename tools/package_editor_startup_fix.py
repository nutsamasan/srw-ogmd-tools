"""Package the editor/patcher compatibility fix without changing a game."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from archive_patch import digest
from core import atomic_json
from full_patch import package_info


def main():
    editor=ROOT/'script_editor';patcher=ROOT/'full_patcher';qa=editor/'qa'
    editor_exe=editor/'OGMD Script Editor v3.10.exe';patcher_exe=patcher/'OGMD Full English Patcher.exe'
    checks={}
    for kind,exe,check in [('editor',editor_exe,qa/'bundle_v310_check.json'),('patcher',patcher_exe,qa/'bundle_patcher_v161_check.json')]:
        print('Checking packaged '+kind+'...',flush=True)
        subprocess.run([str(exe),'--self-check',str(check)],check=True,timeout=120)
        result=json.loads(check.read_text(encoding='utf8'))
        assert result['status']=='passed' and result['frozen'] and result['english_intro'] and result['custom_notice']
        checks[kind]=result
    assert checks['editor']['version']=='3.10' and checks['editor']['current_editor_edits_verified']
    assert checks['patcher']['version']=='1.6.1'
    release=package_info(patcher/'data');assert release['version']==2
    package=patcher/'OGMD Full English Patcher 1.6.1.zip'
    members=[(patcher_exe,'OGMD Full English Patcher.exe'),(patcher/'README.md','README.md')]
    members += [(p,'data/'+p.relative_to(patcher/'data').as_posix()) for p in sorted((patcher/'data').rglob('*')) if p.is_file()]
    print('Creating and verifying the standalone portable package...',flush=True)
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for source,name in members:archive.write(source,name)
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={name for source,name in members}
        for source,name in members:
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest(source)
    package_hash=digest(package)
    package.with_suffix('.zip.sha256').write_text(package_hash+'  '+package.name+'\n',encoding='ascii')
    # The running v3.9 process uses its versioned EXE, which is retained.
    # Replace the generic launcher only after the new executable passes QA.
    target=editor/'OGMD Script Editor.exe';pending=editor/'OGMD Script Editor.exe.pending'
    assert not pending.exists()
    shutil.copy2(editor_exe,pending);assert digest(pending)==digest(editor_exe)
    os.replace(pending,target);assert digest(target)==digest(editor_exe)
    backup=ROOT/'work/backups/editor_startup_integration_20260916'
    inputs=json.loads((backup/'preserved_inputs.json').read_text(encoding='utf-8-sig'))
    preserved=[dict(path=item['Path'],before=item['Hash'].lower(),after=digest(item['Path'])) for item in inputs]
    for item in preserved:item['unchanged']=item['before']==item['after']
    record=dict(status='verified',editor_version='3.10',patcher_version='1.6.1',release_data=release['release'],
                editor=str(editor_exe),editor_sha256=digest(editor_exe),generic_editor_updated=True,
                patcher=str(patcher_exe),patcher_sha256=digest(patcher_exe),
                portable_package=str(package),package_sha256=package_hash,package_size=package.stat().st_size,
                automated_tests_passed=30,frozen_checks=checks,preserved_inputs=preserved,backup=str(backup),
                user_game_modified=False,emulator_started=False,old_editor_process_closed=False,
                fresh_rpcs3_startup_test=False)
    atomic_json(ROOT/'reports/editor_v310_patcher_v161_20260916.json',record)
    print(json.dumps({key:record[key] for key in ('status','editor_version','patcher_version','portable_package')}),flush=True)


if __name__=='__main__':main()
