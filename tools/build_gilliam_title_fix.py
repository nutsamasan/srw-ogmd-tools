"""Build/install/restore a guarded correction for the intermission stage title."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'tools')]
from archive_patch import digest, repack
from core import atomic_json
from fixed_data import parse_fixed
from gilliam_title_correction import ENTRY, AFTER, fix_gilliam_title as fix_stage_titles
from vendor.psarc import Psarc
from vendor import sdat
from patcher import install_patch, validate_target

OUTPUT = ROOT/'work/poc/gilliam_title_fix_20261004/native_patch'
MANIFEST = OUTPUT/'patch.json'


def require_closed():
    from install_apostrophe_text_fix import require_archives_idle
    require_archives_idle(json.loads(MANIFEST.read_text(encoding='utf8')))


def build(target):
    target = validate_target(target)
    if OUTPUT.exists():
        raise FileExistsError('Preserve the existing build and backup.')
    original = target/'Logic.psarc.sdat'
    before, stat = digest(original), original.stat()
    OUTPUT.mkdir(parents=True)
    base, plain = OUTPUT/'Logic.source.psarc', OUTPUT/'Logic.patched.psarc'
    encrypted = OUTPUT/original.name
    print('Authenticating the installed Logic archive...', flush=True)
    sdat.decrypt(original, base, verbose=False)
    assert sdat.verify(original, expect_plain=base, verbose=False)
    arc = Psarc(base)
    entry = next(e for e in arc.entries if e.name == ENTRY)
    source = arc._read_file(entry)
    result, review = fix_stage_titles(source)
    if len(review) != 1:
        raise ValueError('Expected one shared uncorrected scenario 21 title string.')
    assert fix_stage_titles(result) == (result, [])
    (OUTPUT/'StageData.before.dat').write_bytes(source)
    (OUTPUT/'StageData.dat').write_bytes(result)
    verification = repack(base, plain, {ENTRY: result}, lambda m: print(m, flush=True))
    actual = Psarc(plain)
    assert [e.name for e in actual.entries] == [e.name for e in arc.entries]
    for old, new in zip(arc.entries, actual.entries):
        assert actual._read_file(new) == (result if old.name == ENTRY else arc._read_file(old))
    print('Encrypting and verifying every SDAT block...', flush=True)
    sdat.encrypt(plain, encrypted, original, verbose=False)
    assert encrypted.stat().st_size == stat.st_size
    assert sdat.verify(encrypted, expect_plain=plain, verbose=False)
    assert digest(original) == before and original.stat().st_mtime_ns == stat.st_mtime_ns
    atomic_json(MANIFEST, dict(version=1, status='ready', language='en',
        source_corpus=str(ROOT/'script_export/OGMD_EN_JP_20260908'),
        targets=[str(target)], changed_rows=1, review=review,
        archives=[dict(name='Logic', file=original.name, before=before,
            after=digest(encrypted), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
            verification=verification)]))
    atomic_json(OUTPUT/'verification.json', dict(status='passed', scenario=21,
        title=AFTER, changed_title_strings=1, native_entries_checked=len(arc.entries),
        unrelated_entries_unchanged=True, all_non_text_bytes_unchanged=True,
        exact_archive_size=True, sdat_all_blocks_verified=True,
        installed=False, in_game_test=False))
    print('Verified patch ready: '+str(MANIFEST), flush=True)


def readback():
    doc = json.loads(MANIFEST.read_text(encoding='utf8'))
    target = Path(doc['targets'][0])/'Logic.psarc.sdat'
    plain = OUTPUT/'Logic.installed_readback.psarc'
    sdat.decrypt(target, plain, verbose=False)
    assert digest(plain) == digest(OUTPUT/'Logic.patched.psarc')
    arc = Psarc(plain)
    fixed = parse_fixed(arc._read_file(next(e for e in arc.entries if e.name == ENTRY)))
    row = fixed.records[fixed.logical_indices[21]]
    assert fixed.strings[row[3]] == fixed.strings[row[5]] == AFTER
    verification = json.loads((OUTPUT/'verification.json').read_text(encoding='utf8'))
    verification.update(installed=True, installed_readback_verified=True,
        backup_sha256=digest(OUTPUT/'backups/Logic.psarc.sdat'))
    assert verification['backup_sha256'] == doc['archives'][0]['before']
    atomic_json(OUTPUT/'verification.json', verification)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', type=Path, metavar='PSARC_DIRECTORY')
    group.add_argument('--install', action='store_true')
    group.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if args.build:
        build(args.build)
    else:
        require_closed()
        record = install_patch(MANIFEST, restore=args.restore,
            progress=lambda m: print(m, flush=True), closed_check=require_closed)
        if not args.restore:
            readback()
        print(json.dumps(dict(status=record['status'], completed=record['completed'])))
