"""Install or restore the verified apostrophe spacing patch; never run RPCS3."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import build_ogmd_apostrophe_patch as patch
import build_ogmd_spacing_patch as previous
from install_ogmd_spacing_patch import atomic_write
import yaml

RUNTIME = patch.ROOT / 'work/rpcs3_runtime_stage000_english_test'
BACKUP = patch.ROOT / 'work/backups/text_layout_20260909/spacing_v3_apostrophe'
MANIFEST = patch.ROOT / 'reports/ogmd_apostrophe_install_20260909.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def game_closed():
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         "Get-CimInstance Win32_Process -Filter \"Name='rpcs3.exe'\" | Select-Object -ExpandProperty ExecutablePath | ConvertTo-Json -Compress"],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError('Could not check whether the target RPCS3 is open.')
    paths = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(paths, str):
        paths = [paths]
    expected = os.path.normcase(str((RUNTIME / 'rpcs3.exe').resolve()))
    if paths is None or any(p is None or os.path.normcase(str(Path(p).resolve())) == expected for p in paths):
        raise RuntimeError(f'Close {RUNTIME / "rpcs3.exe"} manually before changing its patch settings.')


def protected_files():
    roots = [patch.ROOT / 'work/rpcs3_stage000_english_poc/PS3_GAME/USRDIR',
             RUNTIME / 'dev_hdd0/game/BLJS10335/USRDIR']
    paths = [p for root in roots for p in (root / 'PSARC').glob('*.psarc.sdat')]
    paths += [roots[0] / 'EBOOT.BIN', patch.ROOT / 'script_editor/edits/project.json']
    return {str(p): file_digest(p) for p in paths}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.rollback and args.check:
        parser.error('Choose check or rollback separately.')
    game_closed()
    if args.rollback:
        manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
        for item in manifest['files']:
            assert file_digest(item['path']) == item['after_sha256'], 'Settings changed since install; preserve later changes.'
            assert file_digest(item['backup']) == item['before_sha256']
        changes = [(Path(i['path']), Path(i['path']).read_bytes(), Path(i['backup']).read_bytes()) for i in manifest['files']]
    else:
        assert not MANIFEST.exists(), 'An installation record already exists; do not overwrite its backups.'
        source = (patch.OUT / patch.PATCH_FILE).read_bytes()
        verification = json.loads((patch.OUT / 'verification_report.json').read_text(encoding='utf8'))
        assert verification['status'] == 'passed' and verification['patch_sha256'] == digest(source)
        assert verification['hooks'] == 12 and verification['hook_executions'] == 4008
        assert verification['full_routine_executions'] == 148
        old_patch = yaml.safe_load((previous.OUT / previous.PATCH_FILE).read_bytes())
        new_patch = yaml.safe_load(source)
        assert new_patch[patch.PPU_HASH][patch.PATCH_NAME]['Games'][patch.GAME_NAME]['BLJS10335'] == ['01.00']
        def settings(name):
            return {patch.PPU_HASH: {name: {patch.GAME_NAME: {'BLJS10335': {'01.00': {'Enabled': True}}}}}}
        old_settings, new_settings = settings(previous.PATCH_NAME), settings(patch.PATCH_NAME)
        patch_path = RUNTIME / 'patches/imported_patch.yml'
        config_path = RUNTIME / 'config/patch_config.yml'
        changes = []
        additions = [source[source.index((patch.PPU_HASH + ':').encode()):],
                     yaml.safe_dump(new_settings, sort_keys=False).encode('utf8')]
        for path, expected, replacement, addition in zip(
                [patch_path, config_path], [old_patch, old_settings], [new_patch, new_settings], additions):
            before = path.read_bytes()
            parsed = yaml.safe_load(before.decode('utf-8-sig'))
            assert parsed[patch.PPU_HASH] == expected[patch.PPU_HASH], f'Expected accepted v2 settings in {path}'
            start = before.index((patch.PPU_HASH + ':').encode('utf8'))
            assert yaml.safe_load(before[start:]) == {patch.PPU_HASH: expected[patch.PPU_HASH]}, 'Unexpected trailing settings'
            after = before[:start] + addition
            result = yaml.safe_load(after.decode('utf-8-sig'))
            assert result.pop(patch.PPU_HASH) == replacement[patch.PPU_HASH]
            parsed.pop(patch.PPU_HASH)
            assert result == parsed, 'Other game settings changed'
            changes.append((path, before, after))
        # Validate the font used in both active game copies against the
        # previously verified archive, not just a loose reference font.
        common_report = json.loads((patch.ROOT / 'work/poc/full_english_20260906/archives/Common.verification.json').read_text())
        protected = protected_files()
        assert all(value == common_report['sdat_sha256'] for name, value in protected.items() if name.endswith('Common.psarc.sdat'))
        assert protected[str(patch.ROOT / 'work/rpcs3_stage000_english_poc/PS3_GAME/USRDIR/EBOOT.BIN')] == '38ac2f2cac4d2ce76423bb800ea46c7d8c80bad874298dfd11954936685add09'
        if args.check:
            print(json.dumps(dict(ready=True, verified_patch_sha256=digest(source), settings_files=len(changes),
                                 protected_files=len(protected), game_closed=True)))
            return
        BACKUP.mkdir(parents=True, exist_ok=True)
        records = []
        for path, before, after in changes:
            backup = BACKUP / (path.name + '.before')
            if backup.exists():
                assert backup.read_bytes() == before
            else:
                with backup.open('xb') as stream:
                    stream.write(before)
                    stream.flush()
                    os.fsync(stream.fileno())
            records.append(dict(path=str(path), backup=str(backup), before_sha256=digest(before), after_sha256=digest(after)))

    for path, before, _ in changes:
        assert path.read_bytes() == before, 'Settings changed during preparation'
    game_closed()
    applied = []
    try:
        for path, before, after in changes:
            atomic_write(path, after)
            applied.append((path, before))
        if not args.rollback:
            assert protected_files() == protected, 'Protected game or editor files changed during installation'
            manifest = dict(installed_utc=datetime.now(timezone.utc).isoformat(), patch_name=patch.PATCH_NAME,
                            patch_sha256=digest(source), files=records, protected_sha256=protected,
                            verification=verification,
                            status='Installed and enabled for next fresh RPCS3 launch; user visual test pending')
            atomic_write(MANIFEST, (json.dumps(manifest, indent=2) + '\n').encode('utf8'))
    except Exception:
        for path, before in reversed(applied):
            atomic_write(path, before)
        raise
    print('Previous v2 spacing restored.' if args.rollback else
          'Apostrophe spacing installed and enabled. Archives, EBOOT, and editor edits verified unchanged. Fresh user boot required.')


if __name__ == '__main__':
    main()
