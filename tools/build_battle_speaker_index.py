"""Build the editor-only name lookup from verified native logical pilot IDs."""
from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'tools')]
from core import Corpus, atomic_json, sha
from fixed_data import parse_fixed, structure_hash
from vendor.psarc import Psarc
from port_mltd_stage import parse_mltd
from battle_speakers import speaker_id


def main():
    corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    native = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/PilotData.dat').read_bytes()
    archive = Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
    english = archive._read_file(next(e for e in archive.entries if e.name == '/Dat/FixedData/PilotData.dat'))
    fallback = (ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En/FixedData/PilotNickName.mltd').read_bytes()
    jp, en = parse_fixed(native), parse_fixed(english)
    assert structure_hash(jp, 'PilotData') == structure_hash(en, 'PilotData')
    official = parse_mltd(fallback)[0]
    assert len(official) == len(jp.logical_indices) == 263
    key = '06_Game_data/Pilot_names'
    doc, digest = corpus.load(key)
    assert doc['metadata']['source_jp_sha256'] == sha(native)
    pilots = {}
    for logical, physical in enumerate(jp.logical_indices):
        if physical != 0xffffffff:
            def name(table):
                return table.strings[int.from_bytes(table.records[physical][2:4], 'big')]
            pilots[str(logical)] = dict(en=name(en), jp=name(jp), physical_record=physical, source='native_pilot')
        elif logical in (138, 140):
            assert official[logical].text == 'Bioroid Pilot'
            pilots[str(logical)] = dict(en=official[logical].text, jp=None, source='official_english')
    totals = Counter(); mixed = 0; banks = 0
    for c in corpus.collections:
        if c['group'] != 'Battle messages':
            continue
        rows = corpus.load(c['key'])[0]['rows']
        counts = Counter(speaker_id(r) for r in rows)
        assert None not in counts
        banks += 1; mixed += len(counts) > 1
        for sid, count in counts.items():
            totals[pilots.get(str(sid), {}).get('source', 'unresolved')] += count
    assert dict(totals) == dict(native_pilot=65195, unresolved=971, official_english=672)
    result = dict(version=1, corpus_identity=corpus.identity, pilot_collection=key,
                  pilot_collection_sha256=digest, pilots=pilots,
                  sources=dict(native_pilot_sha256=sha(native), english_pilot_sha256=sha(english),
                               official_english_nickname_sha256=sha(fallback)),
                  coverage=dict(banks=banks, mixed_speaker_banks=mixed, records=sum(totals.values()), by_source=dict(totals)))
    atomic_json(ROOT/'script_editor/assets/battle_speakers.json', result)
    print(json.dumps(result['coverage']))


if __name__ == '__main__':
    main()
