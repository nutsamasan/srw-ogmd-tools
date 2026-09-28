"""Verify and materialize all official English battle-message files for PS3."""
from pathlib import Path
import json
import re
import struct
import sys

from port_mltd_stage import read_cstring,sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'script_editor/vendor'))
from psarc import Psarc

OUT = ROOT/'work/poc/full_english_20260906'
JP = re.compile('[ぁ-んァ-ヶ一-鿿]')

def parse_bmd(data):
    assert data[:2] == b'\x03\x00'
    groups,conditions,lines = struct.unpack_from('>3H',data,2)
    start = 8 + groups*12 + conditions*20
    pool = start + lines*20
    assert pool <= len(data)
    texts = []
    for k in range(lines):
        offset = struct.unpack_from('>I',data,start+k*20+16)[0]
        texts.append(None if offset == 0xFFFFFFFF else read_cstring(data,pool+offset))
    return (groups,conditions,lines),start,pool,texts

def build():
    archive = Psarc(ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Battle.psarc')
    entries = {e.name:e for e in archive.entries}
    rows = []
    sources = sorted((ROOT/'work/extracted/ps4_lang/Dat/Battle/Message/@En').glob('*.bmd'))
    native = [n for n in entries if n.startswith('/Dat/Battle/Message/@Ja/') and n.endswith('.bmd')]
    assert len(native) == len(sources) == 263
    for source in sources:
        target = '/Dat/Battle/Message/@Ja/'+source.name.replace('_en','_ja')
        japanese = archive._read_file(entries[target]);english = source.read_bytes()
        jn,js,jp,jt = parse_bmd(japanese);en,es,ep,et = parse_bmd(english)
        assert (jn,js,jp) == (en,es,ep)
        assert japanese[:js] == english[:es]
        assert all(japanese[js+k*20:js+k*20+16] == english[es+k*20:es+k*20+16] for k in range(jn[2]))
        assert [t is None for t in jt] == [t is None for t in et]
        destination = OUT/'battle'/target.lstrip('/')
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(english)
        assert destination.read_bytes() == english
        rows.append(dict(entry=target,source_sha256=sha256(japanese),output_sha256=sha256(english),
                         source_size=len(japanese),output_size=len(english),message_records=len(et),
                         unique_texts=len(set(et)-{None}),
                         remaining_japanese=sorted({t for t in et if t and JP.search(t)}),
                         all_voice_condition_and_event_bytes_preserved=True,all_text_pointers_verified=True))
    (OUT/'battle_inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(rows),records=sum(r['message_records'] for r in rows),
                         unique_texts_per_file=sum(r['unique_texts'] for r in rows),
                         remaining=sum(len(r['remaining_japanese']) for r in rows))))

if __name__ == '__main__':build()
