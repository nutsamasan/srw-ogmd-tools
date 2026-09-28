"""Patch disposable copies only, then verify defaults and exact backup recovery."""
import json
from pathlib import Path
import shutil
import tempfile

from mech_patch import Session, snapshot
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat',
           Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat'),
           ROOT/'native_eboot_test/runtime/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat']


def main():
    report = dict(original_archives_unchanged=False, in_game_test=False, sources=[])
    originals = {path: snapshot(path) for path in TARGETS}
    for path in TARGETS:
        print('Verifying disposable copy of '+str(path), flush=True)
        with tempfile.TemporaryDirectory(prefix='ogmd-mech-real-check-') as folder:
            target = Path(folder)/path.name
            shutil.copy2(path, target)
            sessions = []
            def read():
                session = Session(target)
                sessions.append(session)
                return session
            try:
                initial = read()
                receipt = initial.install({1: (9, 12, 17, 20, 24), max(initial.mechs): (14, 17, 20, 21, 24)})
                changed = read()
                assert changed.mechs[1].skills == (9, 12, 17, 20, 24)
                assert snapshot(Path(receipt['backup'])) == originals[path]
                old, new = Psarc(initial.plain), Psarc(changed.plain)
                changed_entries = []
                for a, b in zip(old.entries, new.entries):
                    assert a.name == b.name
                    if old._read_file(a) != new._read_file(b):
                        changed_entries.append(a.name)
                assert changed_entries == ['/Dat/FixedData/UnitData.dat']
                assert initial.original['size'] == changed.original['size']
                assert initial.original['mtime_ns'] == changed.original['mtime_ns']
                changed.restore_backup(receipt['manifest'])
                assert snapshot(target) == originals[path]
                original_again = read()
                original_again.install({1: (9, 12, 17, 20, 24)})
                patched_again = read()
                patched_again.install(patched_again.defaults())
                restored = read()
                assert restored.unit == initial.unit
                report['sources'].append(dict(path=str(path), original=originals[path],
                    mech_count=len(initial.mechs), entry_count=len(old.entries), changed_entries=changed_entries,
                    unchanged_entries_verified=len(old.entries)-1, all_sdat_blocks_verified=True,
                    size_and_timestamp_preserved=True, backup_identical=True,
                    exact_backup_restore_identical=True, default_unit_table_restore_identical=True))
            finally:
                for session in sessions:
                    session.close()
    assert {path: snapshot(path) for path in TARGETS} == originals
    report['original_archives_unchanged'] = True
    (Path(__file__).parent/'qa/archive_verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print('Three archive copy roundtrips passed; original hashes and timestamps unchanged.', flush=True)


if __name__ == '__main__':
    main()
