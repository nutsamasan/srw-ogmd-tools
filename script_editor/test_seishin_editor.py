"""Verify paired editing, project persistence and native Seishin patch output."""
import os
import struct
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from core import Corpus, EditProject
from app import Editor, STYLE, load_ui_fonts
from seishin_dialog import SeishinDialog, KEY
from patcher import compile_entry
from fixed_data import parse_fixed, structure_hash
from edit_bundle import export_bundle, read_bundle
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parents[1]


class SeishinEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_ui_fonts(); cls.app.setStyleSheet(STYLE)
        cls.corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        arc = Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
        cls.source = arc._read_file(next(e for e in arc.entries if e.name == '/Dat/FixedData/SpiritData.dat'))

    def test_pair_saved_reopened_exported_and_compiled_without_gameplay_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'project.json'
            window = Editor(self.corpus, path)
            dialog = SeishinDialog(window); dialog.show(); self.app.processEvents()
            self.assertEqual(dialog.current, 2)
            self.assertEqual(dialog.list.count(), 44)
            self.assertTrue(dialog.list.item(0).isHidden())
            dialog.names['en'].setText('Recon')
            dialog.descriptions['en'].setPlainText('Reveal the selected enemy.\nCheck its status information.')
            dialog.list.setCurrentRow(3)  # Navigation saves the paired edit.
            self.assertEqual(dialog.current, 3)
            dialog.close(); window.close()
            project = EditProject(self.corpus, path)
            rows = self.corpus.load(KEY)[0]['rows']
            fields = {r['fixed_field']: r for r in rows if r['fixed_logical'] == 2}
            self.assertEqual(project.values(KEY, fields['name'])['en'], 'Recon')
            self.assertEqual(project.values(KEY, fields['description'])['en'], 'Reveal the selected enemy.\nCheck its status information.')
            self.assertEqual(project.values(KEY, fields['description'])['jp'], fields['description']['jp'])
            bundle = export_bundle(project, Path(temp)/'patch_edits.json')
            groups, _ = read_bundle(bundle, dict(corpus_identity=self.corpus.identity))
            items = groups[('Logic', '/Dat/FixedData/SpiritData.dat')]
            result, review = compile_entry(self.source, items, 'en')
            self.assertEqual(len(review), 2)
            before, after = parse_fixed(self.source), parse_fixed(result)
            self.assertEqual(structure_hash(before, 'SpiritData'), structure_hash(after, 'SpiritData'))
            for old, new in zip(before.records, after.records):
                self.assertEqual(old[:1]+old[2:10]+old[11:], new[:1]+new[2:10]+new[11:])
            row = after.records[after.logical_indices[2]]
            self.assertEqual(after.strings[row[1]], 'Recon')
            self.assertEqual(after.strings[row[10]], 'Reveal the selected enemy.\nCheck its status information.')
            self.assertEqual(struct.unpack_from('>H', after.string_headers[row[10]])[0], 2)
            # Other commands can share text slots; their values must stay intact.
            for logical in range(44):
                if logical == 2: continue
                a, b = before.records[before.logical_indices[logical]], after.records[after.logical_indices[logical]]
                for offset in (1, 10): self.assertEqual(before.strings[a[offset]], after.strings[b[offset]])

    def test_invalid_name_keeps_selection_and_restore_clears_saved_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            window = Editor(self.corpus, Path(temp)/'project.json')
            dialog = SeishinDialog(window)
            dialog.names['en'].setText('Bad@Name')
            self.assertFalse(dialog.save_pending())
            dialog.list.setCurrentRow(3)
            self.assertEqual(dialog.current, 2)
            self.assertEqual(dialog.list.currentRow(), 2)
            self.assertEqual(window.project.count(), 0)
            dialog.names['en'].setText('Recon'); self.assertTrue(dialog.save_pending())
            dialog.restore_source(); self.assertTrue(dialog.save_pending())
            self.assertEqual(window.project.count(), 0)
            dialog.search.setText('Focus'); self.assertFalse(dialog.list.item(3).isHidden())
            dialog.reserved.setChecked(True); dialog.search.clear()
            self.assertFalse(dialog.list.item(0).isHidden())
            dialog.close(); window.close()

    def test_library_omits_duplicate_and_search_opens_dedicated_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            window=Editor(self.corpus,Path(temp)/'project.json')
            for query in ('','spirit','Seishin'):
                window.library_search.setText(query)
                for i in range(window.tree.topLevelItemCount()):
                    group=window.tree.topLevelItem(i)
                    self.assertNotEqual(group.text(0),'Spirit Commands')
                    for j in range(group.childCount()):
                        self.assertNotEqual(group.child(j).data(0,Qt.ItemDataRole.UserRole),KEY)
            window.open_line(KEY,'SpiritData_description:0010');self.app.processEvents()
            dialog=window.seishin_window
            self.assertEqual(dialog.current,10)
            self.assertEqual(dialog.descriptions['en'].toPlainText(),window.project.values(KEY,dialog.commands[10]['description'])['en'])
            dialog.close();self.app.processEvents();window.close()
