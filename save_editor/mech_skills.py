"""Saved mech Ability slots and native built-in ability enable flags."""
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import struct

import ogmd_save as core

UNIT_BASE = 0x2C
UNIT_STRIDE = 0x1BC
UNIT_COUNT = 256
UNIT_MASK = 0x0C
EQUIPPED_OFFSET = 0x23
FLAGS_OFFSET = 0x4F
BUILTIN_MASK = 0xF80
PILOT_EQUIPPED_OFFSET = 0x41
_CATALOG = json.loads((Path(__file__).parent / 'mechs.json').read_text(encoding='utf8'))
UNITS = {int(k): v for k, v in _CATALOG['units'].items()}
BUILTINS = {int(k): v for k, v in _CATALOG['builtins'].items()}
ABILITY_NAMES = ('Empty',) + core.ABILITY_NAMES


@dataclass(frozen=True)
class MechInfo:
    slot_index: int
    unit_id: int
    name: str
    equipped: tuple[int, ...]
    builtins: tuple[int, ...]
    enabled: tuple[bool, ...]
    shared_slots: tuple[int, ...]


@dataclass(frozen=True)
class MechWriteResult:
    mechs: tuple[MechInfo, ...]
    abilities: tuple[core.AbilityInfo, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


def _read_mechs(payload):
    if len(payload) != core.PARMDAT_SIZE or payload[8:12] != bytes.fromhex('40400000'):
        raise core.SaveFormatError('Unsupported mech record version; expected Moon Dwellers unit version 3.0.')
    active = [i for i in range(UNIT_COUNT) if struct.unpack_from('>I', payload, UNIT_MASK+i//32*4)[0] & (1 << (i%32))]
    records = {i: payload[UNIT_BASE+i*UNIT_STRIDE:UNIT_BASE+(i+1)*UNIT_STRIDE] for i in active}
    parents = {i: i for i in active}

    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i

    for i, record in records.items():
        # Native key 0x6A recursively mirrors the three links with flag 0x08.
        for j in range(3):
            flags, other = struct.unpack_from('>Hh', record, 0x12+j*4)
            if flags & 8 and other != -1:
                if other not in records:
                    raise core.SaveFormatError(f'Mech record {i} links to an unavailable form.')
                parents[root(i)] = root(other)
    groups = {}
    for i in active:
        groups.setdefault(root(i), []).append(i)
    result = []
    for group in groups.values():
        equipment = {tuple(records[i][EQUIPPED_OFFSET:EQUIPPED_OFFSET+3]) for i in group}
        if len(equipment) != 1:
            raise core.SaveFormatError('Linked mech forms have different Ability slots; editing is unsupported.')
        equipped = equipment.pop()
        if any(aid > core.ABILITY_COUNT for aid in equipped):
            raise core.SaveFormatError('A mech has an unknown equipped Ability ID.')
        for i in group:
            uid = int.from_bytes(records[i][:2], 'big')
            if uid not in UNITS:
                raise core.SaveFormatError(f'Unknown mech ID 0x{uid:X}; mech editing is unsupported.')
            if uid == 0:
                if len(group) > 1 or any(equipped):
                    raise core.SaveFormatError('Unexpected equipment or links on the dummy mech.')
                continue
            flags = struct.unpack_from('>I', records[i], FLAGS_OFFSET)[0]
            unit = UNITS[uid]
            result.append(MechInfo(i, uid, unit['name'], equipped, tuple(unit['builtins']),
                                  tuple(bool(flags & (1 << (7+j))) for j in range(5)), tuple(group)))
    return tuple(sorted(result, key=lambda m: m.slot_index))


def load_mechs(slot):
    save = core.load_save(slot)
    return _read_mechs(core._read_parmdat(save.slot_path))


def _equipped_counts(slot, payload, mechs):
    counts = Counter()
    seen = set()
    for mech in mechs:
        if mech.shared_slots not in seen:
            counts.update(aid for aid in mech.equipped if aid)
            seen.add(mech.shared_slots)
    for pilot in core.load_pilots(slot):
        offset = core.PILOT_RECORD_BASE + pilot.slot_index*core.PILOT_RECORD_STRIDE + PILOT_EQUIPPED_OFFSET
        slots = payload[offset:offset+3]
        if any(aid > core.ABILITY_COUNT for aid in slots):
            raise core.SaveFormatError('A pilot has an unknown equipped Ability ID.')
        counts.update(aid for aid in slots if aid)
    return counts


def prepare_mech_changes(slot, equipped_updates=None, builtin_updates=None):
    """Validate an entire staged batch before backup or mutation."""
    equipped_updates = equipped_updates or {}
    builtin_updates = builtin_updates or {}
    if not equipped_updates and not builtin_updates:
        raise core.SaveFormatError('No mech changes were supplied.')
    original = core._read_parmdat(Path(slot))
    mechs = _read_mechs(original)
    by_slot = {m.slot_index: m for m in mechs}
    groups = {}
    for index, values in equipped_updates.items():
        if type(index) is not int or index not in by_slot:
            raise core.SaveFormatError('The requested mech is not in this save.')
        values = tuple(values)
        if len(values) != 3 or any(type(v) is not int or not 0 <= v <= core.ABILITY_COUNT for v in values):
            raise core.SaveFormatError('Choose exactly three Ability slots, using Empty or a named Ability.')
        group = by_slot[index].shared_slots
        if group in groups and groups[group] != values:
            raise core.SaveFormatError('Linked forms cannot have conflicting Ability changes.')
        groups[group] = values
    updated = bytearray(original)
    delta = Counter()
    for group, values in groups.items():
        old = by_slot[group[0]].equipped
        delta.update(aid for aid in values if aid)
        delta.subtract(aid for aid in old if aid)
        for index in group:
            offset = UNIT_BASE + index*UNIT_STRIDE + EQUIPPED_OFFSET
            updated[offset:offset+3] = bytes(values)
    for index, values in builtin_updates.items():
        if type(index) is not int or index not in by_slot:
            raise core.SaveFormatError('The requested mech is not in this save.')
        values = tuple(values)
        mech = by_slot[index]
        if len(values) != 5 or any(type(v) is not bool for v in values):
            raise core.SaveFormatError('Built-in ability switches must be five boolean values.')
        if any(not aid and values[j] != mech.enabled[j] for j, aid in enumerate(mech.builtins)):
            raise core.SaveFormatError('An empty built-in slot cannot be enabled or replaced in the save.')
        offset = UNIT_BASE + index*UNIT_STRIDE + FLAGS_OFFSET
        flags = struct.unpack_from('>I', updated, offset)[0]
        mask = sum(1 << (7+j) for j, enabled in enumerate(values) if enabled)
        struct.pack_into('>I', updated, offset, (flags & ~BUILTIN_MASK) | mask)
    abilities = core.load_abilities(slot)
    sysdata, _ = core._load_documents(Path(slot))
    updated_sys = bytearray(sysdata)
    if groups:
        counts = _equipped_counts(slot, original, mechs)
        if any(counts[a.ability_id] != a.equipped for a in abilities):
            raise core.SaveFormatError('Equipped Ability counts do not match the inventory. No changes were written.')
        for ability in abilities:
            used = delta[ability.ability_id]
            available = ability.available - used
            if (ability.locked and used) or not 0 <= available <= ability.total_owned:
                raise core.SaveFormatError(f'Not enough available {ability.name} Abilities. Increase its total in Abilities inventory first.')
            if used:
                struct.pack_into('>H', updated_sys, core.ABILITY_AVAILABLE_OFFSET+(ability.ability_id-1)*2, available)
    prepared_mechs = _read_mechs(updated)
    prepared_abilities = core._read_abilities(updated_sys)
    if groups:
        counts = _equipped_counts(slot, updated, prepared_mechs)
        if any(counts[a.ability_id] != a.equipped for a in prepared_abilities):
            raise core.SaveFormatError('Internal equipped Ability validation failed.')
    return original, bytes(sysdata), bytes(updated), bytes(updated_sys), prepared_mechs, prepared_abilities


@core._guarded_writer
def write_mech_changes(slot, equipped_updates=None, builtin_updates=None):
    core.load_save(slot)
    original, original_sys, updated, updated_sys, prepared_mechs, prepared_abilities = prepare_mech_changes(slot, equipped_updates, builtin_updates)
    if original == updated and original_sys == updated_sys:
        raise core.SaveFormatError('The selected mech values are unchanged.')
    backup = core._backup_slot(Path(slot))
    originals = {core.PARMDAT_NAME: original, core.SYSDATA_NAME: original_sys}
    replacements = {core.PARMDAT_NAME: updated, core.SYSDATA_NAME: updated_sys}
    attempted = []
    try:
        for name, payload in replacements.items():
            if payload != originals[name]:
                attempted.append(name)
                core._atomic_replace(Path(slot)/name, payload)
        after_mechs, after_abilities = load_mechs(slot), core.load_abilities(slot)
        if after_mechs != prepared_mechs or after_abilities != prepared_abilities:
            raise core.SaveFormatError('Post-write mech validation failed.')
    except Exception as exc:
        failures = []
        for name in reversed(attempted):
            try:
                core._atomic_replace(Path(slot)/name, originals[name])
            except Exception as restore_error:
                failures.append(f'{name}: {restore_error}')
        if failures:
            raise core.SaveFormatError(f'Write failed and restoration needs attention. Restore the complete backup at {backup}. '+ '; '.join(failures)) from exc
        raise
    return MechWriteResult(after_mechs, after_abilities, backup)
