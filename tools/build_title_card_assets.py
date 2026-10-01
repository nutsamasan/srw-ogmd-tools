"""Package verified English/Japanese title sheets for the editor; no game writes."""
import base64
import hashlib
import io
import json
import struct
import zipfile
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'work/poc/full_english_20260906'
sys.path.insert(0, str(ROOT / 'script_editor'))
from title_card_correction import correct_st084


def main():
    stages = {s['scenario_id']: s for s in json.loads((ROOT / 'script_export/OGMD_EN_JP_20260908/data/stage_index.json').read_text(encoding='utf8'))}
    rows = json.loads((BASE / 'localized_texture_report.json').read_text(encoding='utf8'))
    cards = []
    output = ROOT / 'script_editor/assets/title_cards.zip'
    pngs = {}
    with zipfile.ZipFile(output.with_suffix('.tmp'), 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for row in rows:
            entry = row['entry']
            if '/SceneTitle/' not in entry:
                continue
            key = Path(entry).stem
            number = int(key[3:])
            stage = stages.get(number, {}) if key.startswith('st_') else {}
            label = (stage.get('title_en', 'Special title') + ' · ' + stage.get('classification_route', '')).strip(' ·') if key.startswith('st_') else ('Chapter ' + str(number) if number < 99 else 'Special chapter number')
            card = dict(id=key, entry=entry, label=label, kind='title' if key.startswith('st_') else 'number', sources={})
            for lang, folder in [('en', 'ui'), ('jp', 'native_ui')]:
                raw = (BASE / folder / 'Common' / entry.lstrip('/')).read_bytes()
                im = Image.open(io.BytesIO(raw)).convert('RGBA')
                assert raw[:4] == b'DDS ' and raw[128:] == im.tobytes('raw', 'BGRA')
                assert len(raw) == 128 + im.width * im.height * 4
                assert struct.unpack_from('<7I', raw, 76) == (32, 65, 0, 32, 0xff0000, 0xff00, 0xff)
                if lang == 'en':
                    assert hashlib.sha256(raw).hexdigest().upper() == row['output_sha256']
                    card.update(width=im.width, height=im.height, header=base64.b64encode(raw[:128]).decode('ascii'))
                else:
                    assert raw[:128] == base64.b64decode(card['header'])
                buffer = io.BytesIO(); im.save(buffer, format='PNG')
                pngs[lang + '/' + key + '.png'] = buffer.getvalue()
                card['sources'][lang] = hashlib.sha256(raw).hexdigest()
            cards.append(card)
        original = json.dumps(dict(version=1, cards=cards), ensure_ascii=False, indent=2).encode('utf8')
        card = next(c for c in cards if c['id'] == 'st_084')
        previous = {hashlib.sha256(original).hexdigest(): {'en:st_084': card['sources']['en']}}
        png = correct_st084({k: pngs['en/' + k + '.png'] for k in ('st_000', 'st_034', 'st_084')})
        pngs['en/st_084.png'] = png
        raw = base64.b64decode(card['header']) + Image.open(io.BytesIO(png)).tobytes('raw', 'BGRA')
        card['sources']['en'] = hashlib.sha256(raw).hexdigest()
        card['label'] = 'VAUGHT AND FAIRY' + (' · ' + card['label'].split(' · ', 1)[1] if ' · ' in card['label'] else '')
        for name, png in pngs.items():
            archive.writestr(name, png)
        archive.writestr('catalog.json', json.dumps(dict(version=1, cards=cards, previous_libraries=previous), ensure_ascii=False, indent=2).encode('utf8'))
    output.with_suffix('.tmp').replace(output)
    print(json.dumps(dict(cards=len(cards), output=str(output), size=output.stat().st_size)))


if __name__ == '__main__':
    main()
