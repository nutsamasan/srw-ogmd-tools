"""Put the verified tighter apostrophe EBOOT into a separate, checked test ISO."""
import json
import re
import shutil
from build_tighter_apostrophe_test import ROOT, OUT
import native_eboot
from core import atomic_json
from full_patch import prepare_font_patch, write_full_game

SOURCE = ROOT/'PS3/OGMD Full English - Battle Caption Fix Test.iso'
OUTPUT = ROOT/'PS3/OGMD Full English - Tighter Apostrophe Test.iso'


def main():
    checks = json.loads((OUT/'verification.json').read_text(encoding='utf8'))
    metadata = json.loads((OUT/'native_eboot/assets.json').read_text(encoding='utf8'))
    assert checks['status'] == 'passed' and checks['native_hook_executions'] == 4008
    assert checks['elf_sha256'] == metadata['elf_sha256']
    assert not OUTPUT.exists()
    # Scope the new candidate to this test builder; shipping allowlists stay unchanged.
    native_eboot.KNOWN_ELFS[metadata['elf_sha256']] = metadata['ppu']
    native_eboot.KNOWN_BOOTS.add(metadata['sha256'])
    native_eboot.load_asset(OUT/'native_eboot')
    shutil.copy2(ROOT/'full_patcher/data/install_icon.png', OUT/'install_icon.png')
    release = json.loads((ROOT/'full_patcher/data/release.json').read_text(encoding='utf8'))
    atomic_json(OUT/'release.json', dict(font_mode='embedded-eboot',
                                       install_icon_sha256=release['install_icon_sha256']))
    last = -1

    def progress(message):
        nonlocal last
        match = re.search(r'Writing patched ISO: (\d+)%', message)
        if match:
            bucket = int(match[1])//10
            if bucket == last:
                return
            last = bucket
        print(message, flush=True)

    manifest = prepare_font_patch(OUT, SOURCE, OUT.with_name(OUT.name+'_iso_build'), progress)
    result = write_full_game(manifest, OUTPUT, progress)
    atomic_json(ROOT/'reports/tighter_apostrophe_20260922.json', dict(
        status='native execution and ISO verified; in-game visual confirmation pending',
        source=str(SOURCE), output=str(OUTPUT), verification=result,
        old_apostrophe_advance=13, new_apostrophe_advance=10,
        word_space_advance_unchanged=True, installed_archives_modified=False,
        editor_project_modified=False, shipping_tools_modified=False,
        real_game_visual_test=False, native_verification=str(OUT/'verification.json')))
    (ROOT/'PS3/Tighter Apostrophe Test - Readme.txt').write_text(
        'OGMD Full English - Tighter Apostrophe Test.iso\n\n'
        'A small font-spacing comparison: ASCII apostrophe advance is 10 units\n'
        'instead of 13 in the known 32-unit native font. At 24-pixel text size\n'
        'this removes 2.25 pixels after each apostrophe. Word spaces, glyph\n'
        'textures and the existing battle-caption fix are preserved.\n\n'
        'Fresh-boot this ISO in the same RPCS3 installation and load a normal\n'
        'in-game save. Compare adults\' discussions and a contraction such as\n'
        'I\'ve. Existing emulator savestates retain the earlier executable.\n\n'
        'The current installed English archives, including the earlier five\n'
        'text corrections, are unchanged and continue to be used. No font YAML\n'
        'is needed. Original ISO preserved. This is an RPCS3-only test build.\n\n'
        'Native-code and full-ISO checks passed; visual confirmation is pending.\n'
        'To undo the comparison, boot the previous Battle Caption Fix Test ISO.\n',
        encoding='utf8')
    print(json.dumps(dict(output=str(OUTPUT), status=result['status'],
                         sha256=result['output_sha256'], source_preserved=result['source_preserved'])))


if __name__ == '__main__':
    main()
