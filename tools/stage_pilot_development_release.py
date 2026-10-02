"""Stage Full English 1.6.4 from 1.6.3, changing ten menu descriptions."""
import copy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'script_editor'))
from core import NativeMetrics, atomic_json, sha
from full_patch import package_info
from archive_patch import digest, repack
from pilot_development import fix_descriptions
from release_delta import apply_recipe, build_recipe, sdat_metadata
from vendor.psarc import Psarc
from vendor import sdat


def main():
    source = ROOT/'full_patcher/data'
    out = ROOT/'full_patcher/data_v164'
    work = ROOT/'work/poc/pilot_development_release_20261002'
    old = package_info(source)
    assert old['release'] == 'OGMD Full English 1.6.3'
    if out.exists() or work.exists():
        raise FileExistsError('Preserve the existing staged release.')
    work.mkdir(parents=True)
    shutil.copytree(source, out)
    release = copy.deepcopy(old)
    logic = next(a for a in release['archives'] if a['name'] == 'Logic')
    vanilla = ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc'
    base = work/'Logic.before.psarc'
    print('Reconstructing the verified 1.6.3 Logic payload...', flush=True)
    apply_recipe(vanilla, source/logic['blob'],
                 json.loads((source/logic['recipe']).read_text(encoding='utf8')), base)
    entry = '/Dat/FixedData/ProgStrData.dat'
    before = Psarc(base)
    native = before._read_file(next(e for e in before.entries if e.name == entry))
    replacement, review = fix_descriptions(native)
    metrics = NativeMetrics(source/'font.bin')
    for row in review:
        row['layout'] = metrics.assess(row['after'], cell=24, limit=768, max_lines=2)
        assert row['layout']['fits']
    plain, encrypted = work/'Logic.psarc', work/'Logic.psarc.sdat'
    checked = repack(base, plain, {entry: replacement}, lambda m: print(m, flush=True))
    after = Psarc(plain)
    assert [e.name for e in before.entries] == [e.name for e in after.entries]
    for a, b in zip(before.entries, after.entries):
        assert after._read_file(b) == (replacement if a.name == entry else before._read_file(a))
    sdat.encrypt(plain, encrypted, vanilla.with_suffix('.psarc.sdat'), verbose=False)
    assert sdat.verify(encrypted, expect_plain=plain, verbose=False)
    (out/logic['blob']).unlink()
    recipe = build_recipe(vanilla, plain, out/logic['blob'])
    atomic_json(out/logic['recipe'], recipe)
    replay = work/'Logic.replayed.psarc'
    apply_recipe(vanilla, out/logic['blob'], recipe, replay)
    assert digest(replay) == digest(plain)
    (out/logic['metadata']).write_bytes(sdat_metadata(encrypted))
    replay_sdat = work/'Logic.replayed.psarc.sdat'
    sdat.encrypt(replay, replay_sdat, vanilla.with_suffix('.psarc.sdat'), verbose=False)
    sdat_metadata(replay_sdat, (out/logic['metadata']).read_bytes())
    assert digest(replay_sdat) == digest(encrypted)
    assert sdat.verify(replay_sdat, expect_plain=replay, verbose=False)
    logic['target_sdat_sha256'] = digest(encrypted)
    for key in ('recipe', 'blob', 'metadata'):
        logic[key+'_sha256'] = digest(out/logic[key])
    release.update(release='OGMD Full English 1.6.4',
        pilot_development_descriptions=dict(entry=entry, logical_records=list(range(212,222)),
            count=10, native_substrings=1, display_lines=2,
            table_sha256=sha(replacement), maximum_line_width=690,
            width_limit=768, font_cell_size=24, user_confirmed_in_game=True))
    release['features'].append('Pilot Development: all ten stat/terrain descriptions display both lines correctly; confirmed in RPCS3.')
    release['package_bytes'] = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    atomic_json(out/'release.json', release)
    assert package_info(out)['release'] == 'OGMD Full English 1.6.4'
    assert release['review'] == old['review'] and release['edited_rows'] == old['edited_rows'] == 918
    for a,b in zip(old['archives'],release['archives']):
        if a['name'] != 'Logic': assert a == b
    changed = {'release.json',logic['recipe'],logic['blob'],logic['metadata']}
    for p in source.rglob('*'):
        if p.is_file() and p.name not in changed:
            assert digest(p) == digest(out/p.relative_to(source))
    atomic_json(work/'verification.json',dict(status='passed',review=review,
        native_entries_checked=len(before.entries), unrelated_native_entries_unchanged=True,
        all_other_payloads_unchanged=True, original_918_text_edits_preserved=True,
        recipe_replay_verified=True, sdat_metadata_replay_verified=True,
        user_confirmed_pilot_development=True, installed_game_modified=False,
        archive_verification=checked))
    print('Full English 1.6.4 payload verified.', flush=True)


if __name__ == '__main__': main()
