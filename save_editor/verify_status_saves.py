"""Exercise actual saves on disposable copies and verify original file hashes."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
from discovery import discover_saves
from ogmd_save import snapshot_slot, load_pilots, write_pilot_stats, PILOT_RECORD_BASE, PILOT_RECORD_STRIDE
from pilot_status import load_status, from_totals


def main():
    report = dict(original_saves_unchanged=True, in_game_validation=False, saves=[])
    for info in discover_saves():
        original = snapshot_slot(info.slot_path)
        pilots = load_pilots(info.slot_path)
        statuses = load_status(info.slot_path)
        # Include the first and last roster records with independent EXP, stat and terrain changes.
        targets = {p.pilot_id: p for p in (pilots[0], pilots[-1])}
        updates = {pid: from_totals(pid, replace(statuses[pid], experience=49000), (400,)*6, (5,)*4)
                   for pid in targets}
        allowed = {PILOT_RECORD_BASE + p.slot_index * PILOT_RECORD_STRIDE + off for p in targets.values()
                   for off in [0x14, 0x15, *range(0x18, 0x28)]}
        with tempfile.TemporaryDirectory(prefix='ogmd-status-verify-') as tmp:
            slot = Path(tmp) / info.directory_name
            shutil.copytree(info.slot_path, slot)
            assert snapshot_slot(slot) == original
            raw = (slot/'PARMDAT.SAV').read_bytes()
            result = write_pilot_stats(slot, status_updates=updates, expected_snapshot=original)
            assert snapshot_slot(result.backup_path) == original
            changed = {i for i, (a, b) in enumerate(zip(raw, (slot/'PARMDAT.SAV').read_bytes())) if a != b}
            assert changed and changed <= allowed
            after = snapshot_slot(slot)
            assert all(after[name] == value for name, value in original.items() if name != 'PARMDAT.SAV')
            actual = load_status(slot)
            assert all(actual[pid] == value for pid, value in updates.items())
            assert all(actual[pid] == value for pid, value in statuses.items() if pid not in updates)
            write_pilot_stats(slot, status_updates={pid: statuses[pid] for pid in targets})
            assert snapshot_slot(slot) == original
        assert snapshot_slot(info.slot_path) == original
        report['saves'].append(dict(path=str(info.slot_path), pilots=len(pilots), original_hashes=original,
            changed_bytes=len(changed), backup_identity=True, unrelated_bytes_preserved=True,
            byte_identical_restoration=True))
    assert report['saves']
    (Path(__file__).parent/'qa/status_real_saves.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f"Verified edit/restore on {len(report['saves'])} real-save copies; originals unchanged.")


if __name__ == '__main__':
    main()
