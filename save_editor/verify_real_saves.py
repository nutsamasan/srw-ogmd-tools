"""Read originals and run byte-level edit checks ONLY on temporary copies."""
import json
from pathlib import Path
import shutil
import tempfile
from dataclasses import asdict
from discovery import discover_saves
import ogmd_save as save
import skill_progress as feature


def main():
    report = {"original_saves_unchanged": True, "in_game_validation": False, "saves": []}
    for info in discover_saves():
        original_hashes = save.snapshot_slot(info.slot_path)
        pilots = save.load_pilots(info.slot_path)
        parts = save.load_parts(info.slot_path)
        abilities = save.load_abilities(info.slot_path)
        weapons = save.load_weapons(info.slot_path)
        skill_pilot = feature.load_pilot_skills(info.slot_path)[-1]
        skill_slots = list(skill_pilot.slots)
        skill_index = next((i for i,s in enumerate(skill_slots) if s.skill_id < 2), 5)
        skill_id = next(i for i in (10,5,6,7,22,23,43,16) if i not in {s.skill_id for s in skill_slots})
        skill_slots[skill_index] = feature.SkillSlot(skill_id, min(1,feature.learned_limit(skill_pilot.pilot,skill_index,skill_id)))
        skill_start = save.PILOT_RECORD_BASE + skill_pilot.pilot.slot_index*72 + feature.SKILLS_OFFSET
        record = {"path": str(info.slot_path), "scenario": info.subtitle,
                  "funds": info.funds, "total_earned": info.total_funds,
                  "pilots": len(pilots), "weapon_copies": sum(w.total_owned for w in weapons),
                  "sha256": original_hashes, "checks": []}
        checks = [
            ("skills", lambda p: feature.write_pilot_skills(p, {skill_pilot.pilot.pilot_id: tuple(skill_slots)}), "PARMDAT.SAV", set(range(skill_start, skill_start+12))),
            ("completed_games", lambda p: feature.write_completed_games(p, 3), "SYSDATA.SAV", set(range(0x2AC,0x2B0))),
            ("funds", lambda p: save.write_funds(p, 1000000), "SYSDATA.SAV", set(range(0x280, 0x288))),
            ("pilots", lambda p: save.write_pilot_stats(p, pp_updates={x.pilot_id: 9999 for x in pilots}, kill_updates={x.pilot_id: 999 for x in pilots}), "PARMDAT.SAV",
             {save.PILOT_RECORD_BASE+x.slot_index*72+offset for x in pilots for offset in (0x12,0x13,0x16,0x17)}),
            ("parts", lambda p: save.write_parts(p, {x.part_id: 99 for x in parts}), "SYSDATA.SAV", set(range(0x529,0x554)) | set(range(0x64D,0x678))),
            ("abilities", lambda p: save.write_abilities(p, {x.ability_id: x.equipped+99 for x in abilities}), "SYSDATA.SAV", set(range(0x56A,0x594)) | set(range(0x68E,0x6B8))),
            ("weapons", lambda p: save.write_weapon_totals(p, {x.weapon_id: 4 for x in weapons if x.total_owned < 4}), "PARMDAT.SAV", set(range(0x20454,0x20474)) | set(range(0x20475,0x20772))),
        ]
        for label, write, file, allowed in checks:
            with tempfile.TemporaryDirectory(prefix="ogmd-editor-verify-") as temp:
                slot = Path(temp) / info.directory_name
                shutil.copytree(info.slot_path, slot)
                before = {p.name: p.read_bytes() for p in slot.iterdir() if p.is_file()}
                result = write(slot)
                assert save.snapshot_slot(result.backup_path) == original_hashes
                for name, payload in before.items():
                    current = (slot/name).read_bytes()
                    if name == file:
                        changed = {i for i, (a,b) in enumerate(zip(payload,current)) if a != b}
                        assert len(payload) == len(current) and changed <= allowed and changed
                    else:
                        # English saves in this corpus have no funds text in SFO.
                        assert payload == current, (label,name)
                save.load_save(slot); save.load_pilots(slot); save.load_parts(slot)
                save.load_abilities(slot); save.load_weapons(slot)
                if label == "pilots":
                    after = save.load_pilots(slot)
                    assert [(x.slot_index,x.pilot_id,x.experience) for x in after] == [(x.slot_index,x.pilot_id,x.experience) for x in pilots]
                if label == "weapons":
                    payload = (slot/file).read_bytes()
                    for weapon in weapons:
                        for copy in weapon.copies:
                            offset = save.WEAPON_SLOT_BASE+copy.slot_index*3
                            assert payload[offset:offset+3] == before[file][offset:offset+3]
                record["checks"].append({"feature": label, "changed_bytes": len(changed), "backup_matches_original": True, "unrelated_bytes_preserved": True})
        assert save.snapshot_slot(info.slot_path) == original_hashes
        report["saves"].append(record)
    assert report["saves"], "No real saves found."
    destination = Path(__file__).parent / "qa/real_save_verification.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print(f"Verified {len(report['saves'])} real save folders, seven edit categories each. All originals unchanged.")


if __name__ == "__main__":
    main()
