"""Read-only battle speaker attribution, independent of editable BMD text."""
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=8192)
def _record_id(metadata):
    try:
        raw = bytes.fromhex(metadata)
    except (ValueError, TypeError):
        return None
    return int.from_bytes(raw[:4], 'big') if len(raw) == 16 else None


def speaker_id(row):
    metadata = row.get('record_metadata_hex')
    return _record_id(metadata) if isinstance(metadata, str) else None


class BattleSpeakers:
    def __init__(self, project, asset):
        self.project = project
        self.corpus = project.corpus
        data = json.loads(Path(asset).read_text(encoding='utf8'))
        if data.get('version') != 1:
            raise ValueError('Unsupported battle speaker index version.')
        self.problem = '' if data['corpus_identity'] == self.corpus.identity else 'Speaker index belongs to a different corpus.'
        self.names = {int(k): v for k, v in data['pilots'].items()} if not self.problem else {}
        self.pilot_rows = {}
        self.count_cache = {}
        key = data['pilot_collection']
        if not self.problem and key in self.corpus.by_key:
            doc, digest = self.corpus.load(key)
            if digest == data['pilot_collection_sha256']:
                self.pilot_rows = {r['fixed_record']: (key, r) for r in doc['rows']
                                   if r.get('fixed_table') == 'PilotData' and r.get('fixed_field') == 'short_name'}

    def is_battle(self, key):
        return key in self.corpus.by_key and self.corpus.by_key[key]['group'] == 'Battle messages'

    def counts(self, key):
        if key not in self.count_cache:
            self.count_cache[key] = Counter(speaker_id(r) for r in self.corpus.load(key)[0]['rows'])
        return self.count_cache[key]

    def name(self, sid, lang):
        info = self.names.get(sid, {})
        source = self.pilot_rows.get(info.get('physical_record'))
        value = self.project.values(*source).get(lang) if source else info.get(lang)
        if value and value.strip():
            return value
        if info.get('source') == 'official_english' and lang == 'jp':
            return f'JP name unavailable (ID {sid})'
        return f'Unknown speaker (ID {sid})' if sid is not None else 'Unknown speaker (invalid metadata)'

    def label(self, sid):
        en, jp = self.name(sid, 'en'), self.name(sid, 'jp')
        return en if en == jp else f'{en} / {jp}'

    def details(self, sid):
        info = self.names.get(sid, {})
        source = info.get('source')
        if self.problem:
            evidence = self.problem
        elif source == 'native_pilot':
            evidence = 'Matched by the battle record character ID to PilotData. Names follow Pilot names edits.'
        elif source == 'official_english':
            evidence = 'Official English PilotNickName fallback. No Japanese pilot name is available in the native table.'
        else:
            evidence = 'No verified pilot name is available for this character ID.'
        identity = f'Character ID {sid} (0x{sid:08X})' if sid is not None else 'Invalid or missing 16-byte battle metadata'
        return f'{self.label(sid)}\n{identity}\n{evidence}\nSpeaker attribution is read-only; it does not change the battle record.'

    def search_text(self, sid):
        return f'{self.label(sid)} ID {sid} {sid:04d}' if sid is not None else self.label(sid)

    def collection_label(self, key):
        counts = self.counts(key)
        if not counts:
            return self.corpus.by_key[key]['title']
        primary = counts.most_common(1)[0][0]
        extra = f' +{len(counts)-1}' if len(counts) > 1 else ''
        return f'Bank {Path(key).name} · {self.name(primary, "en")}{extra} · {sum(counts.values())} rows'

    def collection_details(self, key):
        return '\n'.join(f'{self.search_text(sid)} · {count} rows' for sid, count in self.counts(key).most_common())
