"""Create a self-contained, patch-free RPCS3 test copy without starting it."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_ogmd_native_eboot as native

sys.path.insert(0, str(native.ROOT / 'script_editor'))
from iso_image import DiscImage
import yaml

DEST = native.ROOT / 'native_eboot_test'
RUNTIME_SOURCE = Path('local_data/rpcs3')
ISO = native.ROOT / 'New folder/Super Robot Taisen OG - The Moon Dwellers (Japan) - Full English.iso'
CHUNK = 8 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    verified = json.loads((native.OUT / 'verification_report.json').read_text(encoding='utf8'))
    assert verified['status'] == 'passed'
    assert digest(native.OUT / 'EBOOT.BIN') == verified['test_eboot_sha256']
    assert not DEST.exists(), 'Refusing to replace an existing test directory'
    assert shutil.disk_usage(DEST.parent).free > 20 * 1024**3
    DEST.mkdir()
    game = DEST / 'game'
    runtime = DEST / 'runtime'
    installed = RUNTIME_SOURCE / 'dev_hdd0/game/BLJS10335'
    records = []

    def copy(source, target):
        assert target.resolve().is_relative_to(DEST.resolve())
        assert not source.is_symlink() and not source.is_junction()
        before = source.stat()
        target.parent.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256()
        with source.open('rb') as inp, target.open('xb') as out:
            while data := inp.read(CHUNK):
                checksum.update(data)
                out.write(data)
        shutil.copystat(source, target)
        after = source.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        assert digest(target) == checksum.hexdigest()
        records.append(dict(source=str(source), target=str(target.relative_to(DEST)),
                            size=target.stat().st_size, sha256=checksum.hexdigest(), mtime_ns=target.stat().st_mtime_ns))

    def tree(source, target):
        if not source.exists():
            return
        for path in sorted(source.rglob('*')):
            assert not path.is_symlink() and not path.is_junction()
            if path.is_file():
                copy(path, target / path.relative_to(source))

    # The current installed archives include the user's later editor changes.
    # Use these for both the disc copy and its isolated installed data.
    with DiscImage(ISO) as disc:
        for item in disc.files.values():
            target = game / item.path.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            assert target.resolve().is_relative_to(game.resolve())
            archive_source = installed / 'USRDIR/PSARC' / target.name
            if item.path.upper() == '/PS3_GAME/USRDIR/EBOOT.BIN':
                assert disc.checksum(item) == '38ac2f2cac4d2ce76423bb800ea46c7d8c80bad874298dfd11954936685add09'
                copy(native.OUT / 'EBOOT.BIN', target)
                if item.mtime_ns is not None:
                    os.utime(target, ns=(item.mtime_ns, item.mtime_ns))
            elif item.path.upper().startswith('/PS3_GAME/USRDIR/PSARC/') and archive_source.is_file():
                assert archive_source.stat().st_size == item.size
                copy(archive_source, target)
            else:
                checksum = disc.extract(item, target)
                assert digest(target) == checksum
                if item.mtime_ns is not None:
                    os.utime(target, ns=(item.mtime_ns, item.mtime_ns))
                records.append(dict(source=str(ISO) + ':' + item.path,
                                    target=str(target.relative_to(DEST)), size=item.size,
                                    sha256=checksum, mtime_ns=target.stat().st_mtime_ns))
            print('Verified game file:', item.path, flush=True)

    for path in sorted(RUNTIME_SOURCE.iterdir()):
        if path.is_file() and (path.suffix.lower() in ('.dll',) or path.name in ('rpcs3.exe', 'cacert.pem')):
            copy(path, runtime / path.name)
    for folder in ('qt6', 'dev_flash', 'dev_flash2', 'dev_flash3', 'sounds'):
        tree(RUNTIME_SOURCE / folder, runtime / folder)
    for folder in ('dev_hdd0', 'dev_hdd1', 'dev_usb000', 'dev_bdvd', 'games', 'cache', 'patches', 'GuiConfigs'):
        (runtime / folder).mkdir(parents=True, exist_ok=True)
    for relative in ('config/config.yml', 'config/custom_configs/config_BLJS10335.yml'):
        copy(RUNTIME_SOURCE / relative, runtime / relative)
    tree(RUNTIME_SOURCE / 'config/input_configs', runtime / 'config/input_configs')
    tree(installed, runtime / 'dev_hdd0/game/BLJS10335')
    home = RUNTIME_SOURCE / 'dev_hdd0/home'
    for user in home.iterdir():
        if not user.is_dir() or not user.name.isdecimal():
            continue
        destination = runtime / 'dev_hdd0/home' / user.name
        (destination / 'savedata').mkdir(parents=True, exist_ok=True)
        if (user / 'localusername').is_file():
            copy(user / 'localusername', destination / 'localusername')
        if (user / 'savedata').exists():
            for save in (user / 'savedata').iterdir():
                if save.is_dir() and 'BLJS10335' in save.name:
                    tree(save, destination / 'savedata' / save.name)
        trophy = user / 'trophy/NPWR10811_00'
        tree(trophy, destination / 'trophy/NPWR10811_00')

    # Explicit local mounts; no symlinks or shared writable game/savedata files.
    mounts = {'$(EmulatorDir)': runtime.as_posix() + '/'}
    for name in ('dev_hdd0', 'dev_hdd1', 'dev_flash', 'dev_flash2', 'dev_flash3', 'dev_bdvd'):
        mounts['/' + name + '/'] = (runtime / name).as_posix() + '/'
    mounts['/games/'] = (runtime / 'games').as_posix() + '/'
    mounts['/dev_usb***/'] = {'/dev_usb000': {'Path': (runtime / 'dev_usb000').as_posix() + '/', 'Serial': '', 'VID': '', 'PID': ''}}
    (runtime / 'config/vfs.yml').write_text(yaml.safe_dump(mounts, sort_keys=False), encoding='utf8')
    (runtime / 'config/games.yml').write_text(yaml.safe_dump({'BLJS10335': game.as_posix() + '/'}), encoding='utf8')
    (runtime / 'config/patch_config.yml').write_text('{}\n', encoding='utf8')
    assert not list((runtime / 'patches').iterdir())
    assert not list(runtime.glob('*patch*.yml'))

    # Check native disc files versus the installed copy, including timestamps.
    paired = []
    for archive in sorted((runtime / 'dev_hdd0/game/BLJS10335/USRDIR/PSARC').glob('*.sdat')):
        disc_archive = game / 'PS3_GAME/USRDIR/PSARC' / archive.name
        assert digest(archive) == digest(disc_archive)
        assert archive.stat().st_mtime_ns == disc_archive.stat().st_mtime_ns
        paired.append(archive.name)
    assert len(paired) == 5
    eboot = game / 'PS3_GAME/USRDIR/EBOOT.BIN'
    assert digest(eboot) == verified['test_eboot_sha256']
    launcher = '@echo off\r\ncd /d "%~dp0runtime"\r\nstart "" "%~dp0runtime\\rpcs3.exe" "%~dp0game\\PS3_GAME\\USRDIR\\EBOOT.BIN"\r\n'
    (DEST / 'Start native font test.cmd').write_bytes(launcher.encode('ascii'))
    manifest = dict(status='prepared; fresh user boot pending', created_utc=datetime.now(timezone.utc).isoformat(),
                    runtime_source=str(RUNTIME_SOURCE), iso_source=str(ISO),
                    archive_source=str(installed), game=str(game), runtime=str(runtime),
                    eboot_sha256=digest(eboot), patch_directory_empty=True,
                    patch_config_empty=True, paired_archives=paired,
                    copied_files=len(records), copied_bytes=sum(x['size'] for x in records),
                    verification=str(native.OUT / 'verification_report.json'), files=records,
                    limitations=['Debug SELF wrapper is for RPCS3 only; console signing is pending',
                                 'SDAT hardware authentication has not been validated'])
    (DEST / 'preparation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'files'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
