"""Verify and package the confirmed battle-caption fix in both desktop apps."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor'))
from archive_patch import digest
from core import atomic_json
from full_patch import package_info
from native_eboot import BATTLE_CAPTION_LIMITS, ELF_SHA256, load_asset

QA = ROOT / 'work/poc/battle_caption_release_20260920'
BACKUP = ROOT / 'work/backups/battle_caption_release_20260920'


def self_check(exe, report, version):
    print('Checking ' + exe.name, flush=True)
    subprocess.run([str(exe), '--self-check', str(report)], check=True, timeout=180)
    result = json.loads(report.read_text(encoding='utf8'))
    assert result['status'] == 'passed' and result['frozen']
    assert result['version'] == version
    assert result['english_intro'] and result['custom_notice']
    assert result['battle_caption_limits'] == BATTLE_CAPTION_LIMITS
    assert result['battle_fit_user_confirmed'] and result['diagnostic_recorder'] is False
    return result


def preserved_inputs():
    before = json.loads((BACKUP / 'before.json').read_text(encoding='utf8'))
    changed = {'full_patcher/data/release.json',
               'full_patcher/data/native_eboot/assets.json',
               'full_patcher/data/native_eboot/EBOOT.BIN.zlib'}
    results = []
    for item in before['preserved_inputs']:
        if item['path'] in changed:
            continue
        after = digest(ROOT / item['path'])
        assert after == item['sha256'], 'Unintended change: ' + item['path']
        results.append(dict(path=item['path'], sha256=after, unchanged=True))
    previous = json.loads((BACKUP / 'full_patcher/data/release.json').read_text(encoding='utf8'))
    current = package_info(ROOT / 'full_patcher/data')
    for key in ('archives', 'review', 'edited_rows', 'movie', 'custom_notice',
                'fixed_terminology', 'project_sha256'):
        assert current[key] == previous[key], 'Release content changed: ' + key
    return results


def main():
    raw_log = (QA / 'unittest.log').read_bytes()
    log = raw_log.decode('utf16' if raw_log.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf8')
    count = re.search(r'Ran (\d+) tests? in ', log)
    assert count and re.search(r'^OK\s*$', log, re.MULTILINE), 'Regression suite did not pass'
    native = json.loads((QA / 'verification.json').read_text(encoding='utf8'))
    assert native['status'] == 'passed' and native['elf_sha256'] == ELF_SHA256
    source_iso = json.loads((QA / 'iso_upgrade_check.json').read_text(encoding='utf8'))
    assert source_iso['status'] == 'passed' and source_iso['eboot']['elf_sha256'] == ELF_SHA256
    builder = json.loads((QA / 'build.json').read_text(encoding='utf8'))
    assert builder['tested_caption_payload_identical'] and builder['diagnostic_recorder_removed']

    editor = ROOT / 'script_editor'
    patcher = ROOT / 'full_patcher'
    editor_exe = editor / 'OGMD Script Editor v3.11.exe'
    patcher_exe = patcher / 'OGMD Full English Patcher v1.6.2.exe'
    asset, payload = load_asset(patcher / 'data/native_eboot')
    editor_asset, editor_payload = load_asset(editor / 'assets/native_eboot')
    assert asset == editor_asset and payload == editor_payload
    assert asset['elf_sha256'] == ELF_SHA256 and not asset['diagnostic_recorder']
    checks = {
        'editor': self_check(editor_exe, editor / 'qa/bundle_v311_check.json', '3.11'),
        'patcher': self_check(patcher_exe, editor / 'qa/bundle_patcher_v162_check.json', '1.6.2'),
    }
    assert checks['editor']['current_editor_edits_verified']
    release = package_info(patcher / 'data')
    preserved = preserved_inputs()

    package = patcher / 'OGMD Full English Patcher 1.6.2.zip'
    pending = package.with_suffix('.zip.pending')
    assert not package.exists() and not pending.exists()
    members = [(patcher_exe, 'OGMD Full English Patcher.exe'), (patcher / 'README.md', 'README.md')]
    members += [(p, 'data/' + p.relative_to(patcher / 'data').as_posix())
                for p in sorted((patcher / 'data').rglob('*')) if p.is_file()]
    print('Creating and checking the standalone package...', flush=True)
    with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in members:
            archive.write(source, name)
    portable = QA / 'portable'
    portable.mkdir()
    with zipfile.ZipFile(pending) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {name for source, name in members}
        for source, name in members:
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest(source)
        archive.extractall(portable)
    checks['portable_patcher'] = self_check(portable / 'OGMD Full English Patcher.exe',
                                           QA / 'portable_check.json', '1.6.2')
    assert package_info(portable / 'data') == release
    preserved_inputs()
    os.replace(pending, package)
    package_hash = digest(package)
    package.with_suffix('.zip.sha256').write_text(package_hash + '  ' + package.name + '\n', encoding='ascii')

    # Publish the generic launchers only after source, frozen and portable checks.
    for source, target in ((editor_exe, editor / 'OGMD Script Editor.exe'),
                           (patcher_exe, patcher / 'OGMD Full English Patcher.exe')):
        pending_exe = target.with_suffix('.exe.pending')
        assert not pending_exe.exists()
        shutil.copy2(source, pending_exe)
        assert digest(pending_exe) == digest(source)
        os.replace(pending_exe, target)
        assert digest(target) == digest(source)

    record = dict(status='verified', editor_version='3.11', patcher_version='1.6.2',
                  release_data=release['release'], editor=str(editor_exe),
                  editor_sha256=digest(editor_exe), patcher=str(patcher_exe),
                  patcher_sha256=digest(patcher_exe), generic_launchers_updated=True,
                  portable_package=str(package), package_sha256=package_hash,
                  package_size=package.stat().st_size, automated_tests_passed=int(count.group(1)),
                  native_caller_cases=native['native_caller_cases'], frozen_checks=checks,
                  existing_iso_upgrade=source_iso, embedded_asset=asset,
                  preserved_inputs=preserved, backup=str(BACKUP),
                  user_game_modified=False, emulator_started=False,
                  in_game_visual_scope=asset['battle_visual_test_scope'],
                  release_binary_fresh_visual_test=False,
                  confirmed_test_build_fitting_code_identical=True)
    report = ROOT / 'reports/editor_v311_patcher_v162_20260920.json'
    atomic_json(report, record)
    issue_path = ROOT / 'reports/battle_caption_path_fix_20260920.json'
    issue = json.loads(issue_path.read_text(encoding='utf8'))
    issue.update(shipping_patcher_modified=True, release_report=str(report))
    issue['coverage']['shipping_patcher_updated'] = True
    atomic_json(issue_path, issue)
    builder.update(status='verified and packaged', release_report=str(report))
    atomic_json(QA / 'build.json', builder)
    print(json.dumps({k:record[k] for k in ('status', 'editor_version', 'patcher_version',
                     'automated_tests_passed', 'native_caller_cases', 'portable_package')}), flush=True)


if __name__ == '__main__':
    main()
