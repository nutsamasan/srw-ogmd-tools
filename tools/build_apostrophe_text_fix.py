"""Prepare a reversible text-only fix for the five official smart-apostrophe contractions.

Read each line from the selected installed archive, preserving current edits.
Only an English apostrophe between ASCII letters is normalized to the existing
narrow ASCII apostrophe glyph. The original corpus and executable are untouched.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'work/pydeps')]
from archive_patch import digest, repack
from core import Corpus, EditProject, NativeMetrics, atomic_json
from native_formats import parse_ldbi_table, parse_bmd, read_cstring
from patcher import archive_name, compile_entry, validate_target
from vendor.psarc import Psarc
from vendor import sdat

CORPUS = ROOT/'script_export/OGMD_EN_JP_20260908'
PATTERN = re.compile(r"(?<=[A-Za-z])[\u2018\u2019](?=[A-Za-z])")


def normalize(text):
    return PATTERN.sub("'", text)


def current_text(data, row):
    if data[:4] == b'LDBI':
        _, _, offsets = parse_ldbi_table(data)
        count, start = struct.unpack_from('>II', data, 0x20)
        assert 0 <= row['command_index'] < count
        at = start+row['command_index']*196
        assert at == row['command_offset']
        assert struct.unpack_from('>I', data, at)[0] == 0
        assert data[at+20:at+196].hex() == row['command_metadata_hex']
        index = struct.unpack_from('>I', data, at+16)[0]
        return read_cstring(data, offsets[index]).replace('@', '\n')
    if data[:2] == b'\x03\0':
        _, start, _, texts = parse_bmd(data)
        i = row['message_index']
        assert data[start+i*20:start+i*20+16].hex() == row['record_metadata_hex']
        return texts[i].replace('/', '\n')
    raise ValueError('Unexpected text format')


def build(target, output):
    corpus = Corpus(CORPUS)
    target = validate_target(target, corpus)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(CORPUS) or output.is_relative_to(target.parent.parent):
        raise ValueError('Choose a new build directory outside the corpus and installed game.')
    groups = defaultdict(list)
    scanned_rows = 0
    for info in corpus.collections:
        key = info['key']
        doc, _ = corpus.load(key)
        for row in doc['rows']:
            text = row.get('en') or ''
            scanned_rows += 1
            if normalize(text) == text:
                continue
            entry = doc['metadata']['native_entry']
            groups[(archive_name(entry), '/'+entry)].append(dict(key=key, row=row))
    assert sum(map(len, groups.values())) == 5, 'Recheck the full-corpus inventory before expanding the patch.'
    output.mkdir(parents=True)
    project = EditProject(corpus, output/'edits.json')
    report = dict(version=1, status='building', language='en', source_corpus=str(CORPUS),
                  targets=[str(target)], archives=[], review=[], layout_fixes=[],
                  scanned_rows=scanned_rows, source_candidates=5, scope='English contractions only')
    metrics = NativeMetrics(ROOT/'script_editor/assets/font.bin')
    atomic_json(output/'patch.json', report)
    try:
        for name in sorted({name for name, _ in groups}):
            original = target/(name+'.psarc.sdat')
            before = digest(original)
            stat = original.stat()
            base = output/(name+'.source.psarc')
            plain = output/(name+'.patched.psarc')
            encrypted = output/original.name
            print('Decrypting and authenticating '+name+'...', flush=True)
            sdat.decrypt(original, base, verbose=False)
            assert sdat.verify(original, expect_plain=base, verbose=False)
            arc = Psarc(base)
            index = {e.name: e for e in arc.entries}
            overrides = {}
            for (archive, entry), items in groups.items():
                if archive != name:
                    continue
                data = arc._read_file(index[entry])
                changes = []
                for item in items:
                    old = current_text(data, item['row'])
                    new = normalize(old)
                    if new == old:
                        continue
                    changes.append({**item, 'edits': {'en': new}})
                    project.set(item['key'], item['row'], 'en', new)
                if not changes:
                    continue
                result, review = compile_entry(data, changes, 'en', metrics, normalize=False)
                # Re-read the serialized output through the native row mapping.
                for item in changes:
                    assert current_text(result, item['row']) == item['edits']['en']
                overrides[entry] = result
                report['review'].extend(dict(archive=name, entry=entry, **r) for r in review)
            if not overrides:
                continue
            verification = repack(base, plain, overrides,
                                  lambda message: print(name+': '+message, flush=True))
            print('Encrypting and verifying '+name+'...', flush=True)
            sdat.encrypt(plain, encrypted, original, verbose=False)
            assert encrypted.stat().st_size == stat.st_size
            assert sdat.verify(encrypted, expect_plain=plain, verbose=False)
            assert digest(original) == before and original.stat().st_mtime_ns == stat.st_mtime_ns
            report['archives'].append(dict(name=name, file=original.name, before=before,
                after=digest(encrypted), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                verification=verification))
            atomic_json(output/'patch.json', report)
        project.save()
        report.update(status='ready', changed_rows=len(report['review']),
                      project_sha256=digest(output/'edits.json') if (output/'edits.json').exists() else None)
        atomic_json(output/'patch.json', report)
        print(json.dumps(dict(manifest=str(output/'patch.json'), changed_rows=report['changed_rows'],
                              archives=[a['name'] for a in report['archives']])))
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        atomic_json(output/'patch.json', report)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.target, args.output)
