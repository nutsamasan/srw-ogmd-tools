"""Build public Windows GUI folders/ZIPs without copying local game resources."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    'save': ('OGMD-Save-Editor-1.6', 'save_editor/save_editor.py', [
        ('save_editor/weapon_editor/catalog.json', 'weapon_editor'),
        *[(f'save_editor/{name}.json', '.') for name in ('pilot_status', 'names', 'skills', 'mechs')]]),
    'pilot': ('OGMD-Pilot-Editor-1.1', 'pilot_editor/app.py', [
        ('pilot_editor/catalog.json', '.'), ('pilot_editor/names.json', '.')]),
    'mech': ('OGMD-Mech-Skill-Patcher-1.0', 'mech_skill_patcher/app.py', [
        ('mech_skill_patcher/catalog.json', '.')]),
    'script': ('OGMD-Script-Editor-3.14', 'script_editor/app.py', [
        ('script_editor/assets/battle_speakers.json', 'assets')]),
    'full': ('OGMD-Full-English-Patcher-1.6.2', 'script_editor/full_app.py', []),
}


def build(key, output):
    name, entry, data = TOOLS[key]
    env = os.environ.copy()
    system = Path(env.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, system / 'System32', system]))
    command = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir', '--windowed',
               '--name', name, '--distpath', str(output / 'apps'), '--workpath', str(output / 'build' / key),
               '--specpath', str(output / 'build' / key), '--paths', str((ROOT / entry).parent)]
    for source, destination in data:
        command += ['--add-data', f'{ROOT / source};{destination}']
    command.append(str(ROOT / entry))
    output.mkdir(parents=True, exist_ok=True)
    with (output / f'build-{key}.log').open('w', encoding='utf8') as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    if key in ('script', 'full'):
        trim_unused_qt_plugins(output / 'apps' / name)
    (output / f'build-{key}.json').write_text(json.dumps(dict(
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        clean_source=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    ),indent=2)+'\n',encoding='utf8')


def trim_unused_qt_plugins(folder):
    """These Widgets apps do not use PDF decoding or Qt's virtual keyboard.

    PyInstaller's generic QtGui hook collects those optional plugins, bringing
    unrelated QtPdf/QML/Quick libraries. Keep the normal Windows and offscreen
    platforms, image formats, and physical keyboard/IME support.
    """
    qt = folder / '_internal' / 'PySide6'
    names = ['plugins/imageformats/qpdf.dll', 'plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
             'Qt6Pdf.dll', 'Qt6VirtualKeyboard.dll', 'Qt6Quick.dll', 'Qt6Qml.dll',
             'Qt6QmlMeta.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll']
    for name in names:
        target = (qt / name).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise ValueError('Invalid build output path')
        target.unlink(missing_ok=True)


def copy_licenses(destination, qt):
    destination.mkdir(parents=True, exist_ok=True)
    packages = ['pycryptodome', 'PyInstaller', 'Pillow', 'zopfli', 'PyYAML']
    if qt:
        packages += ['PySide6', 'PySide6_Essentials', 'shiboken6']
    versions = {}
    for name in packages:
        dist = metadata.distribution(name)
        versions[name] = dist.version
        for file in dist.files or []:
            if any(word in str(file).lower() for word in ('license', 'copying')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = destination / name / Path(str(file))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', destination / 'Python-LICENSE.txt')
    shutil.copytree(ROOT / 'licenses' / 'runtime', destination / 'runtime', dirs_exist_ok=True)
    for license_file in (Path(sys.base_prefix) / 'tcl').rglob('license.terms'):
        target = destination / 'Tcl-Tk' / license_file.relative_to(Path(sys.base_prefix) / 'tcl')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(license_file, target)
    if qt:
        shutil.copytree(ROOT / 'licenses' / 'qt', destination / 'Qt-open-source', dirs_exist_ok=True)
    return versions


def package(key, output, revision):
    name, entry, _ = TOOLS[key]
    folder = output / 'apps' / name
    if not (folder / f'{name}.exe').is_file():
        raise FileNotFoundError(f'Build {key} first')
    record=json.loads((output / f'build-{key}.json').read_text(encoding='utf8'))
    if record['source_revision'] != revision or not record['clean_source']:
        raise ValueError('Rebuild from the current clean source commit before packaging')
    for filename in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / filename, folder / filename)
    docs = folder / 'docs'; docs.mkdir(exist_ok=True)
    for filename in ('LOCAL_DATA.md', 'DEPENDENCY_SOURCES.md', 'WINDOWS_DOWNLOADS.md', 'DEVELOPMENT.md', 'DATA_DOWNLOADS.md'):
        shutil.copy2(ROOT / 'docs' / filename, docs / filename)
    shutil.copy2((ROOT / entry).parent / 'README.md' if key != 'full' else ROOT / 'full_patcher/README.md', docs / 'TOOL_README.md')
    versions = copy_licenses(folder / 'licenses', key in ('script', 'full'))
    extra = ''
    if key == 'script':
        extra = '\nAlso download OGMD-Script-Editor-3.14-data.zip from Releases and extract it into the same parent folder. It supplies the script corpus and preview resources. See docs/DATA_DOWNLOADS.md.\n'
    if key == 'full':
        extra = '\nAlso download OGMD-Full-English-Patcher-1.6.2-data.zip from Releases and extract it into the same parent folder. It supplies the patching data. You still need your own supported Japanese game copy. See docs/DATA_DOWNLOADS.md.\n'
    (folder / 'START_HERE.txt').write_text(
        f'{name}\n\nExtract the entire ZIP before starting {name}.exe. Keep the _internal folder beside the program. Python installation is not required.\n'
        'For 64-bit Windows 10/11. Choose your own compatible save/archive in the GUI. Keep a backup before editing.\n'
        + extra + '\nProject: https://github.com/nutsamasan/srw-ogmd-tools\n'
        + f'Corresponding project source: https://github.com/nutsamasan/srw-ogmd-tools/tree/{revision}\n'
        + 'Dependency source download links and replacement/rebuild instructions: docs/DEPENDENCY_SOURCES.md\n', encoding='utf8')
    (folder / 'BUILD_INFO.json').write_text(json.dumps(dict(source_revision=revision, python=sys.version.split()[0],
        packages=versions, tool=key, format='PyInstaller onedir', game_resources_bundled=False), indent=2)+'\n', encoding='utf8')
    archive = output / f'{name}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zip_file:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                zip_file.write(path, path.relative_to(folder.parent))
    with archive.open('rb') as source:
        digest=hashlib.file_digest(source, 'sha256').hexdigest()
    return archive, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'windows')
    parser.add_argument('--tool', choices=['all', *TOOLS], default='all')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--package-only', action='store_true')
    args = parser.parse_args()
    if args.build_only and args.package_only:
        parser.error('Choose only one of --build-only and --package-only')
    output = args.output.resolve()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not args.build_only and subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        parser.error('Commit source changes before creating release ZIPs')
    checksums = []
    for key in TOOLS if args.tool == 'all' else [args.tool]:
        print(f'Processing {key}', flush=True)
        if not args.package_only:
            build(key, output)
        if not args.build_only:
            archive, digest = package(key, output, revision)
            checksums.append(f'{digest}  {archive.name}')
            print(f'Created {archive.name} ({archive.stat().st_size:,} bytes)', flush=True)
    if checksums:
        (output / 'SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n', encoding='utf8')


if __name__ == '__main__':
    main()
