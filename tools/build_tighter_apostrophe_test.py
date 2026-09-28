"""Build an isolated 10-unit apostrophe candidate from the currently used EBOOT."""
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'script_editor'), str(ROOT/'work/pydeps')]
import build_ogmd_apostrophe_patch as v3
from build_ogmd_native_eboot import file_offset
from build_battle_text_fit import ppu_hash
from native_eboot import extract_elf, sha
from core import atomic_json

BASE = ROOT/'work/poc/battle_caption_path_fix_20260920_v2'
OUT = ROOT/'work/poc/tighter_apostrophe_20260922'
NEW_WIDTH = 10


def branch_target(raw, pc):
    word = struct.unpack('>I', raw)[0]
    assert word >> 26 == 18 and word & 3 == 0
    delta = word & 0x03fffffc
    return pc + (delta-0x04000000 if delta & 0x02000000 else delta)


def build():
    boot = (BASE/'EBOOT.BIN').read_bytes()
    assert sha(boot) == '5ea79e05ea21b95cf125f8eafb0ade7c5727cf52fc896a7745ff27f9e92c32d7'
    elf = extract_elf(boot)
    assert sha(elf) == '33e4921cd0dbbd17561b41efe6c71c8401eb03df41d2cb034e946709816a09be'
    patched = bytearray(elf)
    hooks = []
    changes = []
    for hook, expected, _ in v3.compile_hooks():
        at = file_offset(elf, hook.address)
        payload = branch_target(elf[at:at+4], hook.address)
        pos = file_offset(elf, payload, len(expected)+4)
        assert elf[pos:pos+len(expected)] == expected
        assert branch_target(elf[pos+len(expected):pos+len(expected)+4], payload+len(expected)) == hook.address+4
        code = expected
        if hook.kind != 'bearing':
            old = bytes.fromhex('3940000d')  # li r10,13
            new = struct.pack('>I', 0x39400000 | NEW_WIDTH)
            assert expected.count(old) == 1
            index = expected.index(old)
            assert index % 4 == 0
            code = expected.replace(old, new)
            patched[pos:pos+len(code)] = code
            changes.append(pos+index+3)
        hooks.append(dict(hook_address=hook.address, kind=hook.kind, payload_address=payload,
                          payload_offset=pos, code_size=len(code),
                          before_sha256=sha(expected), after_sha256=sha(code)))
    assert len(changes) == 10
    actual = [i for i, (a, b) in enumerate(zip(elf, patched)) if a != b]
    assert actual == sorted(changes) and len(elf) == len(patched)
    metadata = json.loads((BASE/'native_eboot/assets.json').read_text(encoding='utf8'))
    result = boot[:-len(elf)] + patched
    packed = zlib.compress(result, 9)
    metadata.update(sha256=sha(result), elf_sha256=sha(patched), ppu=ppu_hash(patched),
                    compressed_sha256=sha(packed), tighter_apostrophe_advance=NEW_WIDTH,
                    previous_apostrophe_advance=13, apostrophe_visual_tested=False,
                    font_code_identical_to_user_test=False)
    assets = OUT/'native_eboot'
    assets.mkdir(parents=True, exist_ok=True)
    for path, data in [(OUT/'EBOOT.elf', patched), (OUT/'EBOOT.BIN', result),
                       (assets/'EBOOT.BIN.zlib', packed)]:
        if path.exists():
            assert path.read_bytes() == data
        else:
            path.write_bytes(data)
    atomic_json(assets/'assets.json', metadata)
    atomic_json(OUT/'build.json', dict(status='built; verification pending', asset=metadata,
        source_eboot_sha256=sha(boot), source_elf_sha256=sha(elf), hooks=hooks,
        changed_elf_bytes=changes, unchanged_glyph_geometry=True, unchanged_word_spaces=True,
        unchanged_caption_fitting=True, old_advance=13, new_advance=NEW_WIDTH))
    print(json.dumps(dict(output=str(OUT), changed_bytes=len(changes), ppu=metadata['ppu'])))


if __name__ == '__main__':
    build()
