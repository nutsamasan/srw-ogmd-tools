"""Write a separate, fully verified test ISO using the existing guarded writer."""
import json
import shutil
import sys
from pathlib import Path
from build_battle_fit_cache_fix import ROOT, OUT
sys.path.insert(0,str(ROOT/'work/pydeps'))
import native_eboot
from full_patch import prepare_font_patch, write_full_game
from core import atomic_json

ELF_SHA='8550a9849ba09bafc880c8ef4bf8cc1e492f80da74ce950eb04906f58a71b6f1'
BOOT_SHA='5732c4c733fe90e989a9efdfbfe91a931794b9f5e66975a6e38485d4b5bc90dc'
PPU='PPU-5effab33c3d4be07cfb1b9f8eba2d1f570811071'
SOURCE=ROOT/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan) - Full English.iso'
OUTPUT=ROOT/'PS3/OGMD Full English - Battle Fit Test.iso'


def main():
    checks=json.loads((OUT/'verification.json').read_text(encoding='utf8'))
    assert checks['status']=='passed' and checks['draw_cases']==108
    assert not OUTPUT.exists(), 'Existing output is never overwritten.'
    # Restrict this isolated builder to the exact candidate that passed the tests.
    # The shipping patcher, its allowlist, and all release assets remain unchanged.
    native_eboot.KNOWN_ELFS[ELF_SHA]=PPU
    native_eboot.KNOWN_BOOTS.add(BOOT_SHA)
    info,_=native_eboot.load_asset(OUT/'native_eboot')
    assert (info['sha256'],info['elf_sha256'],info['ppu'])==(BOOT_SHA,ELF_SHA,PPU)
    shutil.copy2(ROOT/'full_patcher/data/install_icon.png',OUT/'install_icon.png')
    release=json.loads((ROOT/'full_patcher/data/release.json').read_text(encoding='utf8'))
    atomic_json(OUT/'release.json',dict(font_mode='embedded-eboot',
        install_icon_sha256=release['install_icon_sha256']))
    def progress(message):print(message,flush=True)
    manifest=prepare_font_patch(OUT,SOURCE,OUT.with_name(OUT.name+'_iso_build'),progress)
    result=write_full_game(manifest,OUTPUT,progress)
    atomic_json(ROOT/'reports/battle_fit_cache_fix_20260918.json',dict(
        status='offline verified; fresh user visual test pending',
        issue='Stale caption width makes recursive measurement shrink before drawing.',
        correction='Clear cached width before each of the three battle caption lines.',
        source=str(SOURCE),output=str(OUTPUT),verification=result,
        regression_report=str(OUT/'verification.json'),in_game_visual_test=False,
        installed_game_modified=False,shipping_patcher_modified=False,emulator_started=False))
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
