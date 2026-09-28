"""Write the verified battle-caption correction to a separate test ISO."""
import json
import shutil
import sys
from build_battle_caption_path_fix import ROOT,OUT
sys.path.insert(0,str(ROOT/'work/pydeps'))
import native_eboot
from full_patch import prepare_font_patch,write_full_game
from core import atomic_json

ELF_SHA='33e4921cd0dbbd17561b41efe6c71c8401eb03df41d2cb034e946709816a09be'
BOOT_SHA='5ea79e05ea21b95cf125f8eafb0ade7c5727cf52fc896a7745ff27f9e92c32d7'
PPU='PPU-e4fb2176bc44ea94a0db21c0784a5ec9e47a8e1b'
SOURCE=ROOT/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan) - Full English.iso'
OUTPUT=ROOT/'PS3/OGMD Full English - Battle Caption Fix Test.iso'


def main():
    checks=json.loads((OUT/'verification.json').read_text(encoding='utf8'))
    assert checks['status']=='passed' and checks['native_caller_cases']==35 and checks['elf_sha256']==ELF_SHA
    assert not OUTPUT.exists(),'Existing output is never overwritten.'
    native_eboot.KNOWN_ELFS[ELF_SHA]=PPU
    native_eboot.KNOWN_BOOTS.add(BOOT_SHA)
    info,_=native_eboot.load_asset(OUT/'native_eboot')
    assert (info['sha256'],info['elf_sha256'],info['ppu'])==(BOOT_SHA,ELF_SHA,PPU)
    shutil.copy2(ROOT/'full_patcher/data/install_icon.png',OUT/'install_icon.png')
    release=json.loads((ROOT/'full_patcher/data/release.json').read_text(encoding='utf8'))
    atomic_json(OUT/'release.json',dict(font_mode='embedded-eboot',install_icon_sha256=release['install_icon_sha256']))
    def progress(message):print(message,flush=True)
    manifest=prepare_font_patch(OUT,SOURCE,OUT.with_name(OUT.name+'_iso_build'),progress)
    result=write_full_game(manifest,OUTPUT,progress)
    atomic_json(ROOT/'reports/battle_caption_path_fix_20260920.json',dict(
        status='offline and ISO verified; fresh user visual test pending',
        issue='The reported line uses the plain-text battle renderer, which lacked the existing fitting hook.',
        correction='Set a scoped caption-width limit after speaker-name rendering, before the three caption lines.',
        source=str(SOURCE),output=str(OUTPUT),verification=result,
        runtime_evidence=str(ROOT/'work/poc/battle_trace_20260920_v2/capture_20260920T070837114136Z/capture.json'),
        regression_report=str(OUT/'verification.json'),in_game_visual_test=False,
        installed_game_modified=False,shipping_patcher_modified=False,emulator_started=False))
    (ROOT/'PS3/Battle Caption Fix Test - Readme.txt').write_text(
        'OGMD Full English - Battle Caption Fix Test.iso\n\n'
        'This candidate applies fitting to the plain-text battle-caption path\n'
        'identified by the live diagnostic trace. Long caption lines are narrowed\n'
        'to the text area with a right inset; the speaker name keeps its sizing.\n'
        'Both full-width and compact windows and all three lines are covered.\n\n'
        'Fresh-boot this ISO in RPCS3, reach Azuki\'s "All hands,brace for impact\n'
        'and deploy anti-glare measures!" line, and leave the game paused.\n'
        'An old savestate retains the previous executable.\n\n'
        'Offline native-code and complete ISO checks passed. In-game appearance\n'
        'still needs confirmation. The diagnostic recorder is retained for this test.\n'
        'The original Full English ISO, installed archives and shipping patchers\n'
        'were preserved. This executable is for RPCS3 only.\n',encoding='utf8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
