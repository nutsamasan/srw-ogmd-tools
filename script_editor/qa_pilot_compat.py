"""Verify saved edits against installed archives without installing the result."""
import argparse
import json
from pathlib import Path

from archive_patch import digest
from core import Corpus, EditProject, NativeMetrics, atomic_json
from fixed_data import parse_fixed, SCHEMAS, structure_hash
from patcher import collect_changes, prepare_patch
from vendor.psarc import Psarc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true', help='Check the already built preview.')
    parser.add_argument('--work', type=Path, help='QA folder containing preserved_inputs.json.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    work = (args.work or root/'work/poc/editor_pilot_compat_20260927').resolve()
    preserved = json.loads((work/'preserved_inputs.json').read_text(encoding='utf8'))
    assert all(digest(path) == expected for path, expected in preserved.items())
    corpus = Corpus(root/'script_export/OGMD_EN_JP_20260908')
    project = EditProject(corpus, root/'script_editor/edits/project.json')
    groups = collect_changes(project, 'en')
    target = Path(json.loads((root/'script_editor/patch_settings.json').read_text(encoding='utf8'))['targets'][0])
    manifest = work/'preview/patch.json'
    if not args.verify_only:
        manifest = prepare_patch(project, 'en', [target], manifest.parent,
                                 NativeMetrics(root/'script_editor/assets/font.bin'),
                                 progress=lambda s: print(s, flush=True), keep_plain=True)
    doc = json.loads(manifest.read_text(encoding='utf8'))
    assert doc['status'] == 'ready'
    assert json.loads((manifest.parent/'edits.json').read_text(encoding='utf8')) == project.data
    for archive in doc['archives']:
        assert digest(manifest.parent/archive['file']) == archive['after']
        assert digest(manifest.parent/(archive['name']+'.patched.psarc')) == archive['verification']['sha256']
    before_arc = Psarc(work/'preview/Logic.source.psarc')
    after_arc = Psarc(work/'preview/Logic.patched.psarc')
    tables = {}
    for table in SCHEMAS:
        entry = '/Dat/FixedData/'+table+'.dat'
        before = parse_fixed(before_arc._read_file(next(e for e in before_arc.entries if e.name == entry)))
        after = parse_fixed(after_arc._read_file(next(e for e in after_arc.entries if e.name == entry)))
        items = groups.get(('Logic', entry), [])
        allowed = {(item['row']['fixed_record'], i) for item in items
                   for o, w in [SCHEMAS[table][1][item['row']['fixed_field']]] for i in range(o, o+w)}
        assert len(before.records) == len(after.records)
        assert before.logical_indices == after.logical_indices
        assert structure_hash(before, table) == structure_hash(after, table)
        assert all(a == b or (record, i) in allowed
                   for record, (old, new) in enumerate(zip(before.records, after.records))
                   for i, (a, b) in enumerate(zip(old, new)))
        reviewed = {r['id']:r['after'] for r in doc['review'] if r['entry'] == entry}
        for item in items:
            row = item['row']; off, width = SCHEMAS[table][1][row['fixed_field']]
            index = int.from_bytes(after.records[row['fixed_record']][off:off+width], 'big')
            assert after.strings[index] == reviewed[row['id']]
        tables[table] = dict(records=len(after.records), text_fields_checked=len(items),
                             all_non_text_record_bytes_preserved=True)
    assert all(digest(path) == expected for path, expected in preserved.items())
    result = dict(status='passed', manifest=str(manifest), saved_edit_rows=project.count(),
                  review_fields=len(doc['review']), tables=tables,
                  archives=[dict(name=a['name'], verification=a['verification']) for a in doc['archives']],
                  active_game_files_unchanged=True, saved_project_unchanged=True,
                  game_boot_performed=False)
    atomic_json(work/'full_check.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
