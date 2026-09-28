"""Build an isolated backlog-margin experiment from the current English archive.

Never installs files or controls RPCS3. Only the nine BackLog text-width caps
change. The stock native reader verifies the resulting properties and objects.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor'))
from archive_patch import digest, repack
from core import sha
from vendor.psarc import Psarc
from vendor import sdat
from decode_wtd_native import Decoder

OUT = ROOT / 'work/poc/backlog_margin_20260913'
SOURCE = ROOT / 'work/poc/full_release_20260910_v12/General2d.psarc'
TEMPLATE = ROOT / 'work/poc/full_release_20260910_v12/General2d.psarc.sdat'
TARGET = Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC/General2d.psarc.sdat')
EXPECTED = '1256f31739283968f4aab46bb5269bfca180efcd190134b8f7c1c4a71dbca804'
ENTRY = '/Dat/Window/WindowToolData/windowdataMain.wtd'


def name_hash(text):
    value = 0
    for char in text.encode('ascii'):
        value = (value * 137 + char) & 0xffffffff
    return (value + value // 0xffffffff) & 0xffffffff


def find_window(data):
    offset = 0x718
    matches = []
    for index in range(403):
        size, identifier = struct.unpack_from('>II', data, offset)
        assert 24 <= size <= len(data) - offset
        if identifier == name_hash('BackLog'):
            matches.append(dict(index=index, offset=offset, size=size))
        offset += size
    assert len(matches) == 1
    return matches[0]


def make_asset(source):
    window = find_window(source)
    before = Decoder(source)
    assert before.window(window['offset']) == window['offset'] + window['size']
    objects = before.objects
    changes = []
    result = bytearray(source)
    for number in range(1, 10):
        label = f'f{number}'
        matches = [o for o in objects if struct.unpack_from('>I', source, o['offset'] + 4)[0] == name_hash(label)]
        assert len(matches) == 1
        obj = matches[0]
        end = min([o['offset'] for o in objects if o['offset'] > obj['offset']] + [window['offset'] + window['size']])
        props = {p['offset']: p for p in before.properties if obj['offset'] < p['offset'] < end}
        prop = props[min(props)]
        value = bytes.fromhex(prop['value'])
        assert struct.unpack_from('>H', value, 0x54)[0] == 740
        assert struct.unpack_from('>ff', value, 0x14) == (28.0, 28.0)
        # The initial state serializes the cap followed by a signed -1 field.
        marker = struct.pack('>HH', 740, 0xffff)
        span = source[prop['offset']:prop['end']]
        assert span.count(marker) == 1
        offset = prop['offset'] + span.index(marker)
        struct.pack_into('>H', result, offset, 720)
        assert bytes(before.vm.mem_read(obj['object'] + 0x12, 2)) == struct.pack('>H', 740)
        changes.append(dict(widget=label, object_offset=obj['offset'], property_offset=prop['offset'], width_offset=offset, before=740, after=720))
    result = bytes(result)
    differences = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    assert differences == [c['width_offset'] + 1 for c in changes]
    assert len(result) == len(source)
    after = Decoder(result)
    assert after.window(window['offset']) == window['offset'] + window['size']
    assert before.objects == after.objects and before.groups == after.groups
    assert len(before.properties) == len(after.properties)
    changed_properties = {c['property_offset'] for c in changes}
    checked = 0
    for a, b in zip(before.properties, after.properties):
        expected = bytearray.fromhex(a['value'])
        if a['offset'] in changed_properties:
            struct.pack_into('>H', expected, 0x54, 720)
        assert {k: v for k, v in a.items() if k != 'value'} == {k: v for k, v in b.items() if k != 'value'}
        assert expected.hex() == b['value']
        checked += 1
    changed_objects = {c['object_offset'] for c in changes}
    for obj in before.objects:
        old = bytearray(before.vm.mem_read(obj['object'], 0x110))
        if obj['offset'] in changed_objects:
            struct.pack_into('>H', old, 0x12, 720)
        assert bytes(old) == bytes(after.vm.mem_read(obj['object'], 0x110))
    return result, dict(window=window, changes=changes, changed_bytes=len(differences),
                        native_property_decodes_checked=checked, native_objects_checked=len(objects),
                        all_other_asset_bytes_identical=True, source_sha256=sha(source), output_sha256=sha(result))


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    print('Checking the current installed archive against the preserved source...', flush=True)
    assert digest(TARGET) == digest(TEMPLATE) == EXPECTED
    original_stat = TARGET.stat()
    assert sdat.verify(TEMPLATE, expect_plain=SOURCE, verbose=False)
    arc = Psarc(SOURCE)
    matches = [e for e in arc.entries if e.name == ENTRY]
    assert len(matches) == 1
    source = arc._read_file(matches[0])
    output, asset_report = make_asset(source)
    (OUT / 'windowdataMain.before.wtd').write_bytes(source)
    (OUT / 'windowdataMain.wtd').write_bytes(output)
    print('Nine backlog caps changed; native reader and object comparisons passed.', flush=True)
    plain = OUT / 'General2d.psarc'
    verification = repack(SOURCE, plain, {ENTRY: output}, progress=lambda message: print(message, flush=True))
    encrypted = OUT / 'General2d.psarc.sdat'
    print('Packaging and checking every SDAT block...', flush=True)
    sdat.encrypt(plain, encrypted, TEMPLATE, verbose=False)
    assert encrypted.stat().st_size == original_stat.st_size
    assert sdat.verify(encrypted, expect_plain=plain, verbose=False)
    assert digest(TARGET) == EXPECTED and TARGET.stat().st_mtime_ns == original_stat.st_mtime_ns
    report = dict(status='offline-verified; not installed; visual check pending',
                  target=str(TARGET), file=str(encrypted), before=EXPECTED, after=digest(encrypted),
                  size=original_stat.st_size, mtime_ns=original_stat.st_mtime_ns,
                  asset=asset_report, archive=verification, sdat_all_blocks_verified=True,
                  runtime_modified=False, source_iso_modified=False,
                  native_evidence=dict(property_loader='0xA70C30: property +0x54',
                      runtime_property='BackLog f1-f9 widget +0x12',
                      renderer='0xA797D8-0xA797EC: widget +0x12 to font +0x50',
                      width_before=740, width_after=720))
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
