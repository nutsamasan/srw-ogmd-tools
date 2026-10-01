"""Read current Common archive; build/install/restore only a disposable copy."""
import argparse
import json
import shutil
from pathlib import Path
from archive_patch import digest
from core import Corpus, EditProject, atomic_json
from patcher import prepare_patch, install_patch
from title_cards import project_cards, catalog
from test_title_cards import edited_png
from vendor import sdat
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path); args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    source = Path(json.loads((ROOT/'script_editor/patch_settings.json').read_text(encoding='utf8'))['targets'][0])
    corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    protected = [source/'Common.psarc.sdat', ROOT/'script_editor/edits/project.json', ROOT/'script_editor/patch_settings.json']
    before = {str(p): digest(p) for p in protected}
    fixture = out/'fixture/PS3_GAME/USRDIR/PSARC'; fixture.mkdir(parents=True)
    shutil.copy2(source/'Common.psarc.sdat', fixture/'Common.psarc.sdat')
    shutil.copy2(source.parent.parent/'PARAM.SFO', fixture.parent.parent/'PARAM.SFO')
    # Validation requires Logic's presence; this card-only build never reads it.
    (fixture/'Logic.psarc.sdat').write_bytes(b'QA placeholder; card-only build')
    project = EditProject(corpus, out/'project.json'); cards = project_cards(project)
    cards.stage('st_000', 'en', edited_png())
    manifest = prepare_patch(project, 'en', [fixture], out/'patch', backlog=False, keep_plain=True,
                             progress=lambda text: print(text, flush=True))
    report = json.loads(manifest.read_text(encoding='utf8')); assert len(report['archives']) == 1
    assert report['archives'][0]['verification']['all_entries_verified']
    entry = catalog().card('st_000')['entry']; arc = Psarc(manifest.parent/'Common.patched.psarc')
    expected = catalog().native('st_000', cards.png('st_000', 'en'))
    assert arc._read_file(next(e for e in arc.entries if e.name == entry)) == expected
    install_patch(manifest, closed_check=lambda: None)
    sdat.decrypt(fixture/'Common.psarc.sdat', out/'installed.psarc', verbose=False)
    installed = Psarc(out/'installed.psarc')
    assert installed._read_file(next(e for e in installed.entries if e.name == entry)) == expected
    install_patch(manifest, restore=True, closed_check=lambda: None)
    assert digest(fixture/'Common.psarc.sdat') == before[str(source/'Common.psarc.sdat')]
    assert {str(p): digest(p) for p in protected} == before
    result = dict(status='passed', original_game_and_text_edits_unchanged=True, protected_sha256=before,
                  archive=report['archives'][0], disposable_install_readback_restore=True, in_game_test=False)
    atomic_json(out/'verification.json', result); print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__': main()
