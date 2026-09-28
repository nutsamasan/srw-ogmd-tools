"""Read-only real-target preview and disposable install/restore compatibility check."""
import argparse
import json
import shutil
from pathlib import Path

from archive_patch import digest
from core import Corpus, EditProject, NativeMetrics, atomic_json
from fixed_data import parse_fixed
from patcher import collect_changes, prepare_patch, install_patch
from vendor import sdat
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parents[1]
ENTRY = '/Dat/FixedData/UnitData.dat'


def read_unit(path):
    arc = Psarc(path)
    return arc._read_file(next(e for e in arc.entries if e.name == ENTRY))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    project = EditProject(corpus, ROOT/'script_editor/edits/project.json')
    original_project = digest(project.path)
    original_archives = {str(p): digest(p) for p in args.target.glob('*.sdat')}
    groups = collect_changes(project, 'en')
    manifest = prepare_patch(project, 'en', [args.target], out/'preview',
                             NativeMetrics(ROOT/'script_editor/assets/font.bin'),
                             progress=lambda text: print(text, flush=True), keep_plain=True)
    doc = json.loads(manifest.read_text(encoding='utf8'))
    assert doc['status'] == 'ready'
    assert len(doc['review']) == sum(len(item['edits']) for items in groups.values() for item in items)
    source = read_unit(manifest.parent/'Logic.source.psarc')
    patched = read_unit(manifest.parent/'Logic.patched.psarc')
    before, after = parse_fixed(source), parse_fixed(patched)
    items = groups[('Logic', ENTRY)]
    selected = {item['row']['fixed_record'] for item in items}
    assert before.logical_indices == after.logical_indices
    assert len(before.records) == len(after.records)
    for record, (old, new) in enumerate(zip(before.records, after.records)):
        assert old[0x46:0x4B] == new[0x46:0x4B]
        assert (old[:2]+old[4:] == new[:2]+new[4:]) if record in selected else old == new
    for item in items:
        record = after.records[item['row']['fixed_record']]
        assert after.strings[int.from_bytes(record[2:4], 'big')] == item['edits']['en']
    (out/'installed_UnitData.dat').write_bytes(source)
    # Exercise the existing installer/backup path only on a disposable Logic copy.
    fixture = out/'fixture/PS3_GAME/USRDIR/PSARC'
    fixture.mkdir(parents=True)
    shutil.copy2(args.target.parent.parent/'PARAM.SFO', fixture.parent.parent/'PARAM.SFO')
    shutil.copy2(args.target/'Logic.psarc.sdat', fixture/'Logic.psarc.sdat')
    check_dir = out/'install_check'
    check_dir.mkdir()
    subset = dict(doc, targets=[str(fixture)], archives=[a for a in doc['archives'] if a['name']=='Logic'])
    assert len(subset['archives']) == 1
    shutil.copy2(manifest.parent/'Logic.psarc.sdat', check_dir/'Logic.psarc.sdat')
    atomic_json(check_dir/'patch.json', subset)
    install_patch(check_dir/'patch.json', closed_check=lambda: None)
    sdat.decrypt(fixture/'Logic.psarc.sdat', check_dir/'installed.psarc', verbose=False)
    assert read_unit(check_dir/'installed.psarc') == patched
    install_patch(check_dir/'patch.json', restore=True, closed_check=lambda: None)
    assert digest(fixture/'Logic.psarc.sdat') == subset['archives'][0]['before']
    assert digest(project.path) == original_project
    assert {p: digest(p) for p in original_archives} == original_archives
    atomic_json(out/'verification.json', dict(status='passed', manifest=str(manifest),
        saved_edit_rows=project.count(), review_fields=len(doc['review']),
        archives=[dict(name=a['name'], verification=a['verification']) for a in doc['archives']],
        unit_records=len(before.records), mech_names_checked=len(items), custom_skills_preserved=True,
        all_non_name_unit_bytes_preserved=True, disposable_install_restore=True,
        active_game_files_unchanged=True, saved_project_unchanged=True, original_archives=original_archives,
        project_sha256=original_project))
    print('PASSED: full saved-edits preview, skill preservation, disposable install/restore.', flush=True)


if __name__ == '__main__':
    main()
