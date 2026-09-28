"""Safe read/write support for Super Robot Wars OG: The Moon Dwellers RPCS3 scenario saves.

Only fields whose location has been confirmed across multiple real saves belong
in this module.  Unknown fields must remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from contextvars import ContextVar
from functools import wraps
import hashlib
from datetime import datetime
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
from typing import Final, Mapping


SCENARIO_PREFIX: Final = "BLJS10335_OMI-SCN"
SYSDATA_NAME: Final = "SYSDATA.SAV"
PARMDAT_NAME: Final = "PARMDAT.SAV"
PARAM_SFO_NAME: Final = "PARAM.SFO"
SYSDATA_SIZE: Final = 26_164
PARMDAT_SIZE: Final = 137_624
CURRENT_FUNDS_OFFSET: Final = 0x280
TOTAL_FUNDS_OFFSET: Final = 0x284
MAX_FUNDS: Final = 99_999_999
PART_AVAILABLE_OFFSET: Final = 0x529
PART_TOTAL_OFFSET: Final = 0x64D
PART_COUNT: Final = 43
PART_LOCKED: Final = 0xFF
MAX_PARTS: Final = 99
ABILITY_AVAILABLE_OFFSET: Final = 0x56A
ABILITY_TOTAL_OFFSET: Final = 0x68E
ABILITY_COUNT: Final = 21
MAX_ABILITIES: Final = 32_767
ABILITY_STOCK_TARGET: Final = 99
WEAPON_MASK_OFFSET: Final = 0x20454
WEAPON_MASK_WORD_COUNT: Final = 8
WEAPON_SLOT_BASE: Final = 0x20475
WEAPON_SLOT_STRIDE: Final = 3
WEAPON_SLOT_COUNT: Final = 255
WEAPON_TARGET_COPIES: Final = 4
WEAPON_EQUIPPED_FLAG: Final = 0x08
WEAPON_NEW_FLAG: Final = 0x04
PILOT_RECORD_BASE: Final = 0x1BC44
PILOT_RECORD_STRIDE: Final = 0x48
# All 256 Moon Dwellers records end at 0x20444, before the weapon table.
PILOT_RECORD_COUNT: Final = 256
PILOT_ID_IN_RECORD: Final = 0x0C
PILOT_KILLS_IN_RECORD: Final = 0x12
PILOT_EXPERIENCE_IN_RECORD: Final = 0x14
PILOT_PP_IN_RECORD: Final = 0x16
MAX_KILLS: Final = 999
MAX_PP: Final = 9_999

import json

_CATALOG = json.loads((Path(__file__).parent / "names.json").read_text(encoding="utf8"))
PART_NAMES: Final = tuple(_CATALOG["parts"])
ABILITY_NAMES: Final = tuple(_CATALOG["abilities"])
WEAPON_NAMES: Final = tuple(_CATALOG["weapons"])
ABILITY_LOCKED: Final = 0xFFFF

_SFO_MAGIC: Final = b"\x00PSF"
_SFO_HEADER = struct.Struct("<4sIIII")
_SFO_INDEX = struct.Struct("<HHIII")
_SFO_STRING_FORMAT: Final = 0x0204
_FUNDS_DETAIL_RE = re.compile(
    r"(?P<prefix>(?:\u8cc7\u91d1|Funds)\s*[:\uff1a]\s*)(?P<value>[0-9]+)", re.IGNORECASE
)


class SaveFormatError(ValueError):
    """Raised when a selected folder is not a supported, internally valid save."""


@dataclass(frozen=True)
class SaveInfo:
    slot_path: Path
    directory_name: str
    title: str
    subtitle: str
    detail: str
    funds: int
    total_funds: int
    metadata_funds: int | None

    @property
    def spent_funds(self) -> int:
        return self.total_funds - self.funds


@dataclass(frozen=True)
class WriteResult:
    save: SaveInfo
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class PilotInfo:
    slot_index: int
    pilot_id: int
    name: str
    kills: int
    experience: int
    pp: int


@dataclass(frozen=True)
class PilotWriteResult:
    pilots: tuple[PilotInfo, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class PartInfo:
    part_id: int
    name: str
    available: int | None
    total_owned: int | None
    locked: bool

    @property
    def equipped(self) -> int:
        if self.available is None or self.total_owned is None:
            return 0
        return self.total_owned - self.available


@dataclass(frozen=True)
class PartWriteResult:
    parts: tuple[PartInfo, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class AbilityInfo:
    ability_id: int
    name: str
    available: int
    total_owned: int
    locked: bool = False

    @property
    def equipped(self) -> int:
        return self.total_owned - self.available


@dataclass(frozen=True)
class AbilityWriteResult:
    abilities: tuple[AbilityInfo, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class WeaponCopy:
    slot_index: int
    weapon_id: int
    status: int

    @property
    def upgrade_level(self) -> int:
        return self.status >> 4

    @property
    def equipped(self) -> bool:
        return bool(self.status & WEAPON_EQUIPPED_FLAG)

    @property
    def newly_acquired(self) -> bool:
        return bool(self.status & WEAPON_NEW_FLAG)


@dataclass(frozen=True)
class WeaponInfo:
    weapon_id: int
    name: str
    copies: tuple[WeaponCopy, ...]

    @property
    def total_owned(self) -> int:
        return len(self.copies)

    @property
    def equipped(self) -> int:
        return sum(copy.equipped for copy in self.copies)

    @property
    def available(self) -> int:
        return self.total_owned - self.equipped


@dataclass(frozen=True)
class WeaponWriteResult:
    weapons: tuple[WeaponInfo, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class _SfoEntry:
    key: str
    format: int
    data_length: int
    max_length: int
    data_offset: int
    index_offset: int


class _SfoDocument:
    def __init__(self, payload: bytes):
        self.payload = bytearray(payload)
        if len(payload) < _SFO_HEADER.size:
            raise SaveFormatError("PARAM.SFO is too small.")

        magic, _version, key_start, data_start, entry_count = _SFO_HEADER.unpack_from(payload)
        if magic != _SFO_MAGIC:
            raise SaveFormatError("PARAM.SFO does not have a valid PSF header.")
        if key_start >= len(payload) or data_start >= len(payload):
            raise SaveFormatError("PARAM.SFO table offsets are outside the file.")
        if entry_count > 1_024:
            raise SaveFormatError("PARAM.SFO has an unreasonable entry count.")

        self.key_start = key_start
        self.data_start = data_start
        self.entries: dict[str, _SfoEntry] = {}
        for index in range(entry_count):
            index_offset = _SFO_HEADER.size + index * _SFO_INDEX.size
            if index_offset + _SFO_INDEX.size > len(payload):
                raise SaveFormatError("PARAM.SFO index table is truncated.")
            key_offset, data_format, data_length, max_length, data_offset = _SFO_INDEX.unpack_from(
                payload, index_offset
            )
            key_pos = key_start + key_offset
            if key_pos >= len(payload):
                raise SaveFormatError("PARAM.SFO key offset is outside the file.")
            key_end = payload.find(b"\0", key_pos)
            if key_end < 0 or key_end >= data_start:
                raise SaveFormatError("PARAM.SFO contains an unterminated key.")
            try:
                key = payload[key_pos:key_end].decode("ascii")
            except UnicodeDecodeError as exc:
                raise SaveFormatError("PARAM.SFO contains a non-ASCII key.") from exc

            value_pos = data_start + data_offset
            if data_length > max_length or value_pos + max_length > len(payload):
                raise SaveFormatError(f"PARAM.SFO value bounds are invalid for {key!r}.")
            self.entries[key] = _SfoEntry(
                key=key,
                format=data_format,
                data_length=data_length,
                max_length=max_length,
                data_offset=data_offset,
                index_offset=index_offset,
            )

    def get_string(self, key: str, *, required: bool = False) -> str:
        entry = self.entries.get(key)
        if entry is None:
            if required:
                raise SaveFormatError(f"PARAM.SFO is missing {key}.")
            return ""
        if entry.format != _SFO_STRING_FORMAT:
            raise SaveFormatError(f"PARAM.SFO entry {key} is not a string.")
        start = self.data_start + entry.data_offset
        raw = bytes(self.payload[start : start + entry.data_length]).rstrip(b"\0")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SaveFormatError(f"PARAM.SFO entry {key} is not valid UTF-8.") from exc

    def set_string(self, key: str, value: str) -> None:
        entry = self.entries.get(key)
        if entry is None:
            raise SaveFormatError(f"PARAM.SFO is missing {key}.")
        if entry.format != _SFO_STRING_FORMAT:
            raise SaveFormatError(f"PARAM.SFO entry {key} is not a string.")
        encoded = value.encode("utf-8") + b"\0"
        if len(encoded) > entry.max_length:
            raise SaveFormatError(
                f"Updated {key} needs {len(encoded)} bytes, but only {entry.max_length} are available."
            )
        start = self.data_start + entry.data_offset
        self.payload[start : start + entry.max_length] = b"\0" * entry.max_length
        self.payload[start : start + len(encoded)] = encoded
        struct.pack_into("<I", self.payload, entry.index_offset + 4, len(encoded))

    def to_bytes(self) -> bytes:
        return bytes(self.payload)


def _metadata_funds(detail: str) -> int | None:
    match = _FUNDS_DETAIL_RE.search(detail)
    return int(match.group("value")) if match else None


def _updated_detail(detail: str, funds: int) -> str:
    if not _FUNDS_DETAIL_RE.search(detail):
        raise SaveFormatError("PARAM.SFO DETAIL does not contain a recognizable funds value.")
    return _FUNDS_DETAIL_RE.sub(lambda match: f"{match.group('prefix')}{funds}", detail, count=1)


def _read_sysdata_funds(payload: bytes) -> tuple[int, int]:
    if len(payload) != SYSDATA_SIZE:
        raise SaveFormatError(
            f"{SYSDATA_NAME} is {len(payload)} bytes; expected exactly {SYSDATA_SIZE}."
        )
    current_funds = struct.unpack_from(">I", payload, CURRENT_FUNDS_OFFSET)[0]
    total_funds = struct.unpack_from(">I", payload, TOTAL_FUNDS_OFFSET)[0]
    if max(current_funds, total_funds) > 0x7FFFFFFF:
        raise SaveFormatError("Funds exceed the game's signed 32-bit range.")
    if total_funds < current_funds:
        raise SaveFormatError(
            f"The funds ledger total at 0x{TOTAL_FUNDS_OFFSET:X} ({total_funds}) is lower than "
            f"current funds at 0x{CURRENT_FUNDS_OFFSET:X} ({current_funds})."
        )
    return current_funds, total_funds


def _load_documents(slot_path: Path) -> tuple[bytes, _SfoDocument]:
    sysdata_path = slot_path / SYSDATA_NAME
    sfo_path = slot_path / PARAM_SFO_NAME
    if not sysdata_path.is_file() or not sfo_path.is_file():
        raise SaveFormatError(f"The folder must contain {SYSDATA_NAME} and {PARAM_SFO_NAME}.")
    try:
        sysdata = sysdata_path.read_bytes()
        sfo = _SfoDocument(sfo_path.read_bytes())
    except OSError as exc:
        raise SaveFormatError(f"Could not read the selected save: {exc}") from exc
    return sysdata, sfo


def _read_parmdat(slot_path: Path) -> bytes:
    path = slot_path / PARMDAT_NAME
    if not path.is_file():
        raise SaveFormatError(f"The folder must contain {PARMDAT_NAME}.")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SaveFormatError(f"Could not read {PARMDAT_NAME}: {exc}") from exc
    if len(payload) != PARMDAT_SIZE:
        raise SaveFormatError(
            f"{PARMDAT_NAME} is {len(payload)} bytes; expected exactly {PARMDAT_SIZE}."
        )
    records_end = PILOT_RECORD_BASE + PILOT_RECORD_COUNT * PILOT_RECORD_STRIDE
    if records_end > len(payload):
        raise SaveFormatError("The pilot-record table extends outside PARMDAT.SAV.")
    return payload


@lru_cache(maxsize=1)
def load_pilot_names() -> dict[int, str]:
    return {int(key): value for key, value in _CATALOG["pilots"].items()}


def load_save(slot: str | os.PathLike[str]) -> SaveInfo:
    slot_path = Path(slot).expanduser().resolve()
    if not slot_path.is_dir():
        raise SaveFormatError("The selected save folder does not exist.")

    sysdata, sfo = _load_documents(slot_path)
    sfo_directory = sfo.get_string("SAVEDATA_DIRECTORY", required=True)
    if not slot_path.name.startswith(SCENARIO_PREFIX) or not sfo_directory.startswith(SCENARIO_PREFIX):
        raise SaveFormatError("Only BLJS10335 OG Moon Dwellers scenario saves are supported; system saves are excluded.")
    if sfo_directory != slot_path.name:
        raise SaveFormatError(
            f"Save folder name {slot_path.name!r} does not match PARAM.SFO name {sfo_directory!r}."
        )

    funds, total_funds = _read_sysdata_funds(sysdata)
    detail = sfo.get_string("DETAIL", required=True)
    metadata_funds = _metadata_funds(detail)
    if metadata_funds is not None and metadata_funds != funds:
        raise SaveFormatError(
            f"Funds disagree between {SYSDATA_NAME} ({funds}) and PARAM.SFO ({metadata_funds})."
        )
    return SaveInfo(
        slot_path=slot_path,
        directory_name=sfo_directory,
        title=sfo.get_string("TITLE"),
        subtitle=sfo.get_string("SUB_TITLE"),
        detail=detail,
        funds=funds,
        total_funds=total_funds,
        metadata_funds=metadata_funds,
    )


def load_pilots(slot: str | os.PathLike[str]) -> tuple[PilotInfo, ...]:
    save = load_save(slot)
    payload = _read_parmdat(save.slot_path)
    names = load_pilot_names()
    pilots: list[PilotInfo] = []
    seen_ids: set[int] = set()
    for slot_index in range(PILOT_RECORD_COUNT):
        record = PILOT_RECORD_BASE + slot_index * PILOT_RECORD_STRIDE
        pilot_id = struct.unpack_from(">H", payload, record + PILOT_ID_IN_RECORD)[0]
        if pilot_id == 0:
            continue
        if pilot_id not in names:
            raise SaveFormatError(f"Unknown pilot ID 0x{pilot_id:X}; this layout may be unsupported.")
        if pilot_id in seen_ids:
            raise SaveFormatError(f"Pilot ID 0x{pilot_id:02X} appears more than once in PARMDAT.SAV.")
        seen_ids.add(pilot_id)
        kills = struct.unpack_from(">H", payload, record + PILOT_KILLS_IN_RECORD)[0]
        experience = struct.unpack_from(">H", payload, record + PILOT_EXPERIENCE_IN_RECORD)[0]
        pp = struct.unpack_from(">H", payload, record + PILOT_PP_IN_RECORD)[0]
        pilots.append(
            PilotInfo(
                slot_index=slot_index,
                pilot_id=pilot_id,
                name=names.get(pilot_id, f"Pilot 0x{pilot_id:02X}"),
                kills=kills,
                experience=experience,
                pp=pp,
            )
        )
    return tuple(pilots)


def _read_parts(payload: bytes) -> tuple[PartInfo, ...]:
    if len(payload) != SYSDATA_SIZE:
        raise SaveFormatError(
            f"{SYSDATA_NAME} is {len(payload)} bytes; expected exactly {SYSDATA_SIZE}."
        )
    parts: list[PartInfo] = []
    for index, name in enumerate(PART_NAMES):
        part_id = index + 1
        available_raw = payload[PART_AVAILABLE_OFFSET + index]
        total_raw = payload[PART_TOTAL_OFFSET + index]
        if available_raw == PART_LOCKED or total_raw == PART_LOCKED:
            if available_raw != PART_LOCKED or total_raw != PART_LOCKED:
                raise SaveFormatError(
                    f"Part {part_id} ({name}) has mismatched locked markers "
                    f"({available_raw} vs {total_raw})."
                )
            parts.append(
                PartInfo(part_id=part_id, name=name, available=None, total_owned=None, locked=True)
            )
            continue
        if total_raw > MAX_PARTS:
            raise SaveFormatError(
                f"Part {part_id} ({name}) has an unsupported total count of {total_raw}."
            )
        if available_raw > total_raw:
            raise SaveFormatError(
                f"Part {part_id} ({name}) has {available_raw} available but only {total_raw} total."
            )
        parts.append(
            PartInfo(
                part_id=part_id,
                name=name,
                available=available_raw,
                total_owned=total_raw,
                locked=False,
            )
        )
    return tuple(parts)


def load_parts(slot: str | os.PathLike[str]) -> tuple[PartInfo, ...]:
    save = load_save(slot)
    sysdata, _sfo = _load_documents(save.slot_path)
    return _read_parts(sysdata)


def _read_abilities(payload: bytes) -> tuple[AbilityInfo, ...]:
    if len(payload) != SYSDATA_SIZE:
        raise SaveFormatError(
            f"{SYSDATA_NAME} is {len(payload)} bytes; expected exactly {SYSDATA_SIZE}."
        )
    abilities: list[AbilityInfo] = []
    for index, name in enumerate(ABILITY_NAMES):
        ability_id = index + 1
        available = struct.unpack_from(">H", payload, ABILITY_AVAILABLE_OFFSET + index * 2)[0]
        total_owned = struct.unpack_from(">H", payload, ABILITY_TOTAL_OFFSET + index * 2)[0]
        if available == ABILITY_LOCKED or total_owned == ABILITY_LOCKED:
            if available != total_owned:
                raise SaveFormatError(f"Ability {ability_id} has mismatched locked markers.")
            abilities.append(AbilityInfo(ability_id, name, 0, 0, True))
            continue
        if available > MAX_ABILITIES or total_owned > MAX_ABILITIES:
            raise SaveFormatError(f"Ability {ability_id} exceeds its signed 16-bit counter.")
        if available > total_owned:
            raise SaveFormatError(
                f"Ability {ability_id} ({name}) has {available} available but only "
                f"{total_owned} total."
            )
        abilities.append(
            AbilityInfo(
                ability_id=ability_id,
                name=name,
                available=available,
                total_owned=total_owned,
            )
        )
    return tuple(abilities)


def load_abilities(slot: str | os.PathLike[str]) -> tuple[AbilityInfo, ...]:
    save = load_save(slot)
    sysdata, _sfo = _load_documents(save.slot_path)
    return _read_abilities(sysdata)


def _weapon_slot_is_occupied(payload: bytes, slot_index: int) -> bool:
    word_offset = WEAPON_MASK_OFFSET + (slot_index // 32) * 4
    word = struct.unpack_from(">I", payload, word_offset)[0]
    return bool(word & (1 << (slot_index % 32)))


def _set_weapon_slot_occupied(payload: bytearray, slot_index: int) -> None:
    word_offset = WEAPON_MASK_OFFSET + (slot_index // 32) * 4
    word = struct.unpack_from(">I", payload, word_offset)[0]
    struct.pack_into(">I", payload, word_offset, word | (1 << (slot_index % 32)))


def _read_weapons(payload: bytes) -> tuple[WeaponInfo, ...]:
    if len(payload) != PARMDAT_SIZE:
        raise SaveFormatError(
            f"{PARMDAT_NAME} is {len(payload)} bytes; expected exactly {PARMDAT_SIZE}."
        )
    records_end = WEAPON_SLOT_BASE + WEAPON_SLOT_COUNT * WEAPON_SLOT_STRIDE
    mask_end = WEAPON_MASK_OFFSET + WEAPON_MASK_WORD_COUNT * 4
    if records_end > len(payload) or mask_end > len(payload):
        raise SaveFormatError("The replacement-weapon inventory extends outside PARMDAT.SAV.")

    last_mask_word = struct.unpack_from(
        ">I", payload, WEAPON_MASK_OFFSET + (WEAPON_MASK_WORD_COUNT - 1) * 4
    )[0]
    if last_mask_word & 0x80000000:
        raise SaveFormatError("The replacement-weapon mask uses unsupported slot 255.")

    copies_by_id: dict[int, list[WeaponCopy]] = {
        weapon_id: []
        for weapon_id, name in enumerate(WEAPON_NAMES)
        if weapon_id and name is not None
    }
    valid_status_flags = WEAPON_EQUIPPED_FLAG | WEAPON_NEW_FLAG
    for slot_index in range(WEAPON_SLOT_COUNT):
        record = WEAPON_SLOT_BASE + slot_index * WEAPON_SLOT_STRIDE
        weapon_id, status, padding = payload[record : record + WEAPON_SLOT_STRIDE]
        occupied = _weapon_slot_is_occupied(payload, slot_index)
        if not occupied:
            if weapon_id or status or padding:
                raise SaveFormatError(
                    f"Weapon slot {slot_index} contains data but is not marked occupied."
                )
            continue
        name = WEAPON_NAMES[weapon_id] if weapon_id < len(WEAPON_NAMES) else None
        if name is None:
            raise SaveFormatError(
                f"Weapon slot {slot_index} contains unsupported replacement-weapon ID 0x{weapon_id:02X}."
            )
        if padding != 0:
            raise SaveFormatError(
                f"Weapon slot {slot_index} has an unsupported padding byte of 0x{padding:02X}."
            )
        if status & 0x0F & ~valid_status_flags:
            raise SaveFormatError(
                f"Weapon slot {slot_index} ({name}) has unsupported status 0x{status:02X}."
            )
        copies_by_id[weapon_id].append(
            WeaponCopy(slot_index=slot_index, weapon_id=weapon_id, status=status)
        )

    return tuple(
        WeaponInfo(weapon_id=weapon_id, name=name, copies=tuple(copies_by_id[weapon_id]))
        for weapon_id, name in enumerate(WEAPON_NAMES)
        if weapon_id and name is not None
    )


def load_weapons(slot: str | os.PathLike[str]) -> tuple[WeaponInfo, ...]:
    save = load_save(slot)
    return _read_weapons(_read_parmdat(save.slot_path))


def snapshot_slot(slot: str | os.PathLike[str]) -> dict[str, str]:
    """Fingerprint every file, including files the editor never changes."""
    root = Path(slot).resolve()
    if not root.is_dir():
        raise SaveFormatError("The save folder does not exist.")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise SaveFormatError("Save folders containing links are unsupported.")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise SaveFormatError("The save folder is empty.")
    return result


_TRANSACTION = ContextVar("save_editor_transaction", default=None)


def _guarded_writer(func):
    @wraps(func)
    def guarded(slot, *args, expected_snapshot=None, **kwargs):
        root = Path(slot).resolve()
        lock = root.parent / ("." + root.name + ".editor-lock")
        try:
            handle = lock.open("x")
        except FileExistsError as exc:
            raise SaveFormatError("Another editor write is in progress. If an editor crashed, remove its .editor-lock file after closing it.") from exc
        token = None
        try:
            before = snapshot_slot(root)
            if expected_snapshot is not None and before != expected_snapshot:
                raise SaveFormatError("The save changed after it was loaded. Read the save again before editing.")
            state = {"root": root, "before": before, "expected": dict(before)}
            token = _TRANSACTION.set(state)
            result = func(root, *args, **kwargs)
            after = snapshot_slot(root)
            if after != state["expected"]:
                raise SaveFormatError("The save changed during validation. A full backup is available at " + str(result.backup_path))
            return replace(result, snapshot=after)
        finally:
            if token is not None:
                _TRANSACTION.reset(token)
            handle.close()
            lock.unlink(missing_ok=True)
    return guarded


def _atomic_replace(path: Path, payload: bytes) -> None:
    transaction = _TRANSACTION.get()
    key = path.relative_to(transaction["root"]).as_posix() if transaction else None
    if transaction and hashlib.sha256(path.read_bytes()).hexdigest() != transaction["expected"][key]:
        raise SaveFormatError("The save changed during writing. Load it again; the complete backup is retained.")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        if transaction:
            transaction["expected"][key] = hashlib.sha256(payload).hexdigest()
        if path.read_bytes() != payload:
            raise SaveFormatError(f"Byte-for-byte readback failed for {path.name}.")
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _backup_slot(slot_path: Path) -> Path:
    transaction = _TRANSACTION.get()
    before = transaction["before"] if transaction else snapshot_slot(slot_path)
    if snapshot_slot(slot_path) != before:
        raise SaveFormatError("The save changed while edits were being prepared. Read it again.")
    backup_root = slot_path.parent / "_save_editor_backups"
    backup_root.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_root = backup_root / stamp
    suffix = 1
    while snapshot_root.exists():
        snapshot_root = backup_root / f"{stamp}_{suffix}"
        suffix += 1
    candidate = snapshot_root / slot_path.name
    shutil.copytree(slot_path, candidate)
    if snapshot_slot(candidate) != before or snapshot_slot(slot_path) != before:
        raise SaveFormatError("The save changed during backup. No edit was written; read it again.")
    return candidate


@_guarded_writer
def write_funds(slot: str | os.PathLike[str], funds: int) -> WriteResult:
    if isinstance(funds, bool) or not isinstance(funds, int):
        raise SaveFormatError("Funds must be a whole number.")
    if not 0 <= funds <= MAX_FUNDS:
        raise SaveFormatError(f"Funds must be between 0 and {MAX_FUNDS:,}.")

    before = load_save(slot)
    sysdata, sfo = _load_documents(before.slot_path)
    original_sysdata = bytes(sysdata)
    original_sfo = sfo.to_bytes()

    updated_sysdata = bytearray(sysdata)
    funds_delta = funds - before.funds
    updated_total_funds = before.total_funds + funds_delta
    if not 0 <= updated_total_funds <= 0x7FFFFFFF:
        raise SaveFormatError("The requested change would put the funds ledger outside its valid range.")
    struct.pack_into(">I", updated_sysdata, CURRENT_FUNDS_OFFSET, funds)
    struct.pack_into(">I", updated_sysdata, TOTAL_FUNDS_OFFSET, updated_total_funds)
    if _read_sysdata_funds(updated_sysdata) != (funds, updated_total_funds):
        raise SaveFormatError("Internal validation failed while preparing SYSDATA.SAV.")

    if before.metadata_funds is not None:
        sfo.set_string("DETAIL", _updated_detail(before.detail, funds))
    updated_sfo = sfo.to_bytes()
    check_sfo = _SfoDocument(updated_sfo)
    if before.metadata_funds is not None and _metadata_funds(check_sfo.get_string("DETAIL", required=True)) != funds:
        raise SaveFormatError("Internal validation failed while preparing PARAM.SFO.")

    backup_path = _backup_slot(before.slot_path)
    sysdata_path = before.slot_path / SYSDATA_NAME
    sfo_path = before.slot_path / PARAM_SFO_NAME
    try:
        _atomic_replace(sysdata_path, bytes(updated_sysdata))
        if updated_sfo != original_sfo:
            _atomic_replace(sfo_path, updated_sfo)
        after = load_save(before.slot_path)
        if after.funds != funds or after.total_funds != updated_total_funds:
            raise SaveFormatError("Post-write validation did not read back the requested funds values.")
    except Exception:
        # Restore both originals if either write or post-write validation fails.
        _atomic_replace(sysdata_path, original_sysdata)
        if updated_sfo != original_sfo:
            _atomic_replace(sfo_path, original_sfo)
        raise
    return WriteResult(save=after, backup_path=backup_path)


@_guarded_writer
def write_pilot_stats(
    slot: str | os.PathLike[str],
    *,
    pp_updates: Mapping[int, int] | None = None,
    kill_updates: Mapping[int, int] | None = None,
) -> PilotWriteResult:
    normalized_pp: dict[int, int] = {}
    normalized_kills: dict[int, int] = {}
    for pilot_id, pp in (pp_updates or {}).items():
        if isinstance(pilot_id, bool) or not isinstance(pilot_id, int):
            raise SaveFormatError("Pilot IDs must be whole numbers.")
        if isinstance(pp, bool) or not isinstance(pp, int) or not 0 <= pp <= MAX_PP:
            raise SaveFormatError(f"Pilot PP must be a whole number from 0 through {MAX_PP:,}.")
        normalized_pp[pilot_id] = pp
    for pilot_id, kills in (kill_updates or {}).items():
        if isinstance(pilot_id, bool) or not isinstance(pilot_id, int):
            raise SaveFormatError("Pilot IDs must be whole numbers.")
        if (
            isinstance(kills, bool)
            or not isinstance(kills, int)
            or not 0 <= kills <= MAX_KILLS
        ):
            raise SaveFormatError(
                f"Pilot kill counts must be whole numbers from 0 through {MAX_KILLS}."
            )
        normalized_kills[pilot_id] = kills
    if not normalized_pp and not normalized_kills:
        raise SaveFormatError("No pilot changes were supplied.")

    save = load_save(slot)
    before = load_pilots(save.slot_path)
    by_id = {pilot.pilot_id: pilot for pilot in before}
    requested_ids = set(normalized_pp) | set(normalized_kills)
    missing = sorted(requested_ids - set(by_id))
    if missing:
        joined = ", ".join(f"0x{pilot_id:02X}" for pilot_id in missing)
        raise SaveFormatError(f"These pilot IDs are not recruited in the selected save: {joined}.")

    parmdat_path = save.slot_path / PARMDAT_NAME
    original = _read_parmdat(save.slot_path)
    updated = bytearray(original)
    for pilot_id in requested_ids:
        pilot = by_id[pilot_id]
        record = PILOT_RECORD_BASE + pilot.slot_index * PILOT_RECORD_STRIDE
        stored_id = struct.unpack_from(">H", updated, record + PILOT_ID_IN_RECORD)[0]
        if stored_id != pilot_id:
            raise SaveFormatError("The pilot table changed while the edit was being prepared.")
        if pilot_id in normalized_kills:
            struct.pack_into(">H", updated, record + PILOT_KILLS_IN_RECORD, normalized_kills[pilot_id])
        if pilot_id in normalized_pp:
            struct.pack_into(">H", updated, record + PILOT_PP_IN_RECORD, normalized_pp[pilot_id])

    backup_path = _backup_slot(save.slot_path)
    try:
        _atomic_replace(parmdat_path, bytes(updated))
        after = load_pilots(save.slot_path)
        after_by_id = {pilot.pilot_id: pilot for pilot in after}
        for pilot_id, pp in normalized_pp.items():
            if after_by_id[pilot_id].pp != pp:
                raise SaveFormatError(f"Post-write PP validation failed for pilot 0x{pilot_id:02X}.")
        for pilot_id, kills in normalized_kills.items():
            if after_by_id[pilot_id].kills != kills:
                raise SaveFormatError(
                    f"Post-write kill-count validation failed for pilot 0x{pilot_id:02X}."
                )
    except Exception:
        _atomic_replace(parmdat_path, original)
        raise
    return PilotWriteResult(pilots=after, backup_path=backup_path)


def write_pilot_pp(
    slot: str | os.PathLike[str], updates: Mapping[int, int]
) -> PilotWriteResult:
    return write_pilot_stats(slot, pp_updates=updates)


def write_pilot_kills(
    slot: str | os.PathLike[str], updates: Mapping[int, int]
) -> PilotWriteResult:
    return write_pilot_stats(slot, kill_updates=updates)


@_guarded_writer
def write_parts(
    slot: str | os.PathLike[str], updates: Mapping[int, int]
) -> PartWriteResult:
    if not updates:
        raise SaveFormatError("No parts changes were supplied.")
    normalized: dict[int, int] = {}
    for part_id, total_owned in updates.items():
        if isinstance(part_id, bool) or not isinstance(part_id, int) or not 1 <= part_id <= PART_COUNT:
            raise SaveFormatError(f"Part IDs must be whole numbers from 1 through {PART_COUNT}.")
        if (
            isinstance(total_owned, bool)
            or not isinstance(total_owned, int)
            or not 0 <= total_owned <= MAX_PARTS
        ):
            raise SaveFormatError(
                f"Part totals must be whole numbers from 0 through {MAX_PARTS}."
            )
        normalized[part_id] = total_owned

    save = load_save(slot)
    before = load_parts(save.slot_path)
    by_id = {part.part_id: part for part in before}
    sysdata, _sfo = _load_documents(save.slot_path)
    original = bytes(sysdata)
    updated = bytearray(sysdata)
    for part_id, total_owned in normalized.items():
        part = by_id[part_id]
        equipped = part.equipped
        if total_owned < equipped:
            raise SaveFormatError(
                f"{part.name} has {equipped} equipped; its total cannot be set below that value."
            )
        available = total_owned - equipped
        index = part_id - 1
        updated[PART_AVAILABLE_OFFSET + index] = available
        updated[PART_TOTAL_OFFSET + index] = total_owned

    prepared = _read_parts(updated)
    prepared_by_id = {part.part_id: part for part in prepared}
    for part_id, total_owned in normalized.items():
        part = prepared_by_id[part_id]
        if part.total_owned != total_owned or part.equipped != by_id[part_id].equipped:
            raise SaveFormatError(f"Internal parts validation failed for {part.name}.")

    backup_path = _backup_slot(save.slot_path)
    sysdata_path = save.slot_path / SYSDATA_NAME
    try:
        _atomic_replace(sysdata_path, bytes(updated))
        after = load_parts(save.slot_path)
        after_by_id = {part.part_id: part for part in after}
        for part_id, total_owned in normalized.items():
            part = after_by_id[part_id]
            if part.total_owned != total_owned or part.equipped != by_id[part_id].equipped:
                raise SaveFormatError(f"Post-write parts validation failed for {part.name}.")
    except Exception:
        _atomic_replace(sysdata_path, original)
        raise
    return PartWriteResult(parts=after, backup_path=backup_path)


@_guarded_writer
def write_abilities(
    slot: str | os.PathLike[str], updates: Mapping[int, int]
) -> AbilityWriteResult:
    if not updates:
        raise SaveFormatError("No ability changes were supplied.")
    normalized: dict[int, int] = {}
    for ability_id, total_owned in updates.items():
        if (
            isinstance(ability_id, bool)
            or not isinstance(ability_id, int)
            or not 1 <= ability_id <= ABILITY_COUNT
        ):
            raise SaveFormatError(
                f"Ability IDs must be whole numbers from 1 through {ABILITY_COUNT}."
            )
        if (
            isinstance(total_owned, bool)
            or not isinstance(total_owned, int)
            or not 0 <= total_owned <= MAX_ABILITIES
        ):
            raise SaveFormatError(
                f"Ability totals must be whole numbers from 0 through {MAX_ABILITIES}."
            )
        normalized[ability_id] = total_owned

    save = load_save(slot)
    before = load_abilities(save.slot_path)
    by_id = {ability.ability_id: ability for ability in before}
    sysdata, _sfo = _load_documents(save.slot_path)
    original = bytes(sysdata)
    updated = bytearray(sysdata)
    for ability_id, total_owned in normalized.items():
        ability = by_id[ability_id]
        equipped = ability.equipped
        if total_owned < equipped:
            raise SaveFormatError(
                f"{ability.name} has {equipped} equipped; its total cannot be set below that value."
            )
        available = total_owned - equipped
        index = ability_id - 1
        struct.pack_into(">H", updated, ABILITY_AVAILABLE_OFFSET + index * 2, available)
        struct.pack_into(">H", updated, ABILITY_TOTAL_OFFSET + index * 2, total_owned)

    prepared = _read_abilities(updated)
    prepared_by_id = {ability.ability_id: ability for ability in prepared}
    for ability_id, total_owned in normalized.items():
        ability = prepared_by_id[ability_id]
        if ability.total_owned != total_owned or ability.equipped != by_id[ability_id].equipped:
            raise SaveFormatError(f"Internal ability validation failed for {ability.name}.")

    backup_path = _backup_slot(save.slot_path)
    sysdata_path = save.slot_path / SYSDATA_NAME
    try:
        _atomic_replace(sysdata_path, bytes(updated))
        after = load_abilities(save.slot_path)
        after_by_id = {ability.ability_id: ability for ability in after}
        for ability_id, total_owned in normalized.items():
            ability = after_by_id[ability_id]
            if ability.total_owned != total_owned or ability.equipped != by_id[ability_id].equipped:
                raise SaveFormatError(f"Post-write ability validation failed for {ability.name}.")
    except Exception:
        _atomic_replace(sysdata_path, original)
        raise
    return AbilityWriteResult(abilities=after, backup_path=backup_path)


@_guarded_writer
def write_weapon_totals(
    slot: str | os.PathLike[str], updates: Mapping[int, int]
) -> WeaponWriteResult:
    """Add unequipped level-0 copies until each requested total is reached.

    Existing weapon-instance records are never modified or removed. This is
    intentionally stricter than the parts and ability editors because weapon
    inventory stores per-copy upgrade and equipped flags.
    """
    if not updates:
        raise SaveFormatError("No weapon changes were supplied.")
    valid_ids = {
        weapon_id for weapon_id, name in enumerate(WEAPON_NAMES) if weapon_id and name is not None
    }
    normalized: dict[int, int] = {}
    for weapon_id, total_owned in updates.items():
        if isinstance(weapon_id, bool) or not isinstance(weapon_id, int) or weapon_id not in valid_ids:
            raise SaveFormatError("The replacement-weapon ID is not supported by OG Moon Dwellers.")
        if (
            isinstance(total_owned, bool)
            or not isinstance(total_owned, int)
            or not 0 <= total_owned <= WEAPON_TARGET_COPIES
        ):
            raise SaveFormatError(
                f"Weapon targets must be whole numbers from 0 through {WEAPON_TARGET_COPIES}."
            )
        normalized[weapon_id] = total_owned

    save = load_save(slot)
    original = _read_parmdat(save.slot_path)
    before = _read_weapons(original)
    before_by_id = {weapon.weapon_id: weapon for weapon in before}
    additions: list[int] = []
    for weapon_id, total_owned in sorted(normalized.items()):
        weapon = before_by_id[weapon_id]
        if total_owned < weapon.total_owned:
            raise SaveFormatError(
                f"{weapon.name} already has {weapon.total_owned} copies. "
                "Weapon editing is add-only, so existing copies cannot be removed."
            )
        additions.extend([weapon_id] * (total_owned - weapon.total_owned))
    if not additions:
        raise SaveFormatError("The selected weapon totals do not require any new copies.")

    free_slots = [
        slot_index
        for slot_index in range(WEAPON_SLOT_COUNT)
        if not _weapon_slot_is_occupied(original, slot_index)
    ]
    if len(additions) > len(free_slots):
        raise SaveFormatError(
            f"The weapon inventory needs {len(additions)} free slots, but only {len(free_slots)} remain."
        )

    updated = bytearray(original)
    for weapon_id, slot_index in zip(additions, free_slots):
        record = WEAPON_SLOT_BASE + slot_index * WEAPON_SLOT_STRIDE
        if any(updated[record : record + WEAPON_SLOT_STRIDE]):
            raise SaveFormatError(f"Weapon slot {slot_index} changed while the edit was prepared.")
        updated[record : record + WEAPON_SLOT_STRIDE] = bytes((weapon_id, 0, 0))
        _set_weapon_slot_occupied(updated, slot_index)

    prepared = _read_weapons(updated)
    prepared_by_id = {weapon.weapon_id: weapon for weapon in prepared}
    for weapon_id, total_owned in normalized.items():
        if prepared_by_id[weapon_id].total_owned != total_owned:
            raise SaveFormatError(
                f"Internal weapon validation failed for {prepared_by_id[weapon_id].name}."
            )
    for weapon in before:
        for copy in weapon.copies:
            record = WEAPON_SLOT_BASE + copy.slot_index * WEAPON_SLOT_STRIDE
            if updated[record : record + WEAPON_SLOT_STRIDE] != original[
                record : record + WEAPON_SLOT_STRIDE
            ]:
                raise SaveFormatError(f"An existing {weapon.name} record was changed unexpectedly.")

    backup_path = _backup_slot(save.slot_path)
    parmdat_path = save.slot_path / PARMDAT_NAME
    try:
        _atomic_replace(parmdat_path, bytes(updated))
        after = load_weapons(save.slot_path)
        after_by_id = {weapon.weapon_id: weapon for weapon in after}
        for weapon_id, total_owned in normalized.items():
            if after_by_id[weapon_id].total_owned != total_owned:
                raise SaveFormatError(
                    f"Post-write weapon validation failed for {after_by_id[weapon_id].name}."
                )
        for weapon in before:
            old_copies = weapon.copies
            new_existing_copies = tuple(
                copy
                for copy in after_by_id[weapon.weapon_id].copies
                if copy.slot_index in {old.slot_index for old in old_copies}
            )
            if new_existing_copies != old_copies:
                raise SaveFormatError(
                    f"Post-write validation found a changed existing {weapon.name} record."
                )
    except Exception:
        _atomic_replace(parmdat_path, original)
        raise
    return WeaponWriteResult(weapons=after, backup_path=backup_path)
