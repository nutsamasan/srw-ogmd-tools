"""Install the verified S000 coverage build, or restore the previous archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "work/poc/translation_coverage_20260906/Logic.coverage.psarc.sdat"
BACKUP = ROOT / "work/backups/translation_coverage_20260906/Logic.before_coverage.psarc.sdat"
MANIFEST = ROOT / "reports/stage000_coverage_install_20260906.json"
BEFORE = "3f708d9fd97d1b183176490267a7bfa47f1fba57ca6538007a39171c1d30890d"
AFTER = "66f951322547025c1f46fa4b957c407a5646aacb08b0822072517fc439103bf5"
TARGETS = [ROOT / "work/rpcs3_stage000_english_poc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat",
           ROOT / "work/rpcs3_runtime_stage000_english_test/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, data):
    temporary = path.with_name(path.name + ".coverage.tmp")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    assert path.read_bytes() == data


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    expected = AFTER if args.rollback else BEFORE
    replacement = (BACKUP if args.rollback else BUILD).read_bytes()
    assert digest(replacement) == (BEFORE if args.rollback else AFTER)
    originals = [target.read_bytes() for target in TARGETS]
    assert all(digest(data) == expected for data in originals), "An active archive differs from the expected revision"
    if not args.rollback:
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        if BACKUP.exists():
            assert BACKUP.read_bytes() == originals[0]
        else:
            BACKUP.write_bytes(originals[0])
    # Check again immediately before replacements; never overwrite a newer build.
    assert all(target.read_bytes() == data for target, data in zip(TARGETS, originals))
    completed = []
    try:
        for target, data in zip(TARGETS, originals):
            write_atomic(target, replacement)
            completed.append((target, data))
    except Exception:
        for target, data in reversed(completed):
            write_atomic(target, data)
        raise
    report = dict(updated_utc=datetime.now(timezone.utc).isoformat(), rollback=args.rollback,
                  source=str(BACKUP if args.rollback else BUILD), backup=str(BACKUP),
                  files=[dict(path=str(target), before_sha256=expected,
                              after_sha256=digest(replacement)) for target in TARGETS])
    report_path = MANIFEST.with_name(MANIFEST.stem + "_rollback.json") if args.rollback else MANIFEST
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
