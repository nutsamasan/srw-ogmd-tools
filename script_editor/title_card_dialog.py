"""Mouse-driven title-card sheet preview, export and staged PNG import."""
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QListWidget, QListWidgetItem, QSplitter, QWidget, QFileDialog,
    QMessageBox, QAbstractItemView)
from title_cards import project_cards


class SheetPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage(); self.layer = 3
        self.setMinimumSize(220, 140)

    def set_png(self, png, layer=3):
        self.image = QImage.fromData(png, 'PNG'); self.layer = layer; self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#0a111b'))
        if self.image.isNull():
            return
        image = self.image
        if self.layer >= 0:
            height = image.height() // 6
            image = image.copy(0, height * self.layer, image.width(), height)
        scale = min((self.width() - 16) / image.width(), (self.height() - 16) / image.height())
        w, h = image.width() * scale, image.height() * scale
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), image)


class TitleCardDialog(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor; self.project = project_cards(editor.project)
        self.library = self.project.library; self.pending = None; self.active = None; self.updating = False
        self.setWindowTitle('Stage title cards'); self.resize(1180, 810)
        layout = QVBoxLayout(self)
        intro = QLabel('Export a full PNG sheet, edit it in your image editor, then import it here. Save the card edit and use Patch edits to build and review the game change.')
        intro.setWordWrap(True); layout.addWidget(intro)
        split = QSplitter(); layout.addWidget(split, 1)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit(); self.search.setPlaceholderText('Find a title, route, or card ID…'); ll.addWidget(self.search)
        self.kind = QComboBox(); self.kind.addItems(['Stage titles', 'Chapter numbers', 'All sheets']); ll.addWidget(self.kind)
        self.list = QListWidget(); self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); ll.addWidget(self.list, 1); split.addWidget(left)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(8, 0, 0, 0)
        self.heading = QLabel(); self.heading.setObjectName('title'); self.heading.setWordWrap(True); rl.addWidget(self.heading)
        controls = QHBoxLayout(); self.language = QComboBox(); self.language.addItems(['English artwork', 'Japanese artwork']); controls.addWidget(self.language)
        self.view = QComboBox(); self.view.addItems(['Solid title layer', 'Full animation sheet', 'Layer 1', 'Layer 2', 'Layer 3', 'Layer 5', 'Layer 6']); controls.addWidget(self.view); controls.addStretch(); rl.addLayout(controls)
        rl.addWidget(QLabel('Bundled artwork'))
        self.original = SheetPreview(); rl.addWidget(self.original, 1)
        self.current_label = QLabel('Current artwork'); rl.addWidget(self.current_label)
        self.current = SheetPreview(); rl.addWidget(self.current, 1)
        self.details = QLabel(); self.details.setWordWrap(True); self.details.setObjectName('subtle'); rl.addWidget(self.details)
        note = QLabel('Each sheet has six animation layers. Preserve the full sheet size, transparent background and layer positions. The preview shows artwork; animation timing is checked in the game. Stage names in menus are separate text.')
        note.setWordWrap(True); note.setObjectName('subtle'); rl.addWidget(note)
        split.addWidget(right); split.setSizes([350, 800])
        actions = QHBoxLayout()
        self.export_source = QPushButton('Export bundled PNG…'); self.export_source.clicked.connect(lambda: self.export_png(True)); actions.addWidget(self.export_source)
        self.export_current = QPushButton('Export current PNG…'); self.export_current.clicked.connect(lambda: self.export_png(False)); actions.addWidget(self.export_current)
        self.import_button = QPushButton('Import edited PNG…'); self.import_button.clicked.connect(self.import_png); actions.addWidget(self.import_button)
        self.save_button = QPushButton('Save card edit'); self.save_button.setObjectName('primary'); self.save_button.clicked.connect(self.save_pending); actions.addWidget(self.save_button)
        self.bundled_button = QPushButton('Stage bundled artwork'); self.bundled_button.clicked.connect(self.stage_bundled); actions.addWidget(self.bundled_button)
        self.reset_button = QPushButton('Remove saved card edit'); self.reset_button.clicked.connect(self.reset); actions.addWidget(self.reset_button)
        layout.addLayout(actions)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        bottom = QHBoxLayout(); bottom.addStretch()
        patch = QPushButton('Patch saved edits…'); patch.clicked.connect(self.patch_saved); bottom.addWidget(patch)
        close = QPushButton('Close'); close.clicked.connect(self.close); bottom.addWidget(close); layout.addLayout(bottom)
        for key, card in self.library.cards.items():
            item = QListWidgetItem(key + ' · ' + card['label']); item.setData(Qt.ItemDataRole.UserRole, key); item.setToolTip(item.text()); self.list.addItem(item)
        self.search.textChanged.connect(self.filter); self.kind.currentIndexChanged.connect(self.filter)
        self.list.currentItemChanged.connect(self.select); self.language.currentIndexChanged.connect(self.change_language); self.view.currentIndexChanged.connect(self.refresh)
        self.filter()
        sid = editor.corpus.by_key.get(editor.key, {}).get('meta', {}).get('scenario_id', 0)
        key = f'st_{sid:03d}'
        item = next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.ItemDataRole.UserRole) == key), None)
        self.list.setCurrentItem(item or self.list.item(49))

    def filter(self, *args):
        terms = self.search.text().casefold().split(); kind = self.kind.currentIndex()
        for i in range(self.list.count()):
            item = self.list.item(i); key = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(not all(t in item.text().casefold() for t in terms) or (kind == 0 and not key.startswith('st_')) or (kind == 1 and not key.startswith('sn_')))
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self.list.doItemsLayout()
            self.list.scrollToItem(item)
        QTimer.singleShot(0, self.reveal_selection)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.reveal_selection)

    def reveal_selection(self):
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self.list.doItemsLayout(); self.list.scrollToItem(item)

    def discard_pending(self):
        if self.pending is None:
            return True
        answer = QMessageBox.question(self, 'Unsaved imported artwork', 'Save the imported card before continuing?', QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_pending()
        self.pending = None
        return True

    def select(self, item, previous):
        if self.updating or item is None:
            return
        if not self.discard_pending():
            self.updating = True; self.list.setCurrentItem(previous); self.updating = False; return
        lang = self.active[1] if self.active else ('en' if self.language.currentIndex() == 0 else 'jp')
        self.active = (item.data(Qt.ItemDataRole.UserRole), lang); self.refresh()

    def change_language(self, *args):
        if self.updating or self.active is None:
            return
        if not self.discard_pending():
            self.updating = True; self.language.setCurrentIndex(0 if self.active[1] == 'en' else 1); self.updating = False; return
        self.active = (self.active[0], 'en' if self.language.currentIndex() == 0 else 'jp'); self.refresh()

    def refresh(self, *args):
        if self.active is None:
            return
        key, lang = self.active; card = self.library.card(key)
        layer = [3, -1, 0, 1, 2, 4, 5][self.view.currentIndex()]
        self.original.set_png(self.library.source_png(key, lang), layer)
        self.current.set_png(self.pending if self.pending is not None else self.project.png(key, lang), layer)
        self.heading.setText(card['label'])
        self.details.setText(f"{key} · {card['width']} × {card['height']} pixels · RGBA PNG\n{card['entry']}")
        self.current_label.setText('Imported artwork · not saved yet' if self.pending is not None else 'Saved edited artwork' if self.project.changed(key, lang) else 'Current artwork · bundled')
        self.save_button.setEnabled(self.pending is not None); self.reset_button.setEnabled(self.pending is not None or self.project.changed(key, lang))
        self.status.setText(f'{self.project.count()} saved card edit(s) · ' + str(self.project.path))
        for i in range(self.list.count()):
            item = self.list.item(i); item_key = item.data(Qt.ItemDataRole.UserRole)
            item.setText(('● ' if self.project.changed(item_key, lang) else '') + item_key + ' · ' + self.library.card(item_key)['label'])

    def export_png(self, original):
        if self.active is None:
            return
        key, lang = self.active
        path, _ = QFileDialog.getSaveFileName(self, 'Export full animation sheet', key + '_' + lang + '.png', 'PNG images (*.png)')
        if not path:
            return
        try:
            png = self.library.source_png(key, lang) if original else self.pending if self.pending is not None else self.project.png(key, lang)
            Path(path).write_bytes(png); self.status.setText('Exported full animation sheet: ' + path)
        except Exception as exc:
            QMessageBox.warning(self, 'Export failed', str(exc))

    def import_png(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import edited full animation sheet', '', 'PNG images (*.png)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 12 * 1024 * 1024:
                raise ValueError('Title-card PNG exceeds 12 MB.')
            png = Path(path).read_bytes(); image = self.library.image(self.active[0], png)
            if image.getchannel('A').getextrema() == (255, 255):
                raise ValueError('The image is opaque. Keep the transparent background.')
            self.pending = png; self.refresh(); self.status.setText('Review the imported artwork above, then click Save card edit.')
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot import this sheet', str(exc))

    def save_pending(self):
        if self.pending is None:
            return True
        try:
            self.project.stage(*self.active, self.pending, force=True); self.pending = None; self.refresh(); return True
        except Exception as exc:
            QMessageBox.warning(self, 'Card edit was not saved', str(exc)); return False

    def stage_bundled(self):
        if not self.discard_pending():
            return
        try:
            self.project.stage(*self.active, self.library.source_png(*self.active), force=True)
            self.refresh()
            self.status.setText('Bundled artwork saved for patching. Click Patch saved edits to build and review it.')
        except Exception as exc:
            QMessageBox.warning(self, 'Card edit was not saved', str(exc))

    def reset(self):
        try:
            self.project.reset(*self.active); self.pending = None; self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot restore artwork', str(exc))

    def patch_saved(self):
        if not self.discard_pending():
            return
        self.editor.patch_game()

    def reject(self):
        if self.discard_pending():
            super().reject()

    def closeEvent(self, event):
        if self.discard_pending():
            event.accept()
        else:
            event.ignore()
