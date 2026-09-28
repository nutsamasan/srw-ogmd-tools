"""Level, combat training and terrain training in BLJS10335 scenario saves."""
from dataclasses import dataclass
import json
from pathlib import Path
import struct

from ogmd_save import (SaveFormatError, PILOT_RECORD_BASE, PILOT_RECORD_STRIDE,
                       _read_parmdat, load_pilots)

# Native/save order. The GUI presents Defense before Evade.
STAT_NAMES = ('Melee', 'Ranged', 'Skill', 'Evade', 'Defense', 'Hit')
DISPLAY_ORDER = (0, 1, 2, 4, 3, 5)
TERRAIN_NAMES = ('Air', 'Land', 'Water', 'Space')
RATINGS = ('—', 'D', 'C', 'B', 'A', 'S')
MAX_EXPERIENCE = 65535
MAX_STAT = 400
PROFILES = json.loads((Path(__file__).parent / 'pilot_status.json').read_text())['pilots']


@dataclass(frozen=True)
class PilotStatus:
    experience: int
    training: tuple[int, ...]
    terrain_training: tuple[int, ...]

    @property
    def level(self):
        return min(self.experience, 49000) // 500 + 1


def profile(pilot_id):
    try:
        return PROFILES[str(pilot_id)]
    except KeyError as exc:
        raise SaveFormatError('This pilot has no supported base-stat profile.') from exc


def natural_stats(pilot_id, experience):
    level = min(experience, 49000) // 500 + 1
    # Native 0x1DC508: base + trunc(curve[level-1] * (curve[98]+correction) / curve[98]).
    return tuple(s['base'] + int(s['curve'][level - 1] * (s['curve'][98] + s['correction']) / s['curve'][98])
                 for s in profile(pilot_id)['stats'])


def totals(pilot_id, value):
    return tuple(min(MAX_STAT, base + bonus) for base, bonus in
                 zip(natural_stats(pilot_id, value.experience), value.training))


def terrain_ratings(pilot_id, value):
    return tuple(min(5, base + bonus) for base, bonus in
                 zip(profile(pilot_id)['terrain'], value.terrain_training))


def validate_status(pilot_id, value, original=None):
    profile(pilot_id)
    if not isinstance(value, PilotStatus):
        raise SaveFormatError('Invalid pilot status edit.')
    if type(value.experience) is not int or not 0 <= value.experience <= MAX_EXPERIENCE:
        raise SaveFormatError('EXP must be a whole number from 0 through 65,535 (level caps at 99).')
    for label, values, count, maximum, previous in (
        ('Combat training', value.training, 6, MAX_STAT, original.training if original else ()),
        ('Terrain training', value.terrain_training, 4, 5, original.terrain_training if original else ()),
    ):
        if not isinstance(values, tuple) or len(values) != count or any(type(v) is not int for v in values):
            raise SaveFormatError(f'{label} must contain {count} whole numbers.')
        for i, v in enumerate(values):
            # Preserve pre-existing out-of-range training when another field changes.
            if not 0 <= v <= maximum and not (previous and v == previous[i]):
                raise SaveFormatError(f'{label} must be between 0 and {maximum}.')
    return value


def from_totals(pilot_id, original, combat, terrain):
    if len(combat) != 6 or len(terrain) != 4:
        raise SaveFormatError('Enter all six combat stats and four terrain ratings.')
    bonuses = []
    for i, (value, base, old_total) in enumerate(zip(combat, natural_stats(pilot_id, original.experience), totals(pilot_id, original))):
        if type(value) is not int or not min(base, MAX_STAT) <= value <= MAX_STAT:
            raise SaveFormatError(f'{STAT_NAMES[i]} must be {min(base, MAX_STAT)}–{MAX_STAT} at this level.')
        bonuses.append(original.training[i] if value == old_total else value - base)
    terrain_bonuses = []
    for i, (value, base, old_total) in enumerate(zip(terrain, profile(pilot_id)['terrain'], terrain_ratings(pilot_id, original))):
        if type(value) is not int or not base <= value <= 5:
            raise SaveFormatError(f'{TERRAIN_NAMES[i]} must be {RATINGS[base]}–S. The save stores training above the natural rating.')
        terrain_bonuses.append(original.terrain_training[i] if value == old_total else value - base)
    return validate_status(pilot_id, PilotStatus(original.experience, tuple(bonuses), tuple(terrain_bonuses)), original)


def read_status(payload, pilots):
    if struct.unpack_from('>f', payload, 0x1bc2c)[0] != 2.0:
        raise SaveFormatError('Pilot status editing requires the verified 2.0 pilot-save layout.')
    result = {}
    for p in pilots:
        start = PILOT_RECORD_BASE + p.slot_index * PILOT_RECORD_STRIDE
        result[p.pilot_id] = PilotStatus(struct.unpack_from('>H', payload, start + 0x14)[0],
            struct.unpack_from('>6H', payload, start + 0x18), tuple(payload[start + 0x24:start + 0x28]))
    return result


def load_status(slot):
    return read_status(_read_parmdat(slot), load_pilots(slot))


def prepare_status(payload, pilots, updates):
    before = read_status(payload, pilots)
    by_id = {p.pilot_id: p for p in pilots}
    result = bytearray(payload)
    for pid, value in updates.items():
        if type(pid) is not int or pid not in by_id:
            raise SaveFormatError('The requested pilot is not recruited in this save.')
        validate_status(pid, value, before[pid])
        start = PILOT_RECORD_BASE + by_id[pid].slot_index * PILOT_RECORD_STRIDE
        struct.pack_into('>H', result, start + 0x14, value.experience)
        struct.pack_into('>6H', result, start + 0x18, *value.training)
        result[start + 0x24:start + 0x28] = bytes(value.terrain_training)
    return result
