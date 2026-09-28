"""Install or restore the verified backlog-only test with a checked backup."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor'))
from core import atomic_json
from patcher import atomic_copy, digest, game_closed

FOLDER = ROOT / 'work/poc/backlog_margin_20260913'
TARGET = Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC/General2d.psarc.sdat')
BEFORE = '1256f31739283968f4aab46bb5269bfca180efcd190134b8f7c1c4a71dbca804'
AFTER = 'c9ef5529801614e463a732ef9646a8899fcbbc5b33db08fb8c160c77a6027971'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    report = json.loads((FOLDER / 'verification.json').read_text(encoding='utf8'))
    measurements = json.loads((FOLDER / 'measurement_verification.json').read_text(encoding='utf8'))
    build = FOLDER / 'General2d.psarc.sdat'
    backup = FOLDER / 'backups/General2d.psarc.sdat'
    journal = FOLDER / 'installation.json'
    assert Path(report['target']).resolve() == TARGET.resolve()
    assert Path(report['file']).resolve() == build.resolve()
    assert (report['before'], report['after']) == (BEFORE, AFTER)
    assert report['asset']['changed_bytes'] == 9
    assert report['archive']['all_entries_verified'] and report['sdat_all_blocks_verified']
    assert measurements['status'] == 'passed' and measurements['executions'] == 36
    game_closed()
    expected = AFTER if args.rollback else BEFORE
    desired = BEFORE if args.rollback else AFTER
    size, stamp = report['size'], report['mtime_ns']
    assert digest(build) == AFTER and build.stat().st_size == size
    assert digest(TARGET) == expected, 'Installed archive differs from the expected revision.'
    assert (TARGET.stat().st_size, TARGET.stat().st_mtime_ns) == (size, stamp)
    if args.rollback:
        previous = json.loads(journal.read_text(encoding='utf8'))
        assert previous['status'] == 'installed'
        assert digest(backup) == BEFORE and backup.stat().st_size == size
    else:
        assert not journal.exists(), 'An installation journal already exists.'
        assert not backup.exists(), 'A backup already exists; inspect it before retrying.'
        backup.parent.mkdir(exist_ok=True)
        print('Creating and verifying the original archive backup...', flush=True)
        atomic_copy(TARGET, backup, BEFORE, stamp)
    record = dict(status='restoring' if args.rollback else 'installing',
                  started_utc=datetime.now(timezone.utc).isoformat(),
                  target=str(TARGET), build=str(build), backup=str(backup),
                  before=BEFORE, after=AFTER, size=size, mtime_ns=stamp,
                  visual_check='pending')
    atomic_json(journal, record)
    game_closed()
    assert digest(TARGET) == expected
    try:
        print('Restoring the original archive...' if args.rollback else 'Installing the backlog test...', flush=True)
        atomic_copy(backup if args.rollback else build, TARGET, desired, stamp)
    except Exception as exc:
        try:
            atomic_copy(build if args.rollback else backup, TARGET, expected, stamp)
            record['status'] = 'installed' if args.rollback else 'recovered'
        except Exception as recovery:
            record.update(status='recovery_failed', recovery_error=str(recovery))
        record['error'] = str(exc)
        atomic_json(journal, record)
        raise
    record.update(status='restored' if args.rollback else 'installed',
                  completed_utc=datetime.now(timezone.utc).isoformat(),
                  installed_sha256=digest(TARGET), backup_sha256=digest(backup),
                  verified_size=TARGET.stat().st_size,
                  verified_mtime_ns=TARGET.stat().st_mtime_ns)
    assert record['installed_sha256'] == desired and record['backup_sha256'] == BEFORE
    assert (record['verified_size'], record['verified_mtime_ns']) == (size, stamp)
    atomic_json(journal, record)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
