"""Package the checked caption diagnostic as a separate, verified ISO."""
import json
import shutil
import sys
from build_battle_trace import ROOT, OUT
sys.path.insert(0,str(ROOT/'work/pydeps'))
import native_eboot
from full_patch import prepare_font_patch, write_full_game
from core import atomic_json

ELF_SHA='bbfe215fcc54b7a76017d47e4a0881922595d2b4d2e895468264a68f1618b3a0'
BOOT_SHA='9d2d334ba7b1878337cb872a7a1b012b411acac629eef96a4f067da5b5bce307'
PPU='PPU-dc4455702ec56cf1046a3cfee4033dc662c68581'
SOURCE=ROOT/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan) - Full English.iso'
OUTPUT=ROOT/'PS3/OGMD Full English - Battle Trace.iso'


def main():
    checks=json.loads((OUT/'verification.json').read_text(encoding='utf8'))
    assert checks['status']=='passed' and checks['hook_cases']==17 and checks['actual_wrapper_cases']==12
    assert not OUTPUT.exists(), 'Existing output is never overwritten.'
    native_eboot.KNOWN_ELFS[ELF_SHA]=PPU
    native_eboot.KNOWN_BOOTS.add(BOOT_SHA)
    info,_=native_eboot.load_asset(OUT/'native_eboot')
    assert (info['sha256'],info['elf_sha256'],info['ppu'])==(BOOT_SHA,ELF_SHA,PPU)
    shutil.copy2(ROOT/'full_patcher/data/install_icon.png',OUT/'install_icon.png')
    release=json.loads((ROOT/'full_patcher/data/release.json').read_text(encoding='utf8'))
    atomic_json(OUT/'release.json',dict(font_mode='embedded-eboot',install_icon_sha256=release['install_icon_sha256']))
    def progress(message): print(message,flush=True)
    manifest=prepare_font_patch(OUT,SOURCE,OUT.with_name(OUT.name+'_iso_build'),progress)
    result=write_full_game(manifest,OUTPUT,progress)
    atomic_json(ROOT/'reports/battle_trace_20260920.json',dict(
        status='diagnostic ISO offline verified; live caption capture pending',
        purpose='Capture the actual drawing path and font state for the overflowing Azuki caption.',
        visual_overflow_resolved=False,source=str(SOURCE),output=str(OUTPUT),verification=result,
        regression_report=str(OUT/'verification.json'),runtime_capture_tool=str(ROOT/'tools/read_battle_trace.py'),
        installed_game_modified=False,shipping_patcher_modified=False,emulator_started=False))
    (ROOT/'PS3/Battle Trace - Readme.txt').write_text(
        'OGMD Full English - Battle Trace.iso\n\n'
        'Diagnostic build: the dialogue overflow is not yet fixed.\n'
        'Boot this separate ISO normally in RPCS3, reach Azuki\'s\n'
        '"All hands,brace for impact and deploy anti-glare measures!" line,\n'
        'and leave the game paused so the captured drawing state can be read.\n'
        'Use a fresh boot rather than an old savestate.\n\n'
        'The diagnostic records drawing callers, positions, font sizes and widths\n'
        'in a separate bounded memory area. It retains the reported line after\n'
        'it is drawn. The trace disappears when the game is stopped.\n'
        'Only EBOOT.BIN differs from the Full English source ISO; the ISO writer\n'
        'checks all other bytes and all filesystem views.\n'
        'Source ISO, installed game data, saved games and release patchers are preserved.\n'
        'This executable is for RPCS3 only.\n',encoding='utf8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
