"""Native attribution, mixed-bank navigation and display-only export guards."""
import copy
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app import Editor, ASSETS, STYLE, load_ui_fonts
from battle_speakers import BattleSpeakers, speaker_id
from core import Corpus, EditProject, atomic_json, sha
from fixed_data import parse_fixed

ROOT = Path(__file__).resolve().parents[1]
BANK = '04_Shared/Battle_messages/'
PILOTS = '06_Game_data/Pilot_names'


class BattleSpeakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_ui_fonts();cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLE)
        cls.corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')

    def test_record_id_is_big_endian_and_requires_intact_metadata(self):
        row = self.corpus.load(BANK+'0002')[0]['rows'][0]
        self.assertEqual(speaker_id(row), 2)
        for invalid in (None, [], 'bad', row['record_metadata_hex'][:8], row['record_metadata_hex']+'00'):
            self.assertIsNone(speaker_id({'record_metadata_hex': invalid}))
        self.assertEqual(speaker_id({'record_metadata_hex':'00000106000000000000000000000000'}), 262)

    def test_full_corpus_mapping_against_native_logical_table(self):
        native = parse_fixed((ROOT/'work/extracted/ps3_logic/Dat/FixedData/PilotData.dat').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            p = EditProject(self.corpus, Path(tmp)/'project.json');b = BattleSpeakers(p, ASSETS/'battle_speakers.json')
            totals = Counter();banks = mixed = nulls = 0
            for c in self.corpus.collections:
                if not b.is_battle(c['key']):continue
                doc, digest = self.corpus.load(c['key']);banks += 1;mixed += len(b.counts(c['key'])) > 1
                self.assertEqual(sha((self.corpus.root/c['key']/'script.json').read_bytes()), digest)
                for row in doc['rows']:
                    sid = speaker_id(row);self.assertIsNotNone(sid)
                    physical = native.logical_indices[sid]
                    if physical != 0xffffffff:
                        self.assertEqual(b.names[sid]['physical_record'], physical)
                        name = native.strings[int.from_bytes(native.records[physical][2:4], 'big')]
                        self.assertEqual(b.name(sid, 'jp'), name if name.strip() else f'Unknown speaker (ID {sid})')
                        totals['native'] += 1
                    elif sid in (138, 140):
                        self.assertEqual(b.name(sid, 'en'), 'Bioroid Pilot');totals['fallback'] += 1
                    else:
                        self.assertIn(f'Unknown speaker (ID {sid})', b.label(sid));totals['unknown'] += 1
                    nulls += row['null_text']
            self.assertEqual((banks, mixed, nulls), (263, 58, 2))
            self.assertEqual(totals, {'native':65195, 'fallback':672, 'unknown':971})
            self.assertEqual(b.counts(BANK+'0002'), {2:153, 3:78, 5:38, 7:16})
            self.assertEqual(b.counts(BANK+'0113'), {113:1532, 114:160, 115:194, 116:162})
            self.assertEqual(p.count(), 0)

    def test_names_follow_bilingual_pilot_edits_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = EditProject(self.corpus, Path(tmp)/'project.json');b = BattleSpeakers(p, ASSETS/'battle_speakers.json')
            key, row = b.pilot_rows[b.names[7]['physical_record']]
            for lang, text in [('en', 'QA Azuki'), ('jp', '確認アヅキ')]:
                p.set(key, row, lang, text);self.assertEqual(b.name(7, lang), text)
                self.assertIn(text, b.collection_details(BANK+'0002'))
                p.set(key, row, lang, row[lang]);self.assertEqual(b.name(7, lang), row[lang])
            self.assertEqual(p.count(), 0)

    def test_gui_mixed_bank_filters_preview_and_cross_result_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Editor(self.corpus, Path(tmp)/'project.json');w.show();self.app.processEvents()
            try:
                rows = self.corpus.load(BANK+'0002')[0]['rows'];guest = next(r for r in rows if speaker_id(r)==7)
                w.open_line(BANK+'0002', guest['id']);self.app.processEvents()
                self.assertEqual(w.preview.speaker, 'Azuki');self.assertTrue(w.speakers['en'].isReadOnly())
                self.assertIn(w.battle.name(7,'jp'), w.model.data(w.model.index(w.row_index,1)))
                w.preview_language.setCurrentIndex(1);self.assertEqual(w.preview.speaker,w.battle.name(7,'jp'))
                w.battle_filter.setCurrentIndex(w.battle_filter.findData(7));self.assertEqual(w.proxy.rowCount(),16)
                w.search.setText(w.battle.name(7,'jp'));self.assertEqual(w.proxy.rowCount(),16)
                w.only_edited.setChecked(True);self.assertEqual(w.proxy.rowCount(),0);self.assertEqual(w.preview.speaker,'')
                self.assertEqual(w.preview.text,'');self.assertIsNone(w.row_index)
                # Opening a result in the same bank must remove every active filter.
                w.open_line(BANK+'0002', rows[0]['id']);self.assertEqual(w.proxy.rowCount(),285)
                self.assertEqual(w.row_index,0);self.assertEqual(w.preview.speaker,w.battle.name(2,'jp'))
                w.search.setText('Azuki');self.assertEqual(w.proxy.rowCount(),16)
                w.library_search.setText('Azuki');item = w.tree.currentItem()
                self.assertFalse(item.isHidden());self.assertIn('Azuki',item.toolTip(0))
                w.library_search.clear();w.search.clear();w.preview_language.setCurrentIndex(0)
                self.app.processEvents();w.grab().save(str(ROOT/'script_editor/qa/battle_speakers_v36.png'))
                self.assertEqual(w.project.count(),0);self.assertFalse(w.project.path.exists())
            finally:w.close()

    def test_unknown_fallback_and_story_speaker_editing(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Editor(self.corpus, Path(tmp)/'project.json')
            try:
                stage = w.key;story = next(r for r in w.model.rows if 'speaker_en' in r)
                w.open_line(BANK+'0004','0004:0000');self.assertIn('Unknown speaker (ID 4)',w.preview.speaker)
                w.open_line(BANK+'0138','0138:0000');self.assertEqual(w.preview.speaker,'Bioroid Pilot')
                w.preview_language.setCurrentIndex(1);self.assertIn('JP name unavailable',w.preview.speaker)
                self.assertIn('fallback',w.speakers['en'].toolTip())
                w.restore();self.assertIn('JP name unavailable',w.preview.speaker)
                w.open_line(stage,story['id']);self.assertFalse(w.speakers['en'].isReadOnly())
                self.assertTrue(w.battle_filter_bar.isHidden());self.assertEqual(w.proxy.speaker_filter,'all')
                w.speakers['en'].setText('QA story name');self.assertEqual(w.project.values(stage,story)['speaker_en'],'QA story name')
            finally:w.close()

    def test_bulk_rename_refreshes_bank_library_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Editor(self.corpus, Path(tmp)/'project.json')
            try:
                w.open_line(BANK+'0002','0002:0000');key,row=w.battle.pilot_rows[w.battle.names[2]['physical_record']]
                w.project.set(key,row,'en','QA renamed Ginto');w.project.set(key,row,'jp','確認ギント')
                w.refresh_after_bulk();self.assertEqual(w.preview.speaker,'QA renamed Ginto')
                self.assertIn('QA renamed Ginto',w.tree.currentItem().text(0))
                self.assertIn('確認ギント',w.battle_filter.itemText(w.battle_filter.findData(2)))
                w.search.setText('QA renamed Ginto');self.assertEqual(w.proxy.rowCount(),153)
                w.preview_language.setCurrentIndex(1);self.assertEqual(w.preview.speaker,'確認ギント')
                w.open_line(key,row['id']);w.editors['en'].setPlainText('QA typed name')
                w.speaker_refresh.timeout.emit();self.assertIn('QA typed name',w.battle.collection_label(BANK+'0002'))
            finally:w.close()

    def test_display_mapping_does_not_export_or_patch_speaker_fields(self):
        from patcher import collect_changes,compile_entry
        from native_formats import parse_bmd
        from vendor.psarc import Psarc
        from script_import import ScriptImporter
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);w=Editor(self.corpus,tmp/'project.json')
            try:
                key=BANK+'0002';doc=self.corpus.load(key)[0];original=copy.deepcopy(doc)
                w.open_line(key,'0002:0000');w.editors['en'].setPlainText('QA battle line.')
                # Read-only labels cannot enter replacement plans, saved edits or exported rows.
                self.assertEqual(w.project.data['collections'][key]['rows']['0002:0000'], {'en':'QA battle line.'})
                w.project.export(tmp/'export');exported=json.loads((tmp/'export'/key/'script.json').read_text(encoding='utf8'))
                self.assertTrue(all('speaker_en' not in r and 'speaker_jp' not in r for r in exported['rows']))
                self.assertEqual([r['record_metadata_hex'] for r in exported['rows']],[r['record_metadata_hex'] for r in original['rows']])
                self.assertEqual(doc,original)
                arc=Psarc(ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Battle.psarc')
                for (_,entry),items in collect_changes(w.project,'en').items():
                    source=arc._read_file(next(e for e in arc.entries if e.name==entry))
                    patched,review=compile_entry(source,items,'en')
                    self.assertTrue(review);before=parse_bmd(source);after=parse_bmd(patched)
                    # Parser returns message table start/count; compare every 16-byte record prefix.
                    start=before[1];count=before[0][2]
                    self.assertEqual(after[:3],before[:3]);self.assertEqual(after[3][0],'QA battle line.')
                    self.assertEqual(after[3][1:],before[3][1:])
                    for i in range(count):self.assertEqual(source[start+i*20:start+i*20+16],patched[start+i*20:start+i*20+16])
                other=EditProject(self.corpus,tmp/'other.json');plan=ScriptImporter(other).preview(tmp/'export'/key/'script.json')
                self.assertTrue(plan)
                w.restore();self.assertEqual(w.preview.speaker,'Ginto');self.assertEqual(w.project.count(),0)
            finally:w.close()

    def test_wrong_corpus_index_never_guesses_a_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);data=json.loads((ASSETS/'battle_speakers.json').read_text(encoding='utf8'))
            data['corpus_identity']='other corpus';atomic_json(tmp/'index.json',data)
            b=BattleSpeakers(EditProject(self.corpus,tmp/'project.json'),tmp/'index.json')
            self.assertIn('Unknown speaker (ID 2)',b.name(2,'en'));self.assertIn('different corpus',b.details(2))


if __name__ == '__main__':unittest.main(verbosity=2)
