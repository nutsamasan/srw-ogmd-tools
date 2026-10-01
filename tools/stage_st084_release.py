"""Build Full English 1.6.3 from the verified 1.6.2 payload, in isolated copies."""
import copy
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor'))
from core import atomic_json
from full_patch import package_info
from archive_patch import digest, repack
from release_delta import apply_recipe, build_recipe, sdat_metadata
from title_cards import catalog
from title_card_correction import ST084_PNG_SHA256
from vendor.psarc import Psarc
from vendor import sdat


def main():
    source = ROOT / 'full_patcher/data'
    out = ROOT / 'full_patcher/data_v163'
    work = ROOT / 'work/poc/st084_release_20261001'
    old = package_info(source)
    assert old['release'] == 'OGMD Full English 1.6.2'
    if out.exists():
        raise FileExistsError('Preserve the existing staged release; choose a fresh directory.')
    work.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, out)
    release = copy.deepcopy(old)
    common = next(a for a in release['archives'] if a['name'] == 'Common')
    vanilla = ROOT / 'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Common.psarc'
    base = work / 'Common.before.psarc'
    print('Reconstructing the verified 1.6.2 Common archive...', flush=True)
    apply_recipe(vanilla, source / common['blob'], json.loads((source / common['recipe']).read_text(encoding='utf8')), base)
    lib = catalog(); png = lib.source_png('st_084', 'en')
    assert digest_bytes(png) == ST084_PNG_SHA256
    entry = lib.card('st_084')['entry']; replacement = lib.native('st_084', png)
    plain = work / 'Common.psarc'; encrypted = work / 'Common.psarc.sdat'
    checked = repack(base, plain, {entry: replacement}, lambda s: print(s, flush=True), optimize_images=True)
    before, after = Psarc(base), Psarc(plain)
    assert [e.name for e in before.entries] == [e.name for e in after.entries]
    for a, b in zip(before.entries, after.entries):
        assert after._read_file(b) == (replacement if a.name == entry else before._read_file(a)), a.name
    assert base.stat().st_size == plain.stat().st_size
    print('Encrypting and verifying every SDAT block...', flush=True)
    sdat.encrypt(plain, encrypted, vanilla.with_suffix('.psarc.sdat'), verbose=False)
    assert sdat.verify(encrypted, expect_plain=plain, verbose=False)
    (out / common['blob']).unlink()
    recipe = build_recipe(vanilla, plain, out / common['blob'])
    atomic_json(out / common['recipe'], recipe)
    replay = work / 'Common.replayed.psarc'
    apply_recipe(vanilla, out / common['blob'], recipe, replay)
    assert digest(replay) == digest(plain)
    (out / common['metadata']).write_bytes(sdat_metadata(encrypted))
    common['target_sdat_sha256'] = digest(encrypted)
    common['changed_native_entries'] += 1
    for key in ('recipe', 'blob', 'metadata'):
        common[key + '_sha256'] = digest(out / common[key])
    release.update(release='OGMD Full English 1.6.3', baseline_overrides=old['baseline_overrides'] + 1,
                   title_card_corrections=[dict(id='st_084', title='VAUGHT AND FAIRY', entry=entry,
                       png_sha256=ST084_PNG_SHA256, native_sha256=digest_bytes(replacement),
                       animation_layers=6, in_game_test=False)])
    release['features'].append('S084 stage title corrected to VAUGHT AND FAIRY using original glyph pixels in all six animation layers.')
    release['package_bytes'] = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    atomic_json(out / 'release.json', release)
    assert package_info(out)['release'] == 'OGMD Full English 1.6.3'
    assert release['review'] == old['review'] and release['edited_rows'] == old['edited_rows'] == 918
    for a, b in zip(old['archives'], release['archives']):
        if a['name'] != 'Common':
            assert a == b
    changed = {'release.json', common['recipe'], common['blob'], common['metadata']}
    for p in source.rglob('*'):
        if p.is_file() and p.name not in changed:
            assert digest(p) == digest(out / p.relative_to(source))
    atomic_json(work / 'verification.json', dict(status='passed', release=release['release'], common=checked,
        native_entries_checked=len(before.entries), unrelated_native_entries_unchanged=True,
        all_other_payloads_unchanged=True, original_918_text_edits_preserved=True, recipe_replay_verified=True,
        sdat_all_blocks_verified=True, installed=False, in_game_test=False))
    print('Full English 1.6.3 payload verified.', flush=True)


def digest_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


if __name__ == '__main__':
    main()
