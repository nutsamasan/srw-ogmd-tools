"""Current Will in RPCS3 scenario saves; legacy pilot-relative byte 0x2F."""
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from ogmd_save import (SaveFormatError, PilotInfo, load_save, load_pilots, _read_parmdat,
    _guarded_writer, _backup_slot, _atomic_replace, snapshot_slot,
    PILOT_RECORD_BASE, PILOT_RECORD_STRIDE, PARMDAT_NAME, SCENARIO_PREFIX)

WILL_OFFSET = 0x2F
MIN_WILL, MAX_WILL = 50, 200


@dataclass(frozen=True)
class PilotWill:
    pilot: PilotInfo
    will: int


@dataclass(frozen=True)
class WillWriteResult:
    pilots: tuple[PilotWill, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


def discover_saves():
    here = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    path = here/'save_locations.json'
    roots = json.loads(path.read_text(encoding='utf8')) if path.is_file() else []
    found, seen = [], set()
    for root in roots:
        for folder in Path(root).glob(SCENARIO_PREFIX+'*'):
            try:
                if folder.resolve() in seen:
                    continue
                seen.add(folder.resolve())
                item = load_save(folder)
                found.append(((folder/'SYSDATA.SAV').stat().st_mtime_ns, item))
            except (OSError, ValueError):
                continue
    return [item for _, item in sorted(found, key=lambda pair: pair[0], reverse=True)]


def load_will(slot):
    pilots = load_pilots(slot)
    data = _read_parmdat(Path(slot))
    # Pilot section has its own version marker, independently of unit records.
    if data[0x1BC2C:0x1BC30] != b'\x40\x00\x00\x00':
        raise SaveFormatError('Unsupported pilot save version; expected Moon Dwellers 2.0.')
    return tuple(PilotWill(p, data[PILOT_RECORD_BASE+p.slot_index*PILOT_RECORD_STRIDE+WILL_OFFSET]) for p in pilots)


def prepare_will(slot, updates):
    before = {p.pilot.pilot_id: p for p in load_will(slot)}
    original = _read_parmdat(Path(slot))
    output = bytearray(original)
    changed = set()
    for pid, value in updates.items():
        if type(pid) is not int or pid not in before:
            raise SaveFormatError('Choose a pilot present in the selected save.')
        if type(value) is not int or not MIN_WILL <= value <= MAX_WILL:
            raise SaveFormatError('Current Will must be a whole number from 50 to 200.')
        offset = PILOT_RECORD_BASE+before[pid].pilot.slot_index*PILOT_RECORD_STRIDE+WILL_OFFSET
        if output[offset] != value:
            output[offset] = value
            changed.add(offset)
    if not changed:
        raise SaveFormatError('No current Will changes to save.')
    if {i for i, (a,b) in enumerate(zip(original,output)) if a != b} != changed:
        raise SaveFormatError('The prepared save changed unrelated bytes.')
    return original, bytes(output)


@_guarded_writer
def write_will(slot, updates):
    original, output = prepare_will(slot, updates)
    backup = _backup_slot(Path(slot))
    try:
        _atomic_replace(Path(slot)/PARMDAT_NAME, output)
        pilots = load_will(slot)
        actual = {p.pilot.pilot_id: p.will for p in pilots}
        if any(actual[pid] != value for pid, value in updates.items()):
            raise SaveFormatError('Current Will readback failed.')
    except Exception:
        _atomic_replace(Path(slot)/PARMDAT_NAME, original)
        raise
    return WillWriteResult(pilots, backup)


def backup_will_updates(slot, backup):
    """Restore only Will, preserving every other newer save edit."""
    slot, backup = Path(slot).resolve(), Path(backup).resolve()
    if slot == backup or slot.name != backup.name:
        raise SaveFormatError('Choose a backup of this same save slot.')
    current = {p.pilot.pilot_id: p.will for p in load_will(slot)}
    previous = {p.pilot.pilot_id: p.will for p in load_will(backup)}
    if current.keys() != previous.keys():
        raise SaveFormatError('The backup has a different pilot roster.')
    return {pid: value for pid, value in previous.items() if value != current[pid]}
