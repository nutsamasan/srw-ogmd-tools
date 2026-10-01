"""Corpus-wide replacement and native game patch workflows."""
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,QThread,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QPlainTextEdit,
    QComboBox,QCheckBox,QTableView,QHeaderView,QAbstractItemView,QMessageBox,QLineEdit,QFileDialog,QProgressBar,QWidget)
from core import EditProject,atomic_json,sha
from patcher import default_targets,prepare_patch,install_patch
from iso_patcher import prepare_iso_patch,write_patched_iso
from target_selection import installed_target,runtime_hint


class ResultModel(QAbstractTableModel):
    def __init__(self,columns):super().__init__();self.columns=columns;self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return len(self.columns)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:return self.columns[section][0]
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            value=str(self.rows[index.row()].get(self.columns[index.column()][1],''))
            return value.replace('\n',' ↵ ') if role==Qt.ItemDataRole.DisplayRole else value
    def set_rows(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()


def results_table(model):
    table=QTableView();table.setModel(model);table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setWordWrap(False);table.verticalHeader().hide();table.verticalHeader().setDefaultSectionSize(32)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for i in range(len(model.columns)):table.setColumnWidth(i,150)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class SearchDialog(QDialog):
    def __init__(self,editor):
        super().__init__(editor);self.editor=editor;self.plan=[];self.setWindowTitle('Find and replace in all scripts');self.resize(1240,760)
        layout=QVBoxLayout(self);layout.addWidget(QLabel(f'Search all {len(editor.corpus.collections)} collections, including pilot names, mech names, glossary text, and current edits. Double-click a result to open its row.'))
        fields=QHBoxLayout()
        for label,attr in [('Find','find'),('Replace with','replacement')]:
            box=QVBoxLayout();box.addWidget(QLabel(label));edit=QPlainTextEdit();edit.setMaximumHeight(85);edit.setAccessibleName(label)
            setattr(self,attr,edit);box.addWidget(edit);fields.addLayout(box)
        layout.addLayout(fields);options=QHBoxLayout()
        self.language=QComboBox();self.language.addItems(['English','Japanese','Both languages']);options.addWidget(self.language)
        self.speakers=QCheckBox('Include speaker names');self.speakers.setChecked(True);options.addWidget(self.speakers)
        self.case=QCheckBox('Match case');options.addWidget(self.case);self.words=QCheckBox('Whole words');options.addWidget(self.words);options.addStretch()
        search=QPushButton('Find all / preview');search.clicked.connect(self.search);options.addWidget(search);layout.addLayout(options)
        self.summary=QLabel('Literal search. Line breaks and replacement text are used exactly as typed.');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.model=ResultModel([('Script','title'),('Row','id'),('Field','field'),('Matches','count'),('Current text','before'),('Replacement preview','after')])
        self.table=results_table(self.model);self.table.setColumnWidth(0,200);self.table.setColumnWidth(3,75);self.table.setColumnWidth(4,320)
        self.table.doubleClicked.connect(self.open_result);layout.addWidget(self.table,1)
        detail=QHBoxLayout();self.before=QPlainTextEdit();self.after=QPlainTextEdit()
        for edit in (self.before,self.after):edit.setReadOnly(True);edit.setMaximumHeight(140);detail.addWidget(edit)
        layout.addLayout(detail);self.table.selectionModel().currentRowChanged.connect(self.show_detail)
        buttons=QHBoxLayout();self.undo=QPushButton('Undo last Replace all');self.undo.setEnabled(bool(getattr(editor,'last_bulk',None)));self.undo.clicked.connect(self.undo_replace);buttons.addWidget(self.undo);buttons.addStretch()
        self.replace=QPushButton('Replace all previewed matches');self.replace.setObjectName('primary');self.replace.setEnabled(False);self.replace.clicked.connect(self.replace_all);buttons.addWidget(self.replace)
        close=QPushButton('Close');close.clicked.connect(self.accept);buttons.addWidget(close);layout.addLayout(buttons)
        self.find.textChanged.connect(self.invalidate);self.replacement.textChanged.connect(self.invalidate);self.language.currentIndexChanged.connect(self.invalidate)
        for control in (self.speakers,self.case,self.words):control.toggled.connect(self.invalidate)
    def invalidate(self,*args):
        self.plan=[];self.replace.setEnabled(False);self.model.set_rows([]);self.before.clear();self.after.clear();self.summary.setText('Search options changed. Click Find all / preview.')
    def search(self):
        try:
            languages=[('en',),('jp',),('en','jp')][self.language.currentIndex()]
            self.plan=self.editor.project.find_all(self.find.toPlainText(),self.replacement.toPlainText(),languages,self.speakers.isChecked(),self.case.isChecked(),self.words.isChecked())
            self.model.set_rows(self.plan);n=sum(x['count'] for x in self.plan);files=len({x['key'] for x in self.plan})
            self.summary.setText(f'{n:,} occurrences · {len(self.plan):,} text fields · {files} script files. Review the changes below.')
            changed=[x for x in self.plan if x['before']!=x['after']];self.replace.setEnabled(bool(changed))
            self.replace.setText(f'Replace all · {sum(x["count"] for x in changed):,} occurrences')
            if self.plan:self.table.selectRow(0)
        except Exception as exc:QMessageBox.warning(self,'Search failed',str(exc))
    def show_detail(self,current,previous):
        row=self.plan[current.row()] if current.isValid() and current.row()<len(self.plan) else {}
        self.before.setPlainText(row.get('before',''));self.after.setPlainText(row.get('after',''))
    def replace_all(self):
        try:
            changed=[x for x in self.plan if x['before']!=x['after']]
            count=self.editor.project.apply_replacements(changed);self.editor.last_bulk=copy.deepcopy(changed)
            self.editor.refresh_after_bulk();self.invalidate();self.undo.setEnabled(bool(changed))
            self.summary.setText(f'Replaced and saved {count:,} text fields. Undo last Replace all is available; original scripts are unchanged.')
        except Exception as exc:QMessageBox.warning(self,'Replacement was not applied',str(exc))
    def undo_replace(self):
        try:
            self.editor.project.apply_replacements(self.editor.last_bulk,undo=True);self.editor.last_bulk=[]
            self.editor.refresh_after_bulk();self.invalidate();self.undo.setEnabled(False);self.summary.setText('Last bulk replacement undone and saved.')
        except Exception as exc:QMessageBox.warning(self,'Cannot undo replacement',str(exc))
    def open_result(self,index):
        if not index.isValid():return
        row=self.plan[index.row()];self.editor.open_line(row['key'],row['id']);self.accept()


class Job(QThread):
    message=Signal(str);done=Signal(object);failed=Signal(str)
    def __init__(self,function):super().__init__();self.function=function
    def run(self):
        try:self.done.emit(self.function(self.message.emit))
        except Exception as exc:self.failed.emit(str(exc))


class PatchDialog(QDialog):
    def __init__(self,editor,home):
        super().__init__(editor);self.editor=editor;self.home=home;self.manifest=None;self.completed_manifest=None;self.job=None;self.setWindowTitle('Patch text and title-card edits');self.resize(1240,860)
        layout=QVBoxLayout(self)
        from title_cards import project_cards
        intro=QLabel(f'Build a patch with your text edits, saved title cards ({project_cards(editor.project).count()} total), and the selected backlog fix. Review the changes, then install to a game folder or create a patched ISO.');intro.setWordWrap(True);layout.addWidget(intro)
        choice=QHBoxLayout();choice.addWidget(QLabel('Patch destination:'));self.mode=QComboBox();self.mode.addItems(['Game folders / RPCS3','ISO image']);choice.addWidget(self.mode);choice.addStretch();layout.addLayout(choice)
        self.config_path=home/'patch_settings.json'
        try:self.config=json.loads(self.config_path.read_text(encoding='utf8')) if self.config_path.exists() else {}
        except Exception:self.config={}
        targets=self.config.get('targets') or [str(p) for p in default_targets(editor.corpus)]
        self.paths=[];self.controls=[self.mode]
        self.folder_group=QWidget();folder_layout=QVBoxLayout(self.folder_group);folder_layout.setContentsMargins(0,0,0,0);layout.addWidget(self.folder_group)
        for i,label in enumerate(['Game copy or installed data · USRDIR/PSARC','Second matching copy · USRDIR/PSARC (optional)']):
            folder_layout.addWidget(QLabel(label));line=QHBoxLayout();field=QLineEdit(targets[i] if len(targets)>i else '')
            self.paths.append(field);line.addWidget(field);browse=QPushButton('Browse…');browse.clicked.connect(lambda checked=False,field=field:self.browse(field));line.addWidget(browse);folder_layout.addLayout(line)
            self.controls.extend([field,browse]);field.textChanged.connect(self.invalidate)
        self.iso_group=QWidget();iso_layout=QVBoxLayout(self.iso_group);iso_layout.setContentsMargins(0,0,0,0);layout.addWidget(self.iso_group);self.iso_group.hide()
        candidates=sorted((editor.corpus.root.parents[1]/'PS3').glob('*.iso'))
        default_iso=self.config.get('iso_source') or (str(candidates[0]) if candidates else '')
        self.iso_source=QLineEdit(default_iso);self.iso_output=QLineEdit(self.config.get('iso_output') or (str(Path(default_iso).with_name(Path(default_iso).stem+' - edited.iso')) if default_iso else ''))
        for label,field,save in [('Source ISO (kept intact)',self.iso_source,False),('New patched ISO',self.iso_output,True)]:
            iso_layout.addWidget(QLabel(label));line=QHBoxLayout();line.addWidget(field);browse=QPushButton('Browse…');browse.clicked.connect(lambda checked=False,save=save:self.browse_iso(save));line.addWidget(browse);iso_layout.addLayout(line)
            self.controls.extend([field,browse])
        self.iso_source.textChanged.connect(self.invalidate)
        options=QHBoxLayout();options.addWidget(QLabel('Apply edits from:'));self.language=QComboBox();self.language.addItems(['English','Japanese']);options.addWidget(self.language)
        self.normalize=QCheckBox('Use supported equivalent glyphs');self.normalize.setChecked(True);options.addWidget(self.normalize);options.addStretch();layout.addLayout(options)
        self.controls.extend([self.language,self.normalize]);self.language.currentIndexChanged.connect(self.invalidate);self.normalize.toggled.connect(self.invalidate)
        self.backlog=QCheckBox('Fix backlog scrollbar overlap');self.backlog.setChecked(self.config.get('backlog_fix',True))
        self.backlog.setToolTip('Reserve space before the Triangle backlog scrollbar. Works with or without text edits; already fixed layouts are preserved.')
        layout.addWidget(self.backlog);self.controls.append(self.backlog);self.backlog.toggled.connect(self.invalidate)
        runtime_row=QHBoxLayout();runtime_row.addWidget(QLabel('RPCS3 folder:'))
        self.runtime=QLineEdit(runtime_hint(home,self.config));runtime_row.addWidget(self.runtime)
        runtime_browse=QPushButton('Browse…');runtime_browse.clicked.connect(self.browse_runtime);runtime_row.addWidget(runtime_browse)
        self.use_installed=QPushButton('Use installed game data');self.use_installed.clicked.connect(self.select_installed);runtime_row.addWidget(self.use_installed);layout.addLayout(runtime_row)
        self.controls.extend([self.runtime,runtime_browse,self.use_installed])
        self.note=QLabel();self.note.setWordWrap(True);self.note.setObjectName('subtle');layout.addWidget(self.note)
        self.model=ResultModel([('Archive','archive'),('Asset','entry'),('Row / card','id'),('Field','field'),('Current','before'),('Patched','after')])
        self.table=results_table(self.model);self.table.setColumnWidth(0,80);self.table.setColumnWidth(1,210);self.table.setColumnWidth(3,80);self.table.setColumnWidth(4,280);layout.addWidget(self.table,1)
        detail=QHBoxLayout();self.before=QPlainTextEdit();self.after=QPlainTextEdit()
        for edit in (self.before,self.after):edit.setReadOnly(True);edit.setMaximumHeight(130);detail.addWidget(edit)
        layout.addLayout(detail);self.table.selectionModel().currentRowChanged.connect(self.show_detail)
        from title_card_dialog import SheetPreview
        self.card_review=QWidget();card_layout=QVBoxLayout(self.card_review)
        self.card_view=QComboBox();self.card_view.addItems(['Solid title layer','Full animation sheet','Layer 1','Layer 2','Layer 3','Layer 5','Layer 6'])
        self.card_view.currentIndexChanged.connect(lambda:self.show_detail(self.table.currentIndex(),None));card_layout.addWidget(self.card_view)
        images=QHBoxLayout();card_layout.addLayout(images)
        self.card_before=SheetPreview();self.card_after=SheetPreview()
        for title,preview in [('Current game artwork',self.card_before),('Patched artwork',self.card_after)]:
            column=QVBoxLayout();column.addWidget(QLabel(title));column.addWidget(preview);images.addLayout(column)
        self.card_review.setMaximumHeight(235);self.card_review.hide();layout.addWidget(self.card_review)
        self.status=QLabel('Ready to build. No game files have been changed.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        buttons=QHBoxLayout();self.restore=QPushButton('Restore previous game files…');self.restore.clicked.connect(self.restore_patch);buttons.addWidget(self.restore);buttons.addStretch()
        self.native_font=QPushButton('Embed font / battle text fix…');self.native_font.clicked.connect(self.embed_font);buttons.addWidget(self.native_font)
        self.runtime_setup=QPushButton('RPCS3 compatibility');self.runtime_setup.setEnabled(False);self.runtime_setup.clicked.connect(self.configure_runtime);buttons.addWidget(self.runtime_setup)
        self.build=QPushButton('Build patch preview');self.build.clicked.connect(self.build_patch);buttons.addWidget(self.build)
        self.install=QPushButton('Back up and install');self.install.setObjectName('primary');self.install.setEnabled(False);self.install.clicked.connect(self.install_prepared);buttons.addWidget(self.install)
        self.close_button=QPushButton('Close');self.close_button.clicked.connect(self.accept);buttons.addWidget(self.close_button);layout.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self.change_mode);self.mode.setCurrentIndex(self.config.get('mode',0));self.change_mode()
    def change_mode(self,*args):
        iso=self.mode.currentIndex()==1;self.folder_group.setVisible(not iso);self.iso_group.setVisible(iso);self.restore.setVisible(not iso)
        self.install.setText('Create patched ISO' if iso else 'Back up and install');self.invalidate()
        self.note.setText('OGMD PS3 BLJS10335 · Decrypted ISO. Applies selected-language edits and the checked backlog fix. Unedited text stays as in the source ISO. The output preserves the disc layout and size; allow space for a full ISO copy.' if iso else 'OGMD PS3 BLJS10335 · For an ISO game, use installed game data to apply edits and the selected backlog fix. A second folder is optional and must already match. Close RPCS3 before installation or restore.')
        self.status.setText('Ready to build an ISO patch preview.' if iso else 'Ready to build a game folder patch preview.')
    def browse_iso(self,save):
        if save:path,_=QFileDialog.getSaveFileName(self,'Choose a NEW output ISO',self.iso_output.text(),'PS3 ISO (*.iso)')
        else:path,_=QFileDialog.getOpenFileName(self,'Choose the source OGMD PS3 ISO',self.iso_source.text(),'PS3 ISO (*.iso)')
        if path:
            if save:self.iso_output.setText(path)
            else:
                self.iso_source.setText(path);self.iso_output.setText(str(Path(path).with_name(Path(path).stem+' - edited.iso')))
    def browse(self,field):
        path=QFileDialog.getExistingDirectory(self,'Choose the game USRDIR/PSARC folder',field.text())
        if path:field.setText(path)
    def browse_runtime(self):
        path=QFileDialog.getExistingDirectory(self,'Choose the folder containing rpcs3.exe',self.runtime.text())
        if path:self.runtime.setText(path)
    def select_installed(self):
        try:target=installed_target(self.runtime.text().strip())
        except Exception as exc:self.failed(str(exc));return
        self.mode.setCurrentIndex(0);self.paths[0].setText(str(target));self.paths[1].clear()
        self.save_settings()
        self.status.setText('Selected installed OGMD data only. The ISO stays unchanged. Build the patch preview next.')
    def save_settings(self):
        self.config.update(targets=[p.text().strip() for p in self.paths if p.text().strip()],
            runtime=self.runtime.text().strip(),mode=self.mode.currentIndex(),
            iso_source=self.iso_source.text().strip(),iso_output=self.iso_output.text().strip(),backlog_fix=self.backlog.isChecked())
        atomic_json(self.config_path,self.config)
    def invalidate(self,*args):
        self.manifest=None
        if hasattr(self,'install'):self.install.setEnabled(False);self.model.set_rows([])
        if hasattr(self,'card_review'):self.card_review.hide()
    def show_detail(self,current,previous):
        row=self.model.rows[current.row()] if current.isValid() else {}
        self.before.setPlainText(row.get('before',''));self.after.setPlainText(row.get('after',''))
        if hasattr(self,'card_review'):
            self.card_review.setVisible(bool(row.get('title_card')))
            if row.get('title_card'):
                import base64
                layer=[3,-1,0,1,2,4,5][self.card_view.currentIndex()]
                self.card_before.set_png(base64.b64decode(row['before_png']),layer)
                self.card_after.set_png(base64.b64decode(row['after_png']),layer)
    def busy(self,value):
        for control in self.controls+[self.build,self.restore,self.close_button,self.native_font]:control.setEnabled(not value)
        self.install.setEnabled(not value and self.manifest is not None);self.progress.setVisible(value)
        self.runtime_setup.setEnabled(not value and self.completed_manifest is not None)
    def run_job(self,function,finished):
        self.busy(True);self.job=Job(function);self.job.message.connect(self.status.setText)
        self.job.done.connect(finished);self.job.failed.connect(self.failed);self.job.finished.connect(lambda:self.busy(False));self.job.start()
    def failed(self,message):self.status.setText('Stopped: '+message);QMessageBox.warning(self,'Patch operation stopped',message)
    def build_patch(self):
        if not self.editor.save():return
        self.invalidate();targets=[p.text().strip() for p in self.paths if p.text().strip()]
        self.save_settings()
        snapshot=EditProject(self.editor.corpus,self.editor.project.path);language='en' if self.language.currentIndex()==0 else 'jp'
        output=self.home/'patches'/datetime.now().strftime('patch_%Y%m%d_%H%M%S_%f');normalize=self.normalize.isChecked()
        backlog=self.backlog.isChecked()
        if self.mode.currentIndex()==1:
            source=self.iso_source.text().strip()
            self.run_job(lambda progress:prepare_iso_patch(snapshot,language,source,output,self.editor.metrics,normalize,progress,backlog=backlog),self.built)
        else:self.run_job(lambda progress:prepare_patch(snapshot,language,targets,output,self.editor.metrics,normalize,progress,backlog=backlog),self.built)
    def built(self,manifest):
        self.manifest=Path(manifest);doc=json.loads(self.manifest.read_text(encoding='utf8'))
        layouts=doc.get('layout_fixes',[])
        rows=doc['review']+[dict(archive='General2d',entry='Backlog window',id='Backlog',field='Margin',
            before='Already fixed' if item['already_applied'] else 'Text can overlap the scrollbar',
            after='Space reserved before the scrollbar') for item in layouts]
        self.model.set_rows(rows)
        action='create the patched ISO' if doc.get('kind')=='ogmd-iso' else 'install'
        self.status.setText(f'Verified {len(doc["archives"])} archives · {len(doc["review"]):,} edited fields / native uses · {sum(r["normalized"] for r in doc["review"])} glyph normalizations. Review, then {action}. Build: {self.manifest.parent}')
        if layouts:self.status.setText(self.status.text()+' · Backlog margin verified.')
        if not doc['archives']:
            self.manifest=None;self.install.setEnabled(False);self.status.setText('The backlog fix is already applied. No game files need changing.')
        if rows:self.table.selectRow(0)
    def install_prepared(self):
        if not self.manifest:return
        doc=json.loads(self.manifest.read_text(encoding='utf8'))
        from title_cards import project_fingerprint,CardProject,project_cards
        cards=project_cards(self.editor.project)
        try:
            if CardProject(cards.path).file_hash!=cards.file_hash:raise ValueError('Title-card edits changed on disk. Reopen the editor and build again.')
        except Exception as exc:
            self.invalidate();self.failed(str(exc));return
        if project_fingerprint(self.editor.project)!=doc['project_sha256']:
            self.invalidate();self.failed('Your edits changed. Build the patch again.');return
        if doc.get('kind')=='ogmd-iso':
            output=self.iso_output.text().strip()
            if not output:self.failed('Choose a new output ISO filename.');return
            self.config['iso_output']=output;atomic_json(self.config_path,self.config)
            self.run_job(lambda progress:write_patched_iso(self.manifest,output,progress),self.iso_written)
        else:self.run_job(lambda progress:install_patch(self.manifest,progress=progress),self.installed)
    def iso_written(self,result):
        self.completed_manifest=self.manifest
        self.manifest=None;self.status.setText('Patched ISO created and fully verified: '+result['output']+' · Source preserved. Checksum report saved beside the ISO.')
    def installed(self,result):
        self.completed_manifest=self.manifest
        self.config['last_patch']=str(self.manifest);atomic_json(self.config_path,self.config);self.manifest=None
        self.status.setText('Patch installed and verified in every selected game copy. Backups saved. Start the game fresh to read the edited text.')
    def configure_runtime(self):
        from runtime_setup import setup_runtime
        if not self.completed_manifest:return
        assets=self.editor.assets/'runtime'
        runtime=self.runtime.text().strip();manifest=self.completed_manifest
        self.config['runtime']=runtime;atomic_json(self.config_path,self.config)
        self.run_job(lambda progress:setup_runtime(runtime,manifest,assets,progress,font_mode='compatibility-only'),
            lambda result:self.status.setText('RPCS3 compatibility configured. Font patches were not changed. Backup: '+result['setup_plan']+' · Start the game fresh.'))
    def embed_font(self):
        from full_dialog import FullPatchDialog
        dialog=FullPatchDialog(self.home.parent/'full_patcher',self.editor)
        dialog.font_only.setChecked(True);dialog.runtime.setText(self.runtime.text())
        if self.mode.currentIndex()==1 and self.iso_source.text().strip():
            dialog.mode.setCurrentIndex(0);dialog.source.setText(self.iso_source.text())
            p=Path(self.iso_source.text());dialog.output.setText(str(p.with_name(p.stem+' - embedded font.iso')))
        dialog.exec()
    def restore_patch(self):
        filename,_=QFileDialog.getOpenFileName(self,'Choose the installed patch.json to restore',self.config.get('last_patch',str(self.home/'patches')),'Patch manifest (patch.json)')
        if not filename:return
        try:
            doc=json.loads(Path(filename).read_text(encoding='utf8'))
            message='Restore the previous game archives from this patch backup?\n\n'+'\n'.join(doc['targets'])+'\n\nPatch: '+str(Path(filename).parent)
            if QMessageBox.question(self,'Restore game files',message)!=QMessageBox.StandardButton.Yes:return
            self.manifest=None;self.run_job(lambda progress:install_patch(filename,restore=True,progress=progress),lambda result:self.status.setText('Previous game archives restored and verified. Editor text edits are unchanged.'))
        except Exception as exc:self.failed(str(exc))
    def reject(self):
        if self.job and self.job.isRunning():return
        super().reject()
    def closeEvent(self,event):
        if self.job and self.job.isRunning():event.ignore()
        else:event.accept()
