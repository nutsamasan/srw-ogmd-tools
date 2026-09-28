"""Check embedded EBOOT on a separate full-size English ISO, never install it."""
from pathlib import Path
import json
from full_patch import prepare_font_patch,write_full_game
from core import atomic_json
from iso_image import DiscImage
from native_eboot import extract_elf,sha,ELF_SHA256

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'New folder/Super Robot Taisen OG - The Moon Dwellers (Japan) - Full English.iso'
OUT=ROOT/'script_editor/qa/native_iso_v37'

def main():
    OUT.mkdir(exist_ok=False)
    manifest=prepare_font_patch(ROOT/'full_patcher/data_v13',SOURCE,OUT/'build',lambda m:print(m,flush=True))
    result=write_full_game(manifest,OUT/'QA embedded font.iso',lambda m:print(m,flush=True))
    with DiscImage(OUT/'QA embedded font.iso') as iso:
        elf=extract_elf(b''.join(iso.chunks(iso.file('/PS3_GAME/USRDIR/EBOOT.BIN'))))
        assert sha(elf)==ELF_SHA256
        assert set(iso.views)=={'ISO9660','Joliet','UDF','UDF mirror'}
    result.update(tested_elf_identical=True,game_installed=False,emulator_started=False)
    atomic_json(OUT/'verification.json',result)
    print('Full-size ISO and all four filesystem views verified.',flush=True)

if __name__=='__main__':main()
