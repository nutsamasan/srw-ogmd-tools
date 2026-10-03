"""Paired Seishin name/description editing backed by the shared edit project."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QWidget, QTabWidget, QCheckBox, QMessageBox, QScrollArea)

KEY = '06_Game_data/Spirit_commands'


class SeishinDialog(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.project = editor.project
        self.commands = {}
        for row in editor.corpus.load(KEY)[0]['rows']:
            self.commands.setdefault(row['fixed_logical'], {})[row['fixed_field']] = row
        if any(set(fields) != {'name', 'description'} for fields in self.commands.values()):
            raise ValueError('The Seishin library is missing paired text fields.')
        self.current = None
        self.loading = False
        self.pending = False
        self.setWindowTitle('Seishin names / descriptions')
        self.resize(1180, 800)
        self.setMinimumSize(880, 650)
        layout = QVBoxLayout(self)
        title = QLabel('Seishin · names and descriptions'); title.setObjectName('brand'); layout.addWidget(title)
        note = QLabel('Select a command, edit its name and description, then Save command. Saved changes are included in Patch edits, Export edits and Full English patcher → Use current editor edits.')
        note.setWordWrap(True); layout.addWidget(note)
        split = QSplitter(Qt.Orientation.Horizontal); layout.addWidget(split, 1)
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit(); self.search.setPlaceholderText('Find ID, English / Japanese name or description…'); lv.addWidget(self.search)
        self.reserved = QCheckBox('Show reserved entries (0–1)'); lv.addWidget(self.reserved)
        self.list = QListWidget(); lv.addWidget(self.list, 1); split.addWidget(left)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(8, 0, 0, 0)
        self.command_label = QLabel(); self.command_label.setObjectName('title'); rv.addWidget(self.command_label)
        self.tabs = QTabWidget(); rv.addWidget(self.tabs, 1)
        self.names = {}; self.descriptions = {}; self.sources = {}
        for lang, label in (('en', 'English'), ('jp', 'Japanese')):
            pane = QWidget(); pv = QVBoxLayout(pane)
            pv.addWidget(QLabel('Name'))
            name = QLineEdit(); name.setAccessibleName(label + ' Seishin name'); pv.addWidget(name)
            pv.addWidget(QLabel('Description'))
            description = QPlainTextEdit(); description.setAccessibleName(label + ' Seishin description'); description.setTabChangesFocus(True); pv.addWidget(description, 1)
            source = QLabel(); source.setWordWrap(True); source.setTextFormat(Qt.TextFormat.PlainText); source.setObjectName('subtle'); pv.addWidget(source)
            self.names[lang] = name; self.descriptions[lang] = description; self.sources[lang] = source
            name.textChanged.connect(self.changed); description.textChanged.connect(self.changed)
            self.tabs.addTab(pane, label)
        from app import DataPreview
        self.preview = DataPreview(editor.metrics)
        area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(self.preview); rv.addWidget(area, 1)
        self.fit = QLabel(); self.fit.setWordWrap(True); rv.addWidget(self.fit)
        split.addWidget(right); split.setSizes([340, 840])
        actions = QHBoxLayout()
        self.restore_button = QPushButton('Restore source for this language'); self.restore_button.clicked.connect(self.restore_source); actions.addWidget(self.restore_button)
        actions.addStretch()
        self.save_button = QPushButton('Save command'); self.save_button.setObjectName('primary'); self.save_button.clicked.connect(self.save_pending); actions.addWidget(self.save_button)
        self.patch_button = QPushButton('Patch saved edits…'); self.patch_button.clicked.connect(self.patch_saved); actions.addWidget(self.patch_button)
        close = QPushButton('Close'); close.clicked.connect(self.close); actions.addWidget(close); layout.addLayout(actions)
        self.status = QLabel('Names and descriptions only; command effects and SP costs stay as configured.'); self.status.setWordWrap(True); layout.addWidget(self.status)
        for logical in sorted(self.commands):
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, logical); self.list.addItem(item); self.label_item(item)
        self.list.currentItemChanged.connect(self.select_command)
        self.search.textChanged.connect(self.filter); self.reserved.toggled.connect(self.filter)
        self.tabs.currentChanged.connect(self.refresh_preview)
        self.filter()
        self.list.setCurrentRow(2)

    def language(self):
        return 'en' if self.tabs.currentIndex() == 0 else 'jp'

    def label_item(self, item):
        logical = item.data(Qt.ItemDataRole.UserRole); fields = self.commands[logical]
        row = fields['name']; values = self.project.values(KEY, row)
        edited = any(self.project.changed(KEY, row) for row in fields.values())
        item.setText(f"{logical:02d} · {values['en']} · {values['jp']}" + ('  *' if edited else ''))
        item.setToolTip(item.text())

    def filter(self, *args):
        terms = self.search.text().casefold().split()
        for i in range(self.list.count()):
            item = self.list.item(i); logical = item.data(Qt.ItemDataRole.UserRole)
            text = str(logical) + ' ' + f'{logical:02d}'
            for row in self.commands[logical].values():
                values = self.project.values(KEY, row); text += ' ' + values['en'] + ' ' + values['jp']
            item.setHidden((logical < 2 and not self.reserved.isChecked()) or not all(t in text.casefold() for t in terms))

    def select_command(self, item, previous):
        if self.loading or item is None:
            return
        if not self.save_pending():
            self.loading = True; self.list.setCurrentItem(previous); self.loading = False; return
        self.current = item.data(Qt.ItemDataRole.UserRole)
        self.loading = True
        for lang in ('en', 'jp'):
            fields = self.commands[self.current]
            self.names[lang].setText(self.project.values(KEY, fields['name'])[lang])
            self.descriptions[lang].setPlainText(self.project.values(KEY, fields['description'])[lang])
            self.sources[lang].setText('Original name: ' + fields['name'][lang] + '\nOriginal description: ' + fields['description'][lang])
        self.loading = False; self.pending = False
        self.command_label.setText(f'Command {self.current:02d}')
        self.refresh_preview()

    def changed(self, *args):
        if self.loading or self.current is None:
            return
        self.pending = True; self.status.setText('Unsaved command changes · Save command, or select another command to save.')
        self.refresh_preview()

    def refresh_preview(self, *args):
        if self.current is None:
            return
        lang = self.language(); name = self.names[lang].text(); text = self.descriptions[lang].toPlainText()
        self.preview.set_content(name, text, 'Seishin · ' + ('English' if lang == 'en' else 'Japanese'))
        assessed = self.editor.metrics.assess(text)
        warnings = []
        if assessed['missing']: warnings.append('unsupported glyphs: ' + ''.join(assessed['missing']))
        if assessed['overflow']: warnings.append('wide description lines')
        self.fit.setText((' · '.join(warnings) + '. ' if warnings else '') + 'Native font reference; the preview frame is reconstructed.')

    def save_pending(self):
        if not self.pending or self.current is None:
            return True
        values = {}
        for lang in ('en', 'jp'):
            name = self.names[lang].text(); description = self.descriptions[lang].toPlainText()
            if any(c in name for c in '\n\r\0@<>') or '\0' in description:
                self.status.setText('Cannot save: names must be one line without control markers; NUL is not allowed.')
                return False
            values[lang] = (name, description)
        try:
            for lang, (name, description) in values.items():
                fields = self.commands[self.current]
                self.project.set(KEY, fields['name'], lang, name)
                self.project.set(KEY, fields['description'], lang, description)
            if not self.editor.save():
                return False
        except Exception as exc:
            self.status.setText('Cannot save command: ' + str(exc)); return False
        self.pending = False
        item = next(self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.ItemDataRole.UserRole) == self.current)
        self.label_item(item); self.filter()
        self.status.setText('Command saved in the shared project. Use Patch edits to apply it to the game.')
        return True

    def restore_source(self):
        if self.current is None:
            return
        lang = self.language(); fields = self.commands[self.current]
        self.names[lang].setText(fields['name'][lang]); self.descriptions[lang].setPlainText(fields['description'][lang])

    def patch_saved(self):
        if self.save_pending():
            self.editor.patch_game()

    def closeEvent(self, event):
        if not self.save_pending():
            event.ignore(); return
        if self.editor.key == KEY:
            row = self.editor.model.rows[self.editor.row_index] if self.editor.row_index is not None else None
            self.editor.select_collection(self.editor.tree.currentItem())
            if row: self.editor.open_line(KEY, row['id'])
        event.accept()

    def reject(self):
        self.close()
