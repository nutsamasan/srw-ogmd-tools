"""Moon Dwellers pilot skills and completed games. See FORMAT_NOTES.md."""
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import struct

from ogmd_save import (
    SaveFormatError, PilotInfo, load_save, load_pilots, _read_parmdat,
    _load_documents, _guarded_writer, _backup_slot, _atomic_replace,
    PILOT_RECORD_BASE, PILOT_RECORD_STRIDE, PARMDAT_NAME, SYSDATA_NAME,
    PARAM_SFO_NAME,
)

SKILLS_OFFSET = 0x35
SKILL_SLOTS = 6
SKILL_FLAGS_OFFSET = 0x50
SKILL_FLAGS_SHIFT = 26
COMPLETED_GAMES_OFFSET = 0x2AC
COUNTER_SELECTOR_OFFSET = 0x258
CLEAR_SAVE_OFFSET = 0x2A8
MAX_COMPLETED_GAMES = 99
_CATALOG = json.loads((Path(__file__).parent / "skills.json").read_text(encoding="utf8"))
SKILLS = {item["id"]: item for item in _CATALOG["skills"]}
_LAPS = re.compile(
    r"(?P<prefix>(?:Game Mode\s*[（(]Laps[）)]|ゲームモード\s*[（(](?:周回数|Ｌａｐｓ|Laps)[）)])"
    r"\s*[:：]\s*[^\r\n（(]*[（(])(?P<count>[0-9]+)(?P<end>[）)])", re.I
)


@dataclass(frozen=True)
class SkillSlot:
    skill_id: int
    learned_levels: int


@dataclass(frozen=True)
class PilotSkills:
    pilot: PilotInfo
    slots: tuple[SkillSlot, ...]
    natural_disabled: int = 0


@dataclass(frozen=True)
class GameProgress:
    completed_games: int
    clear_save: bool


@dataclass(frozen=True)
class SkillsWriteResult:
    pilots: tuple[PilotSkills, ...]
    backup_path: Path
    snapshot: dict[str, str] | None = None


@dataclass(frozen=True)
class ProgressWriteResult:
    progress: GameProgress
    backup_path: Path
    snapshot: dict[str, str] | None = None


def natural_levels(pilot: PilotInfo, position: int, skill_id: int, *, maximum=False,
                   disabled=None) -> int:
    """Read the slot's growth curve, unless its saved replacement flag is set.

    PilotData has six ten-byte entries at 0x96: ID + nine unlock levels.
    Runtime key 0x157 uses the slot, not the current skill ID. With no explicit
    flag, infer replacement status for a newly chosen skill from its native ID.
    """
    profile = _CATALOG["pilots"].get(str(pilot.pilot_id))
    if not profile or skill_id < 2:
        return 0
    if disabled is None:
        disabled = profile[position][0] != skill_id
    if disabled:
        return 0
    level = 99 if maximum else min(pilot.experience, 49000) // 500 + 1
    result = 0
    for threshold in profile[position][1]:
        if not 0 < threshold <= level:
            break
        result += 1
    return result if SKILLS[skill_id]["has_levels"] else min(result, 1)


def learned_limit(pilot: PilotInfo, position: int, skill_id: int, *, disabled=None) -> int:
    if skill_id < 2:
        return 0
    skill = SKILLS[skill_id]
    if not skill["has_levels"]:
        return 1
    # Leave room for future natural growth, so leveling the pilot cannot exceed
    # the verified skill range after an editor write.
    return max(0, skill["max_level"] - natural_levels(pilot, position, skill_id, maximum=True, disabled=disabled))


def load_pilot_skills(slot) -> tuple[PilotSkills, ...]:
    pilots = load_pilots(slot)
    payload = _read_parmdat(Path(slot))
    result = []
    for pilot in pilots:
        start = PILOT_RECORD_BASE + pilot.slot_index * PILOT_RECORD_STRIDE + SKILLS_OFFSET
        slots = tuple(SkillSlot(*payload[start+i*2:start+i*2+2]) for i in range(SKILL_SLOTS))
        if any(item.skill_id not in SKILLS for item in slots):
            raise SaveFormatError(f"Unknown skill ID for {pilot.name}; skill editing is unsupported.")
        flags = struct.unpack_from(">I", payload, start-SKILLS_OFFSET+SKILL_FLAGS_OFFSET)[0]
        result.append(PilotSkills(pilot, slots, flags >> SKILL_FLAGS_SHIFT))
    return tuple(result)


def changed_skill_mask(pilot, original, slots, original_mask):
    """Changing an ID explicitly sets/clears the native replacement flag."""
    profile = _CATALOG["pilots"].get(str(pilot.pilot_id))
    mask = original_mask
    for index, item in enumerate(slots):
        if item.skill_id != original[index].skill_id:
            disabled = not profile or item.skill_id != profile[index][0]
            mask = (mask & ~(1 << index)) | (int(disabled) << index)
    return mask


def move_skill(item: PilotSkills, source: int, target: int) -> PilotSkills:
    """Insert a row at target, retaining effective levels through level 99.

    Natural curves are fixed game data. A completed curve can be converted to
    training; ongoing growth must have an equivalent destination curve.
    """
    if any(type(i) is not int or not 0 <= i < SKILL_SLOTS for i in (source, target)):
        raise SaveFormatError("Choose a skill slot from 1 to 6.")
    if source == target:
        return item
    order = list(range(SKILL_SLOTS))
    order.insert(target, order.pop(source))
    slots, mask = [], 0
    level_now = min(item.pilot.experience, 49000) // 500 + 1
    for dest, origin in enumerate(order):
        skill = item.slots[origin]
        disabled = bool(item.natural_disabled & (1 << origin))
        if origin != dest and skill.skill_id > 1:
            if not SKILLS[skill.skill_id]["has_levels"]:
                # These skills are enabled by ID, independently of training.
                disabled = True
            else:
                pilots = [replace(item.pilot, experience=(level-1)*500)
                          for level in range(level_now, 100)]
                natural = [natural_levels(p, origin, skill.skill_id, disabled=disabled)
                           for p in pilots]
                totals = [skill.learned_levels + base for base in natural]

                # If this skill has finished all of its natural growth (or its
                # saved growth flag already disables the curve), freeze the
                # current effective level into training.  That makes the move
                # independent of whichever natural curve belongs to the
                # destination slot.
                if len(set(natural)) == 1:
                    training = totals[0]
                    if training > SKILLS[skill.skill_id]["max_level"]:
                        raise SaveFormatError(
                            f"{SKILLS[skill.skill_id]['name']} has an unsupported effective level {training}.")
                    skill = SkillSlot(skill.skill_id, training)
                    disabled = True
                else:
                    # Ongoing natural growth may only move to a slot whose
                    # native curve is exactly equivalent (up to a fixed
                    # training offset).  A disabled destination curve is flat,
                    # so it cannot preserve ongoing growth.
                    bases = [natural_levels(p, dest, skill.skill_id, disabled=False)
                             for p in pilots]
                    training = totals[0] - bases[0]
                    if (0 <= training <= SKILLS[skill.skill_id]["max_level"] and
                            all(a == b + training for a, b in zip(totals, bases))):
                        skill = SkillSlot(skill.skill_id, training)
                        disabled = False
                    else:
                        raise SaveFormatError(
                            f"{SKILLS[skill.skill_id]['name']} still gains natural levels in slot {origin+1}. "
                            f"Moving it to slot {dest+1} would change its future growth. "
                            "Keep that skill in its slot and rearrange the other skills, or try again after its natural growth is complete.")
        slots.append(skill)
        mask |= int(disabled) << dest
    return PilotSkills(item.pilot, tuple(slots), mask)


def _progress(payload: bytes) -> GameProgress:
    # The native MD reset routine always selects counter bank zero. Do not
    # interpret alternate bank layouts without target-game evidence.
    if struct.unpack_from(">I", payload, COUNTER_SELECTOR_OFFSET)[0] != 0:
        raise SaveFormatError("Unsupported completed-game counter bank.")
    count = struct.unpack_from(">i", payload, COMPLETED_GAMES_OFFSET)[0]
    clear = struct.unpack_from(">I", payload, CLEAR_SAVE_OFFSET)[0]
    if count < 0 or clear not in (0, 1):
        raise SaveFormatError("Invalid completed-game count or clear-save flag.")
    return GameProgress(count, bool(clear))


def load_progress(slot) -> GameProgress:
    save = load_save(slot)
    return _progress(_load_documents(save.slot_path)[0])


def validate_skill_changes(pilot: PilotInfo, original: tuple[SkillSlot, ...], slots, *,
                           original_mask=0, natural_disabled=None) -> tuple[SkillSlot, ...]:
    slots = tuple(slots)
    if len(slots) != SKILL_SLOTS or any(not isinstance(s, SkillSlot) for s in slots):
        raise SaveFormatError("Each pilot must have exactly six skill slots.")
    if any(type(s.skill_id) is not int or type(s.learned_levels) is not int for s in slots):
        raise SaveFormatError("Skill IDs and learned levels must be whole numbers.")
    ids = [s.skill_id for s in slots if s.skill_id > 1]
    if len(ids) != len(set(ids)):
        raise SaveFormatError("A pilot cannot have the same skill in multiple slots.")
    if natural_disabled is None:
        natural_disabled = changed_skill_mask(pilot, original, slots, original_mask)
    if type(natural_disabled) is not int or not 0 <= natural_disabled < 64:
        raise SaveFormatError("Invalid skill growth flags.")
    for index, item in enumerate(slots):
        if type(item.skill_id) is not int or type(item.learned_levels) is not int:
            raise SaveFormatError("Skill IDs and learned levels must be whole numbers.")
        disabled = bool(natural_disabled & (1 << index))
        if item == original[index] and disabled == bool(original_mask & (1 << index)):
            continue  # Preserve unusual existing values when editing other slots.
        if item.skill_id not in SKILLS or item.skill_id == 1:
            raise SaveFormatError("Choose a named skill or Empty.")
        limit = learned_limit(pilot, index, item.skill_id, disabled=disabled)
        if not 0 <= item.learned_levels <= limit:
            raise SaveFormatError(f"Slot {index+1}: learned levels must be 0–{limit} (allows for natural growth).")
        if item.skill_id >= 2 and SKILLS[item.skill_id]["has_levels"]:
            if not item.learned_levels and not natural_levels(pilot, index, item.skill_id, maximum=True, disabled=disabled):
                raise SaveFormatError(f"Slot {index+1}: a new leveled skill needs at least level 1.")
    return slots


@_guarded_writer
def write_pilot_skills(slot, updates, *, natural_disabled_updates=None) -> SkillsWriteResult:
    if not updates:
        raise SaveFormatError("No skill changes were supplied.")
    save = load_save(slot)
    before = {p.pilot.pilot_id: p for p in load_pilot_skills(save.slot_path)}
    normalized = {}
    masks = {}
    if natural_disabled_updates is not None and set(natural_disabled_updates) - set(updates):
        raise SaveFormatError("Skill growth flags need matching skill changes.")
    for pilot_id, slots in updates.items():
        if type(pilot_id) is not int or pilot_id not in before:
            raise SaveFormatError("The requested pilot is not in this save.")
        item = before[pilot_id]
        slots = tuple(slots)
        # Validate slot shape before deriving flags from IDs.
        if len(slots) != SKILL_SLOTS or any(not isinstance(s, SkillSlot) for s in slots):
            raise SaveFormatError("Each pilot must have exactly six skill slots.")
        mask = (natural_disabled_updates or {}).get(pilot_id)
        if mask is None:
            mask = changed_skill_mask(item.pilot, item.slots, slots, item.natural_disabled)
        normalized[pilot_id] = validate_skill_changes(item.pilot, item.slots, slots,
            original_mask=item.natural_disabled, natural_disabled=mask)
        masks[pilot_id] = mask
    original = _read_parmdat(save.slot_path)
    updated = bytearray(original)
    for pilot_id, slots in normalized.items():
        start = PILOT_RECORD_BASE + before[pilot_id].pilot.slot_index * PILOT_RECORD_STRIDE + SKILLS_OFFSET
        updated[start:start+12] = bytes(v for s in slots for v in (s.skill_id, s.learned_levels))
        flag_offset = start - SKILLS_OFFSET + SKILL_FLAGS_OFFSET
        flags = struct.unpack_from(">I", original, flag_offset)[0]
        flags = (flags & 0x03FFFFFF) | (masks[pilot_id] << SKILL_FLAGS_SHIFT)
        struct.pack_into(">I", updated, flag_offset, flags)
    backup = _backup_slot(save.slot_path)
    path = save.slot_path / PARMDAT_NAME
    try:
        _atomic_replace(path, bytes(updated))
        after = load_pilot_skills(save.slot_path)
        actual = {p.pilot.pilot_id: p for p in after}
        if any(actual[pid].slots != slots or actual[pid].natural_disabled != masks[pid]
               for pid, slots in normalized.items()):
            raise SaveFormatError("Post-write skill validation failed.")
    except Exception:
        _atomic_replace(path, original)
        raise
    return SkillsWriteResult(after, backup)


@_guarded_writer
def write_completed_games(slot, completed_games: int) -> ProgressWriteResult:
    if type(completed_games) is not int or not 0 <= completed_games <= MAX_COMPLETED_GAMES:
        raise SaveFormatError(f"Completed games must be a whole number from 0 to {MAX_COMPLETED_GAMES}.")
    save = load_save(slot)
    original, sfo = _load_documents(save.slot_path)
    before = _progress(original)
    original_sfo = sfo.to_bytes()
    updated = bytearray(original)
    struct.pack_into(">I", updated, COMPLETED_GAMES_OFFSET, completed_games)
    # Match native SFO formatter: min(completed + 1, 99) - clear-save flag.
    display_lap = min(completed_games + 1, 99) - int(before.clear_save)
    detail = _LAPS.sub(lambda m: m["prefix"] + str(display_lap) + m["end"], save.detail)
    if detail != save.detail:
        sfo.set_string("DETAIL", detail)
    updated_sfo = sfo.to_bytes()
    backup = _backup_slot(save.slot_path)
    path = save.slot_path / SYSDATA_NAME
    sfo_path = save.slot_path / PARAM_SFO_NAME
    try:
        _atomic_replace(path, bytes(updated))
        if updated_sfo != original_sfo:
            _atomic_replace(sfo_path, updated_sfo)
        after = load_progress(save.slot_path)
        if after.completed_games != completed_games or after.clear_save != before.clear_save:
            raise SaveFormatError("Post-write completed-game validation failed.")
    except Exception:
        _atomic_replace(path, original)
        if updated_sfo != original_sfo:
            _atomic_replace(sfo_path, original_sfo)
        raise
    return ProgressWriteResult(after, backup)
