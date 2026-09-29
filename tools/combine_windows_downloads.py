"""Assemble one complete download per tool from verified GUI and data ZIPs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'script': 'OGMD-Script-Editor-3.14', 'full': 'OGMD-Full-English-Patcher-1.6.2'}


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def extract(archive, prefix, destination, ignore=()):
    """Extract one explicit archive subtree into a new package directory."""
    destination = Path(destination).resolve()
    count = 0
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('Archive failed CRC check: ' + str(archive))
        for item in z.infolist():
            if item.is_dir() or not item.filename.startswith(prefix + '/'):
                continue
            relative = item.filename[len(prefix) + 1:]
            if relative in ignore:
                continue
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Invalid archive path')
            if target.exists():
                raise FileExistsError('Package files overlap: ' + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            count += 1
    if not count:
        raise ValueError('Required archive subtree missing: ' + prefix)


def copy_docs(home, key):
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, home / name)
    docs = home / 'docs'; docs.mkdir(exist_ok=True)
    for name in ('WINDOWS_DOWNLOADS.md', 'DATA_DOWNLOADS.md', 'LOCAL_DATA.md',
                 'DEPENDENCY_SOURCES.md', 'DEVELOPMENT.md'):
        shutil.copy2(ROOT / 'docs' / name, docs / name)
    shutil.copy2(ROOT / ('script_editor' if key == 'script' else 'full_patcher') / 'README.md', docs / 'TOOL_README.md')


def assemble(key, gui_dir, data_dir, output):
    name = NAMES[key]
    home = output / 'packages' / name
    if home.exists():
        raise FileExistsError('Use a fresh output folder; packages are not overwritten: ' + str(home))
    gui = gui_dir / (name + '-windows-x64.zip')
    data = data_dir / (name + '-data.zip')
    # The unchanged editor expects full_patcher beside its executable folder.
    # Keep both inside one portable package, with a launcher at its top level.
    app_home = home / 'Editor' if key == 'script' else home
    extract(gui, name, app_home)
    extract(data, name, app_home, ignore=('DATA_SETUP.txt',))
    inputs = {gui.name: sha(gui), data.name: sha(data)}
    if key == 'script':
        patch_data = data_dir / (NAMES['full'] + '-data.zip')
        extract(patch_data, NAMES['full'] + '/data', home / 'full_patcher' / 'data')
        inputs[patch_data.name] = sha(patch_data)
        (home / 'Start Script Editor.cmd').write_text(
            '@echo off\nstart "" "%~dp0Editor\\OGMD-Script-Editor-3.14.exe"\n', encoding='ascii')
        instructions = '''OGMD Script Editor 3.14 - complete portable package

1. Extract the entire ZIP.
2. Double-click Start Script Editor.cmd.

The program, English/Japanese script corpus, preview resources, runtime
support and Full English Patcher 1.6.2 data are all included. No separate
data download or Python installation is needed.

You can also open Editor/OGMD-Script-Editor-3.14.exe directly. Keep the Editor
and full_patcher folders together. Full English patcher and Embed font /
battle text fix buttons automatically use the included full_patcher/data.
To build a full English copy with your edits, choose Use current editor edits.
The script-reading guide is Editor/script_export/OGMD_EN_JP_20260908/START_HERE.md.
'''
    else:
        instructions = '''OGMD Full English Patcher 1.6.2 - complete portable package

1. Extract the entire ZIP.
2. Open OGMD-Full-English-Patcher-1.6.2.exe.

The program and complete 1.6.2 patching data are included. No separate data
download or Python installation is needed. Keep data and _internal beside
the executable. Release data folder is detected automatically.

Choose your supported Japanese PS3 BLJS10335 01.00 ISO or complete game
folder, choose a NEW output location, then use Build and verify patch and
Create English output.
'''
    instructions += '''
Keep your own game/save backups. Patching requires your own compatible game
copy; a complete game ISO or disc folder is not included.

Tool source is GPLv3. Game-derived script, translation and support resources
retain their original ownership and are not relicensed as GPL.

Project: https://github.com/nutsamasan/srw-ogmd-tools
Release: https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-09-29
'''
    (home / 'START_HERE.txt').write_text(instructions, encoding='utf8')
    if app_home != home:
        (app_home / 'START_HERE.txt').write_text(instructions, encoding='utf8')
    # DATA_SETUP was the old two-download guide. The complete package uses
    # START_HERE instead; regenerate per-file data checksums for this layout.
    data_roots = ([app_home / 'assets', app_home / 'script_export', home / 'full_patcher' / 'data']
                  if key == 'script' else [home / 'data'])
    entries = []
    for folder in data_roots:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                entries.append(f'{sha(path)}  {path.relative_to(home).as_posix()}')
    old_checksums = app_home / 'DATA_SHA256SUMS.txt'
    if old_checksums.exists():
        old_checksums.unlink()
    (home / 'DATA_SHA256SUMS.txt').write_text('\n'.join(entries)+'\n', encoding='utf8')
    build = json.loads((app_home / 'BUILD_INFO.json').read_text(encoding='utf8'))
    build.update(game_resources_bundled=True, full_patcher_data_bundled=True,
                 format='Complete portable package with PyInstaller onedir runtime')
    (app_home / 'BUILD_INFO.json').write_text(json.dumps(build, indent=2)+'\n', encoding='utf8')
    copy_docs(home, key)
    if app_home != home:
        copy_docs(app_home, key)
    package_revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    info = dict(tool=key, binary_source_revision=build['source_revision'],
                packaging_source_revision=package_revision, input_archives=inputs,
                program_and_data_included=True, original_game_required=True,
                launch='Start Script Editor.cmd' if key == 'script' else name+'.exe')
    (home / 'PACKAGE_INFO.json').write_text(json.dumps(info, indent=2)+'\n', encoding='utf8')
    archive = output / (name + '-windows-x64.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(home.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(home.parent))
    return dict(filename=archive.name, size=archive.stat().st_size, sha256=sha(archive), **info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit packaging changes before creating release downloads')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    results = []
    for key in NAMES:
        print('Combining '+key, flush=True)
        result = assemble(key, args.gui_dir.resolve(), args.data_dir.resolve(), output)
        results.append(result)
        print(result['filename']+f" ({result['size']:,} bytes)", flush=True)
    (output / 'packaging-report.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf8')


if __name__ == '__main__':
    main()
