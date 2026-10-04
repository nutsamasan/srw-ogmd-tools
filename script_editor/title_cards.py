"""Lossless native title sheets, separate guarded edits, and patch compilation."""
from __future__ import annotations
import base64
import copy
import io
import json
import re
import struct
import sys
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from PIL import Image
from core import atomic_json, sha

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'
PREFIX = '/Dat/SceneTitle/Dds/@Ja/'


class CardCatalog:
    def __init__(self, path=None):
        self.path = Path(path or ASSETS / 'title_cards.zip')
        with zipfile.ZipFile(self.path) as archive:
            raw = archive.read('catalog.json')
        doc = json.loads(raw)
        if doc.get('version') != 1:
            raise ValueError('Unsupported title-card library.')
        self.identity = sha(raw)
        self.cards = {c['id']: c for c in doc['cards']}
        self.previous_libraries = doc.get('previous_libraries', {})
        from gilliam_title_correction import correct_title_label
        for card in self.cards.values():
            card['label'] = correct_title_label(card['label'])

    def card(self, key):
        if key not in self.cards:
            raise ValueError('Unknown title-card ID: ' + str(key))
        return self.cards[key]

    def source_png(self, key, language):
        self.card(key)
        if language not in ('en', 'jp'):
            raise ValueError('Select English or Japanese artwork.')
        with zipfile.ZipFile(self.path) as archive:
            raw = archive.read(language + '/' + key + '.png')
        native = self.native(key, raw)
        if sha(native) != self.card(key)['sources'][language]:
            raise ValueError('Title-card source artwork changed: ' + key)
        return raw

    def image(self, key, png):
        card = self.card(key)
        if len(png) > 12 * 1024 * 1024:
            raise ValueError('Title-card PNG exceeds 12 MB.')
        with Image.open(io.BytesIO(png)) as im:
            if im.format != 'PNG' or getattr(im, 'n_frames', 1) != 1:
                raise ValueError('Import a single-frame PNG image.')
            if im.size != (card['width'], card['height']):
                raise ValueError(f"This sheet must be {card['width']} × {card['height']} pixels. Export the full sheet as your template; do not resize it.")
            if 'A' not in im.getbands() and 'transparency' not in im.info:
                raise ValueError('The PNG must include transparency. Export an RGBA PNG.')
            return im.convert('RGBA')

    def native(self, key, png):
        return base64.b64decode(self.card(key)['header']) + self.image(key, png).tobytes('raw', 'BGRA')

    def from_native(self, key, raw):
        card = self.card(key)
        header = base64.b64decode(card['header'])
        if raw[:128] != header or len(raw) != 128 + card['width'] * card['height'] * 4:
            raise ValueError('Title-card format or dimensions differ: ' + key)
        im = Image.frombytes('RGBA', (card['width'], card['height']), raw[128:], 'raw', 'BGRA')
        output = io.BytesIO(); im.save(output, format='PNG')
        return output.getvalue()


@lru_cache(maxsize=1)
def catalog():
    return CardCatalog()


class CardProject:
    """Images are self-contained in the JSON; every change is saved with a backup."""
    def __init__(self, path, library=None):
        self.path = Path(path)
        self.library = library or catalog()
        raw = self.path.read_bytes() if self.path.exists() else None
        self.file_hash = sha(raw) if raw is not None else None
        self.data = json.loads(raw) if raw is not None else dict(version=1, catalog_identity=self.library.identity, images={})
        if self.data.get('version') != 1:
            raise ValueError('Title-card edits belong to a different library.')
        if not isinstance(self.data.get('images'), dict):
            raise ValueError('Invalid title-card edits.')
        previous = self.data.get('catalog_identity')
        if previous != self.library.identity:
            migration = self.library.previous_libraries.get(previous)
            if migration is None:
                raise ValueError('Title-card edits belong to a different library.')
            for identity, image in self.data['images'].items():
                if identity in migration:
                    language, key = identity.split(':', 1)
                    if image.get('base_sha256') != migration[identity]:
                        raise ValueError('Title-card source fingerprint differs: ' + key)
                    image['base_sha256'] = self.library.card(key)['sources'][language]
            self.data['catalog_identity'] = self.library.identity
        for identity, image in self.data['images'].items():
            language, key = identity.split(':', 1)
            self.validate_edit(key, language, image)

    def validate_edit(self, key, language, image):
        if language not in ('en', 'jp'):
            raise ValueError('Invalid artwork language.')
        if image.get('base_sha256') != self.library.card(key)['sources'][language]:
            raise ValueError('Title-card source fingerprint differs: ' + key)
        png = base64.b64decode(image['png'], validate=True)
        if sha(self.library.native(key, png)) != image['native_sha256']:
            raise ValueError('Title-card pixels changed outside the editor: ' + key)
        return png

    def count(self):
        return len(self.data['images'])

    def changed(self, key, language):
        return language + ':' + key in self.data['images']

    def png(self, key, language):
        image = self.data['images'].get(language + ':' + key)
        return self.validate_edit(key, language, image) if image else self.library.source_png(key, language)

    def commit(self, data):
        current = self.path.read_bytes() if self.path.exists() else None
        if (sha(current) if current is not None else None) != self.file_hash:
            raise ValueError('Title-card edits changed in another editor. Reopen before saving.')
        if current is not None:
            backup = self.path.parent / 'backups' / ('title_cards_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(current)
        atomic_json(self.path, data)
        self.file_hash = sha(self.path.read_bytes()); self.data = data

    def stage(self, key, language, png, force=False):
        if language not in ('en', 'jp'):
            raise ValueError('Invalid artwork language.')
        im = self.library.image(key, png)
        if im.getchannel('A').getextrema() == (255, 255):
            raise ValueError('This sheet is completely opaque. Keep its transparent background and animation layers.')
        buffer = io.BytesIO(); im.save(buffer, format='PNG'); png = buffer.getvalue()
        fingerprint = sha(self.library.native(key, png))
        data = copy.deepcopy(self.data); identity = language + ':' + key
        if not force and fingerprint == self.library.card(key)['sources'][language]:
            data['images'].pop(identity, None)
        else:
            data['images'][identity] = dict(png=base64.b64encode(png).decode('ascii'), native_sha256=fingerprint,
                                          base_sha256=self.library.card(key)['sources'][language])
        if data != self.data:
            self.commit(data)

    def reset(self, key, language):
        data = copy.deepcopy(self.data)
        if data['images'].pop(language + ':' + key, None) is not None:
            self.commit(data)

    def groups(self, language):
        groups = {}
        for identity, image in self.data['images'].items():
            lang, key = identity.split(':', 1)
            if lang != language:
                continue
            self.validate_edit(key, lang, image)
            card = self.library.card(key)
            item = dict(key='Title_cards', row=dict(id=key, title_card=True, native_entry=card['entry']), edits={lang: image['png']})
            groups[('Common', card['entry'])] = [item]
        return groups


def project_cards(project):
    if not hasattr(project, '_title_cards'):
        project._title_cards = CardProject(project.path.with_name(project.path.stem + '_title_cards.json'))
    return project._title_cards


def project_fingerprint(project):
    data = project.data
    # Preserve legacy report hashes when no artwork is staged.
    cards = project_cards(project)
    if cards.count():
        data = dict(text=project.data, title_cards=cards.data)
    return sha(json.dumps(data, sort_keys=True, ensure_ascii=False).encode())


def validate_item(entry, items, language):
    if len(items) != 1:
        raise ValueError('One replacement sheet is required per title card.')
    item = items[0]; row = item['row']; key = row['id']
    card = catalog().card(key)
    if row.get('title_card') is not True or row.get('native_entry') != entry or entry != card['entry']:
        raise ValueError('Title-card archive mapping differs.')
    if set(item['edits']) != {language}:
        raise ValueError('Title-card artwork language differs.')
    png = base64.b64decode(item['edits'][language], validate=True)
    catalog().image(key, png)
    return key, png


def compile_card(source, items, language):
    key, png = validate_item(items[0]['row'].get('native_entry'), items, language)
    # Accept existing custom pixels, but require the exact native format/header.
    catalog().from_native(key, source)
    result = catalog().native(key, png)
    card = catalog().card(key)
    before_png = catalog().from_native(key, source)
    review = dict(id=key, field='Title-card image', before=f"{card['width']} × {card['height']} · SHA-256 {sha(source)}",
                  after=f"{card['width']} × {card['height']} · SHA-256 {sha(result)}", normalized=False,
                  title_card=True, before_png=base64.b64encode(before_png).decode('ascii'), after_png=base64.b64encode(png).decode('ascii'))
    return result, [review]
