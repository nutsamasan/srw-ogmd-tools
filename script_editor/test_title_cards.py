"""Title-card pixel integrity, input guards, patch routing and review UI."""
import base64
import copy
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from core import Corpus, EditProject, sha
from title_cards import catalog, CardProject, project_cards, project_fingerprint
from title_card_dialog import TitleCardDialog
from patcher import collect_changes, compile_entry
from edit_bundle import export_bundle, read_bundle, checksum
from app import Editor, STYLE, load_ui_fonts
from dialogs import PatchDialog
from test_backlog_layout import layout_archive
from test_import_iso import mini_iso
from test_patch_features import mini_archive
from iso_patcher import prepare_iso_patch, write_patched_iso
from iso_image import DiscImage
from archive_patch import digest
from vendor import sdat
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parents[1]


def edited_png(key='st_000', language='en'):
    im = catalog().image(key, catalog().source_png(key, language))
    # A tiny QA mark in every layer exercises RGBA including hidden RGB.
    for layer in range(6):
        im.putpixel((12, layer * (im.height // 6) + 12), (30, 200, 80, 190))
    output = io.BytesIO(); im.save(output, format='PNG'); return output.getvalue()


class TitleCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Corpus(ROOT / 'script_export/OGMD_EN_JP_20260908')
        cls.app = QApplication.instance() or QApplication([]); load_ui_fonts(); cls.app.setStyleSheet(STYLE)

    def test_corrected_bundled_card_can_patch_without_custom_pixels(self):
        from title_card_correction import ST084_PNG_SHA256
        lib = catalog(); png = lib.source_png('st_084', 'en')
        self.assertEqual(sha(png), ST084_PNG_SHA256)
        self.assertIn('VAUGHT AND FAIRY', lib.card('st_084')['label'])
        with tempfile.TemporaryDirectory() as tmp:
            editor = Editor(self.corpus, Path(tmp) / 'project.json'); dialog = TitleCardDialog(editor)
            item = next(dialog.list.item(i) for i in range(dialog.list.count()) if dialog.list.item(i).data(Qt.ItemDataRole.UserRole) == 'st_084')
            dialog.list.setCurrentItem(item); dialog.bundled_button.click()
            self.assertEqual(dialog.project.count(), 1)
            entry = lib.card('st_084')['entry']; items = collect_changes(editor.project, 'en')['Common', entry]
            # Compiles against a compatible preexisting image, not just the new default.
            before = bytearray(lib.native('st_084', png)); before[-1] ^= 1
            compiled, review = compile_entry(bytes(before), items, 'en')
            self.assertEqual(compiled, lib.native('st_084', png)); self.assertTrue(review[0]['title_card'])
            dialog.grab().save(str(ROOT / 'script_editor/qa/st084_bundled.png'))
            dialog.reset_button.click(); self.assertEqual(dialog.project.count(), 0)
            dialog.close(); editor.close()

    def test_known_previous_library_preserves_edits_and_rejects_bad_fingerprints(self):
        lib = catalog(); previous, migration = next(iter(lib.previous_libraries.items()))
        with tempfile.TemporaryDirectory() as tmp:
            cards = CardProject(Path(tmp) / 'cards.json')
            png = edited_png('st_084'); cards.stage('st_084', 'en', png)
            data = copy.deepcopy(cards.data); data['catalog_identity'] = previous
            data['images']['en:st_084']['base_sha256'] = migration['en:st_084']
            original = json.dumps(data).encode('utf8'); cards.path.write_bytes(original)
            reopened = CardProject(cards.path)
            self.assertEqual(reopened.png('st_084', 'en'), png)
            self.assertEqual(cards.path.read_bytes(), original)
            reopened.stage('st_001', 'en', edited_png('st_001'))
            self.assertTrue(any(p.read_bytes() == original for p in (cards.path.parent / 'backups').glob('*.json')))
            self.assertEqual(CardProject(cards.path).png('st_084', 'en'), png)
            data['images']['en:st_084']['base_sha256'] = '0' * 64
            cards.path.write_text(json.dumps(data), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'fingerprint'): CardProject(cards.path)
            data['catalog_identity'] = 'f' * 64
            cards.path.write_text(json.dumps(data), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'different library'): CardProject(cards.path)

    def test_all_packaged_sources_roundtrip_to_verified_native_hashes(self):
        lib = catalog()
        self.assertEqual(len(lib.cards), 115)
        for key, card in lib.cards.items():
            for lang in ('en', 'jp'):
                png = lib.source_png(key, lang); native = lib.native(key, png)
                self.assertEqual(sha(native), card['sources'][lang])
                self.assertEqual(lib.native(key, lib.from_native(key, native)), native)

    def test_reject_wrong_dimensions_format_and_opaque_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            cards = CardProject(Path(tmp) / 'cards.json')
            for im, fmt in [(Image.new('RGBA', (100, 100)), 'PNG'), (Image.new('RGB', (1280, 1152)), 'PNG'), (Image.new('RGBA', (1280, 1152), (1, 2, 3, 255)), 'PNG'), (Image.new('RGB', (1280, 1152)), 'JPEG')]:
                output = io.BytesIO(); im.save(output, format=fmt)
                with self.assertRaises(ValueError): cards.stage('st_000', 'en', output.getvalue())
            self.assertFalse(cards.path.exists())

    def test_atomic_save_backups_stale_editor_and_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            cards = CardProject(Path(tmp) / 'cards.json'); stale = CardProject(cards.path)
            png = edited_png(); cards.stage('st_000', 'en', png)
            self.assertEqual(CardProject(cards.path).png('st_000', 'en'), png)
            with self.assertRaisesRegex(ValueError, 'another editor'): stale.stage('st_001', 'en', edited_png('st_001'))
            self.assertEqual(stale.count(), 0)
            cards.reset('st_000', 'en'); self.assertEqual(cards.count(), 0)
            self.assertEqual(len(list((Path(tmp) / 'backups').glob('title_cards_*.json'))), 1)
            self.assertEqual(cards.png('st_000', 'en'), catalog().source_png('st_000', 'en'))

    def test_language_groups_compile_and_native_header_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = EditProject(self.corpus, Path(tmp) / 'project.json'); cards = project_cards(project)
            original_hash = project_fingerprint(project)
            cards.stage('st_000', 'en', edited_png()); cards.stage('sn_001', 'jp', edited_png('sn_001', 'jp'))
            self.assertNotEqual(original_hash, project_fingerprint(project)); self.assertEqual(project.count(), 0)
            for lang, key in [('en', 'st_000'), ('jp', 'sn_001')]:
                groups = collect_changes(project, lang); entry = catalog().card(key)['entry']
                self.assertEqual(list(groups), [('Common', entry)])
                source = catalog().native(key, catalog().source_png(key, lang))
                changed, review = compile_entry(source, groups['Common', entry], lang)
                self.assertEqual(changed[:128], source[:128]); self.assertEqual(len(changed), len(source))
                self.assertEqual(changed, catalog().native(key, cards.png(key, lang)))
                self.assertEqual(catalog().native(key, base64.b64decode(review[0]['before_png'])), source)
                bad = bytearray(source); bad[12] ^= 1
                with self.assertRaises(ValueError): compile_entry(bytes(bad), groups['Common', entry], lang)
                wrong = copy.deepcopy(groups['Common', entry]); wrong[0]['row']['native_entry'] = '/wrong'
                with self.assertRaises(ValueError): compile_entry(source, wrong, lang)

    def test_export_bundle_carries_artwork_and_rejects_wrong_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = EditProject(self.corpus, root / 'project.json')
            project_cards(project).stage('st_000', 'en', edited_png())
            project.export(root / 'export')
            path = root / 'export/patch_edits.json'; release = dict(corpus_identity=self.corpus.identity)
            groups, _ = read_bundle(path, release); self.assertEqual(len(groups), 1)
            self.assertTrue((root / 'export/Title_cards/st_000_en.png').is_file())
            doc = json.loads(path.read_text(encoding='utf8')); self.assertEqual(doc['version'], 2)
            doc['groups'][0]['entry'] = catalog().card('st_001')['entry']; doc.pop('payload_sha256'); doc['payload_sha256'] = checksum(doc)
            path.write_text(json.dumps(doc), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'mapping'): read_bundle(path, release)

    def test_card_only_iso_build_write_and_native_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=EditProject(self.corpus,root/'project.json');cards=project_cards(project)
            cards.stage('st_000','en',edited_png());entry=catalog().card('st_000')['entry']
            native=catalog().native('st_000',catalog().source_png('st_000','en'))
            with patch('test_backlog_layout.ENTRY',entry):layout_archive(root/'original.psarc',native)
            sdat.encrypt(root/'original.psarc',root/'Common.psarc.sdat',ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat',verbose=False)
            mini_archive(root/'logic.psarc')
            sdat.encrypt(root/'logic.psarc',root/'Logic.psarc.sdat',ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat',verbose=False)
            source=root/'source.iso';mini_iso(source,(root/'Logic.psarc.sdat').read_bytes());raw=bytearray(source.read_bytes());payload=(root/'Common.psarc.sdat').read_bytes()
            name=b'COMMON_PSARC.SDAT;1';n=33+len(name)+(len(name)%2==0);rec=bytearray(n);rec[0]=n;sector=len(raw)//2048
            struct.pack_into('<I',rec,2,sector);struct.pack_into('>I',rec,6,sector)
            struct.pack_into('<I',rec,10,len(payload));struct.pack_into('>I',rec,14,len(payload))
            rec[18:25]=bytes([126,9,30,0,0,0,0]);rec[28:32]=b'\1\0\0\1';rec[32]=len(name);rec[33:33+len(name)]=name
            at=27*2048
            while raw[at]:at+=raw[at]
            raw[at:at+n]=rec;raw.extend(payload);raw.extend(bytes((-len(raw))%2048))
            struct.pack_into('<I',raw,16*2048+80,len(raw)//2048);struct.pack_into('>I',raw,16*2048+84,len(raw)//2048);source.write_bytes(raw)
            before=digest(source);manifest=prepare_iso_patch(project,'en',source,root/'build',backlog=False)
            doc=json.loads(manifest.read_text(encoding='utf8'));self.assertEqual([a['name'] for a in doc['archives']],['Common'])
            self.assertTrue(doc['review'][0]['title_card']);self.assertEqual(doc['project_sha256'],project_fingerprint(project))
            output=root/'edited.iso';result=write_patched_iso(manifest,output)
            self.assertTrue(result['outside_archive_bytes_unchanged']);self.assertEqual(digest(source),before)
            with DiscImage(output) as disc:disc.extract(disc.file('/PS3_GAME/USRDIR/PSARC/Common.psarc.sdat'),root/'readback.sdat')
            sdat.decrypt(root/'readback.sdat',root/'readback.psarc',verbose=False);arc=Psarc(root/'readback.psarc')
            self.assertEqual(arc._read_file(next(e for e in arc.entries if e.name==entry)),catalog().native('st_000',cards.png('st_000','en')))
            self.assertEqual(arc._read_file(next(e for e in arc.entries if e.name=='/unrelated')),b'preserved asset')

    def test_preview_import_save_and_patch_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); editor = Editor(self.corpus, root / 'project.json'); dialog = TitleCardDialog(editor)
            dialog.show(); self.app.processEvents(); self.assertEqual(dialog.active, ('st_000', 'en'))
            dialog.search.setText('WHITE LYNX'); self.assertEqual(sum(not dialog.list.item(i).isHidden() for i in range(dialog.list.count())), 1)
            dialog.search.clear(); png = edited_png(); source_file = root / 'edit.png'; source_file.write_bytes(png)
            with patch('title_card_dialog.QFileDialog.getOpenFileName', return_value=(str(source_file), 'PNG')): dialog.import_button.click()
            self.assertEqual(dialog.project.count(), 0); self.assertTrue(dialog.save_button.isEnabled())
            dialog.save_button.click(); self.assertEqual(dialog.project.count(), 1)
            dialog.view.setCurrentIndex(1); self.app.processEvents()
            dialog.grab().save(str(ROOT / 'script_editor/qa/title_cards_full_sheet.png'))
            dialog.view.setCurrentIndex(0); self.app.processEvents()
            dialog.grab().save(str(ROOT / 'script_editor/qa/title_cards.png'))
            native = catalog().native('st_000', catalog().source_png('st_000', 'en'))
            items = list(collect_changes(editor.project, 'en').values())[0]
            _, review = compile_entry(native, items, 'en')
            manifest = root / 'patch.json'; manifest.write_text(json.dumps(dict(archives=[dict(name='Common')], review=review, project_sha256=project_fingerprint(editor.project))), encoding='utf8')
            patch_dialog = PatchDialog(editor, root); patch_dialog.built(manifest); patch_dialog.show(); self.app.processEvents()
            self.assertTrue(patch_dialog.card_review.isVisible()); self.assertFalse(patch_dialog.card_after.image.isNull())
            patch_dialog.grab().save(str(ROOT / 'script_editor/qa/title_cards_patch_review.png'))
            # A later card edit invalidates the prepared review before any install.
            dialog.project.reset('st_000', 'en')
            with patch.object(patch_dialog, 'failed') as failed:
                patch_dialog.install_prepared(); failed.assert_called_once()
            self.assertIsNone(patch_dialog.manifest)
            patch_dialog.close(); dialog.close(); editor.close()


if __name__ == '__main__': unittest.main()
