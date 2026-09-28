"""Regression checks for editing, navigation, persistence and source safety."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from core import Corpus,EditProject,NativeMetrics
from app import Editor,STYLE,ASSETS,load_ui_fonts

ROOT=Path(__file__).resolve().parents[1]
CORPUS=ROOT/'script_export/OGMD_EN_JP_20260908'


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);load_ui_fonts();cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLE)
        cls.corpus=Corpus(CORPUS);cls.metrics=NativeMetrics(ASSETS/'font.bin')
        cls.key=next(c['key'] for c in cls.corpus.collections if c['meta'].get('script_id')=='S001')

    def test_native_measurement_reference(self):
        reports=json.loads((ROOT/'work/poc/text_layout_20260905/spacing_v2/line_measurement_report.json').read_text(encoding='utf8'))
        for case in reports['comparisons']:
            # The native measurement-routine reference receives literal input;
            # markup parsing is a separate step in the actual text wrapper.
            self.assertEqual(self.metrics.raw_width(case['text']),case['values']['v2_b7f808']-case['text'].count("'")*6.75)
        self.assertEqual(self.metrics.advance("'"),9.75)
        self.assertEqual(self.metrics.advance('’'),24)
        self.assertTrue(self.metrics.assess('W'*100)['overflow'])
        self.assertTrue(self.metrics.assess('A\nB\nC\nD')['too_many_lines'])
        self.assertIn('😀',self.metrics.assess('😀')['missing'])
        self.assertEqual(self.metrics.width('<C=red>A</C><keyword>'),self.metrics.width('Akeyword'))

    def test_wrap_controls_and_width(self):
        text='This is a long sentence about the Granteed and the Steel Dragons. '*5
        wrapped=self.metrics.wrap(text)
        self.assertEqual(' '.join(wrapped.split()),' '.join(text.split()))
        self.assertTrue(all(w<=768 for w in self.metrics.assess(wrapped)['widths']))
        with self.assertRaises(ValueError):self.metrics.wrap('Yes;\nNo')
        with self.assertRaises(ValueError):self.metrics.wrap('<C=red>Hello</C>')

    def test_save_reload_export_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'project.json';p=EditProject(self.corpus,path)
            doc,_=self.corpus.load(self.key);row=doc['rows'][0]
            source=self.corpus.root/self.key/'script.json';before=source.read_bytes()
            p.set(self.key,row,'en','A test line.\nSecond line.');p.save()
            p2=EditProject(self.corpus,path);self.assertEqual(p2.values(self.key,row)['en'],'A test line.\nSecond line.')
            p2.set(self.key,row,'jp','確認用。\n次の行。');p2.save()
            self.assertEqual(len(list((Path(tmp)/'backups').glob('*.json'))),1)
            dest=Path(tmp)/'export';p2.export(dest)
            output=json.loads((dest/self.key/'script.json').read_text(encoding='utf8'))
            self.assertEqual(output['rows'][0]['jp_raw'],'確認用。@次の行。')
            self.assertEqual(output['rows'][0]['jp_original'],row['jp'])
            self.assertEqual(output['rows'][1:],doc['rows'][1:])
            self.assertEqual(source.read_bytes(),before)
            p.set(self.key,row,'en','Conflicting change')
            with self.assertRaises(RuntimeError):p.save()
            with self.assertRaises(ValueError):p2.export(self.corpus.root/'forbidden')
            p3=EditProject(self.corpus,path);p3.set(self.key,row,'en',row['en']);p3.set(self.key,row,'jp',row['jp']);p3.save();self.assertEqual(p3.count(),0)

    def test_gui_navigation_search_undo_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Editor(self.corpus,Path(tmp)/'project.json');w.show();self.app.processEvents()
            target=None
            for i in range(w.tree.topLevelItemCount()):
                parent=w.tree.topLevelItem(i)
                for j in range(parent.childCount()):
                    item=parent.child(j)
                    if item.data(0,Qt.ItemDataRole.UserRole)==self.key:target=item
            w.tree.setCurrentItem(target);self.app.processEvents();self.assertEqual(w.key,self.key);self.assertEqual(w.row_index,0)
            initial=w.editors['en'].toPlainText();row=w.model.rows[0]
            cursor=w.editors['en'].textCursor();cursor.select(QTextCursor.SelectionType.Document);cursor.insertText('Edited in the GUI.');self.app.processEvents()
            self.assertEqual(w.project.values(self.key,row)['en'],'Edited in the GUI.')
            w.editors['en'].undo();self.app.processEvents();self.assertEqual(w.editors['en'].toPlainText(),initial)
            w.editors['en'].setPlainText('Saved through navigation.');w.navigate(1);w.navigate(-1);self.app.processEvents()
            self.assertEqual(w.editors['en'].toPlainText(),'Saved through navigation.')
            w.search.setText('Saved through navigation');self.app.processEvents();self.assertEqual(w.proxy.rowCount(),1)
            w.search.setText('NONEXISTENT-CORPUS-TEXT');self.app.processEvents();self.assertEqual(w.proxy.rowCount(),0);self.assertIsNone(w.row_index)
            w.search.clear();self.app.processEvents();self.assertGreater(w.proxy.rowCount(),0)
            w.only_edited.setChecked(True);self.app.processEvents();self.assertEqual(w.proxy.rowCount(),1)
            w.save();self.assertFalse(w.project.dirty)
            self.assertEqual(EditProject(self.corpus,Path(tmp)/'project.json').values(self.key,row)['en'],'Saved through navigation.')
            w.only_edited.setChecked(False);w.editors['en'].setPlainText(initial);w.save();w.autosave.stop()
            w.preview_language.setCurrentIndex(0);self.app.processEvents()
            (ROOT/'script_editor/qa').mkdir(exist_ok=True);w.grab().save(str(ROOT/'script_editor/qa/editor_smoke.png'))
            w.close();self.app.processEvents()


if __name__=='__main__':unittest.main(verbosity=2)
