"""Check the frozen program in isolation, assemble its ZIP, and verify original hashes."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile
import re
import pilot_patch as core
import will_save as saves
from app import VERSION

HERE=Path(__file__).resolve().parent
EXE=HERE/f'OGMD Pilot Editor v{VERSION}.exe'
ZIP=HERE/f'OGMD Pilot Editor {VERSION}.zip'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    real=json.loads((HERE/'qa/real_verification.json').read_text())
    baseline=json.loads((HERE/f'qa/v{VERSION}_input_snapshot.json').read_text())
    target=Path(baseline['archives'][1]['path']); save=Path(baseline['saves'][0]['path'])
    log=(HERE/f'qa/unittest_v{VERSION}.log').read_text(encoding='utf8')
    count=int(re.search(r'Ran (\d+) tests',log)[1])
    assert '\nOK' in log and 'FAILED' not in log and 'invalid command' not in log
    report=dict(version=VERSION,automated_tests=count,tests_passed=True,review_display_scales=[100,125,150,200],
        prior_copy_verification='real_verification.json',prior_archive_copies_verified=len(real['archives']),prior_save_copies_verified=len(real['saves']),
        exe_sha256=digest(EXE),in_game_test=False)
    with tempfile.TemporaryDirectory(prefix='ogmd-pilot-portable-') as folder:
        folder=Path(folder)
        isolated=folder/EXE.name; isolated.write_bytes(EXE.read_bytes())
        result=folder/'check.json'
        subprocess.run([str(isolated),'--check',str(result),'--target',str(target),'--save',str(save)],
            cwd=folder,check=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        checked=json.loads(result.read_text())
        assert checked['ok'] and checked['gui_constructed'] and checked['archive_read'] and checked['save_read']
        assert checked['review_actions_constructed'] and checked['write_requires_exit_checkbox'] and checked['profile_guide_constructed']
        assert checked['version']==VERSION
        assert checked['archive_sha256']==baseline['archives'][1]['source']['sha256']
        (HERE/f'qa/packaged_check_v{VERSION}.json').write_text(json.dumps(checked,indent=2)+'\n',encoding='utf8')
        report['isolated_frozen_check']=checked
    for item in baseline['archives']:assert core.snapshot(Path(item['path']))==item['source']
    for item in baseline['saves']:assert saves.snapshot_slot(item['path'])==item['source']
    report.update(original_archives_unchanged=True,original_saves_unchanged=True,zip_crc_verified=True)
    (HERE/f'qa/release_verification_v{VERSION}.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    EXE.with_suffix('.exe.sha256').write_text(digest(EXE)+'  '+EXE.name+'\n',encoding='ascii')
    selected=[EXE,EXE.with_suffix('.exe.sha256'),HERE/'README.md',HERE/'FORMAT_NOTES.md',HERE/'WILL_BEHAVIOR.md',
        HERE/'catalog.json',HERE/'names.json',HERE/'archive_locations.json',HERE/'save_locations.json',HERE/'build.ps1']
    selected += sorted(HERE.glob('*.py'))
    selected += sorted((HERE/'vendor').glob('*.py'))
    selected += [p for p in sorted((HERE/'qa').glob('*')) if p.is_file() and p.suffix in ('.json','.png','.log','.txt','.py')]
    with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in selected:archive.write(path,f'OGMD Pilot Editor {VERSION}/'+path.relative_to(HERE).as_posix())
    with zipfile.ZipFile(ZIP) as archive:
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read(f'OGMD Pilot Editor {VERSION}/'+EXE.name)).hexdigest()==digest(EXE)
    ZIP.with_suffix('.zip.sha256').write_text(digest(ZIP)+'  '+ZIP.name+'\n',encoding='ascii')
    print(json.dumps(dict(exe=str(EXE),zip=str(ZIP),exe_bytes=EXE.stat().st_size,zip_bytes=ZIP.stat().st_size,
        isolated_frozen_gui_and_data_check=True,zip_crc=True,original_files_unchanged=True,in_game_test=False),indent=2))


if __name__=='__main__':main()
