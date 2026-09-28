"""Stage release 1.3, retaining the accepted 1.2 translation verbatim."""
from pathlib import Path
import shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json
from full_patch import package_info
from native_eboot import load_asset,MODE
from archive_patch import digest


def main():
    source=ROOT/'full_patcher/data';out=ROOT/'full_patcher/data_v13'
    release=package_info(source)
    if out.exists():raise ValueError('Staging folder already exists; inspect it before rebuilding.')
    out.mkdir()
    for file in source.iterdir():
        if file.is_file() and file.name not in ('release.json','spacing.yml'):shutil.copy2(file,out/file.name)
    shutil.copytree(ROOT/'script_editor/assets/native_eboot',out/'native_eboot')
    info,_=load_asset(out/'native_eboot')
    release.update(release='OGMD Full English 1.3',font_mode=MODE,embedded_eboot_sha256=info['sha256'],
        embedded_elf_sha256=info['elf_sha256'],embedded_ppu=info['ppu'],rpcs3_only=True,
        runtime_note='VWF and apostrophe spacing are embedded in EBOOT. RPCS3 compatibility setup is separate; no font YAML is required. Physical PS3 support is not included.')
    release.pop('spacing_sha256',None)
    release['features']=[x for x in release['features'] if 'proportional spacing' not in x]
    release['features']+=['Embedded VWF and apostrophe spacing; no font YAML required (RPCS3)',
                          'Font fix only mode preserves an existing game translation']
    release['package_bytes']=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    atomic_json(out/'release.json',release);package_info(out)
    for archive in release['archives']:
        for key in ('recipe','blob','metadata'):assert digest(out/archive[key])==digest(source/archive[key])
    print('Release 1.3 staged; all five archive recipes and translation payloads are unchanged.')


if __name__=='__main__':main()
