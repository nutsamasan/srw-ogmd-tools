"""RPCS3 patch generator for OGMD Spirit/Seishin command testing.

Important: the known EBOOT patch points override a command slot globally. They do
not edit the selected pilot's PARMDAT record and do not persist per-pilot Seishin
IDs into the scenario save.
"""
from __future__ import annotations

from collections.abc import Mapping
import re

DEFAULT_PPU_HASH = "e429bb11d03c2e6a046775179d21169cba555c47"
GAME_SERIAL = "BLJS10335"
GAME_VERSION = "01.00"

# Public OGMD PS3 code locations. Values are complete PowerPC `li` instructions
# with the low 8-bit immediate replaced by the chosen Spirit ID.
SEISHIN_PATCH_POINTS = {
    1: (0x00659084, 0x38000000, "Spirit 1"),
    2: (0x006591B0, 0x38000000, "Spirit 2"),
    3: (0x00659224, 0x39200000, "Spirit 3"),
    4: (0x006592A0, 0x39200000, "Spirit 4"),
    5: (0x0065931C, 0x39200000, "Spirit 5"),
    6: (0x00659398, 0x39600000, "Twin Spirit"),
}

SP_ZERO_POINTS = (
    (0x001EB9B4, 0x38600000),
    (0x001F26A0, 0x38600000),
)
UNLOCK_ALL_POINT = (0x001E397C, 0x38600000)


def parse_spirit_id(value: str | int) -> int:
    if isinstance(value, bool):
        raise ValueError("Spirit ID must be 00 through FF.")
    if isinstance(value, int):
        number = value
    else:
        text = value.strip()
        if not text:
            raise ValueError("Spirit ID is blank.")
        if text.lower().startswith("0x"):
            number = int(text, 16)
        elif re.fullmatch(r"[0-9A-Fa-f]{1,2}", text):
            # Treat the UI as hex by default because the source code lists IDs as nn.
            number = int(text, 16)
        else:
            raise ValueError(f"Invalid Spirit ID {value!r}; use hex 00 through FF.")
    if not 0 <= number <= 0xFF:
        raise ValueError("Spirit ID must be 00 through FF.")
    return number


def normalize_ppu_hash(value: str) -> str:
    text = value.strip()
    if text.upper().startswith("PPU-"):
        text = text[4:]
    if not re.fullmatch(r"[0-9A-Fa-f]{40}", text):
        raise ValueError("PPU hash must be exactly 40 hexadecimal characters.")
    return text.lower()


def build_patch(
    spirit_ids: Mapping[int, str | int | None],
    *,
    ppu_hash: str = DEFAULT_PPU_HASH,
    zero_sp: bool = False,
    unlock_all: bool = False,
) -> str:
    ppu = normalize_ppu_hash(ppu_hash)
    lines: list[tuple[int, int, str]] = []
    for slot in range(1, 7):
        raw = spirit_ids.get(slot)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        spirit_id = parse_spirit_id(raw)
        address, opcode, label = SEISHIN_PATCH_POINTS[slot]
        lines.append((address, opcode | spirit_id, f"{label} = 0x{spirit_id:02X}"))
    if zero_sp:
        lines.extend((address, value, "SP cost = 0") for address, value in SP_ZERO_POINTS)
    if unlock_all:
        address, value = UNLOCK_ALL_POINT
        lines.append((address, value, "Ignore Spirit unlock level"))
    if not lines:
        raise ValueError("Choose at least one Spirit slot or helper option.")

    out = [
        "Version: 1.2",
        f"PPU-{ppu}:",
        "  OGMD Seishin Override - GLOBAL TEST:",
        "    Games:",
        "      Super Robot Wars OG The Moon Dwellers:",
        f"        {GAME_SERIAL}:",
        f"        - '{GAME_VERSION}'",
        "    Author: OGMD Save Editor 1.4",
        "    Patch Version: 1.0",
        "    Notes: >-",
        "      Experimental EBOOT override. Spirit slot replacements affect ALL pilots while",
        "      this patch is enabled; they are not stored per pilot in PARMDAT.SAV.",
        "      Disable the patch to restore the original Spirit commands.",
        "    Patch:",
    ]
    for address, value, comment in lines:
        out.append(f"    - [ be32, 0x{address:08X}, 0x{value:08X} ] # {comment}")
    return "\n".join(out) + "\n"
