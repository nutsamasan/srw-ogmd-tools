"""Locate user-supplied preview resources without bundling game assets."""
from pathlib import Path

PREVIEW_FILES = ('font.bin', 'font_atlas.png', 'tex_13.png')


def missing_preview_files(folder):
    folder = Path(folder)
    return [name for name in PREVIEW_FILES
            if not (folder / name).is_file() or (folder / name).stat().st_size == 0]


def find_preview_assets(candidates):
    for candidate in candidates:
        if candidate and not missing_preview_files(candidate):
            return Path(candidate)
    return None
