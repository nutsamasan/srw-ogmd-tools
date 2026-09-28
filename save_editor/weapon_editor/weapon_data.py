"""Proven WeaponData fields, with strict validation of every other record byte."""
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import struct
from .fixed_data import parse_fixed

EDIT_OFFSETS = frozenset((12, 13, 14, 15, 20, 21))
FIELDS = ('power', 'minimum_range', 'maximum_range', 'en_cost', 'ammo')
LABELS = ('Base attack', 'Minimum range', 'Maximum range', 'EN cost', 'Maximum ammo')
LIMITS = ((0, 65535), (1, 255), (1, 255), (0, 255), (0, 255))


class PatchError(ValueError):
    pass


@dataclass(frozen=True)
class WeaponSettings:
    power: int
    minimum_range: int
    maximum_range: int
    en_cost: int
    ammo: int


@dataclass(frozen=True)
class Weapon:
    record: int
    unit: int
    slot: int
    name: str
    owner: str
    installed_name: str
    settings: WeaponSettings
    defaults: WeaponSettings


def profile(row):
    return WeaponSettings(int.from_bytes(row[12:14], 'big'), row[14], row[15], row[21], row[20])


def structure(fixed):
    rows = []
    for original in fixed.records:
        if len(original) != 84:
            raise PatchError('Unexpected WeaponData record size.')
        row = bytearray(original)
        # Only the proven translated name pointer and editable fields are masked.
        for offset in EDIT_OFFSETS | {4, 5}:
            row[offset] = 0
        rows.append(row)
    return hashlib.sha256(struct.pack('>'+str(len(fixed.logical_indices))+'I', *fixed.logical_indices)
                          + b''.join(rows)).hexdigest()


def catalog():
    return json.loads((Path(__file__).parent/'catalog.json').read_text(encoding='utf8'))


def validate_settings(value):
    if not isinstance(value, WeaponSettings):
        raise PatchError('Invalid weapon settings.')
    for field, label, (low, high) in zip(FIELDS, LABELS, LIMITS):
        v = getattr(value, field)
        if type(v) is not int or not low <= v <= high:
            raise PatchError(f'{label} must be a whole number from {low:,} to {high:,}.')
    if value.minimum_range > value.maximum_range:
        raise PatchError('Minimum range cannot exceed maximum range.')


def read_table(raw):
    try:
        fixed = parse_fixed(raw)
        if structure(fixed) != catalog()['structure']:
            raise PatchError('Unsupported WeaponData table. This editor supports PS3 BLJS10335 '
                             'with original weapon properties or these five edited fields.')
        return fixed
    except PatchError:
        raise
    except Exception as exc:
        raise PatchError('The weapon table is damaged or unsupported.') from exc


def read_weapons(raw):
    fixed = read_table(raw)
    result = {}
    for key, item in catalog()['weapons'].items():
        record = int(key)
        row = fixed.records[record]
        index = int.from_bytes(row[4:6], 'big')
        if index >= len(fixed.strings):
            raise PatchError('Invalid weapon name pointer.')
        current = profile(row)
        validate_settings(current)
        result[record] = Weapon(record, int.from_bytes(row[:2], 'big'), row[2], item['name'],
            item['owner'], fixed.strings[index], current, WeaponSettings(**item['defaults']))
    return result


def prepare_weapons(raw, updates):
    fixed = read_table(raw)
    weapons = read_weapons(raw)
    result, changes, allowed = bytearray(raw), [], set()
    for record, value in updates.items():
        if type(record) is not int or record not in weapons:
            raise PatchError('Choose a supported weapon; the dummy record cannot be edited.')
        validate_settings(value)
        weapon = weapons[record]
        if value == weapon.settings:
            continue
        base = fixed.chunks[b'DATA'][0] + 12 + record * 84
        result[base+12:base+14] = value.power.to_bytes(2, 'big')
        result[base+14] = value.minimum_range
        result[base+15] = value.maximum_range
        result[base+20] = value.ammo
        result[base+21] = value.en_cost
        allowed.update(base+offset for offset in EDIT_OFFSETS)
        changes.append(dict(record=record, unit=weapon.unit, slot=weapon.slot, name=weapon.name,
            owner=weapon.owner, before=asdict(weapon.settings), after=asdict(value)))
    if len(result) != len(raw) or any(a != b and i not in allowed for i, (a,b) in enumerate(zip(raw,result))):
        raise PatchError('Prepared edits changed bytes outside the selected weapon fields.')
    actual = read_weapons(result)
    if any(actual[key].settings != value for key, value in updates.items()):
        raise PatchError('Weapon settings failed prepared-output verification.')
    return bytes(result), changes
