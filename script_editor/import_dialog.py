"""Script import with complete validation, conflict preview, and undo."""
import copy
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QFileDialog,QComboBox,QCheckBox,QPlainTextEdit,QMessageBox,QProgressBar)
from core import EditProject
from dialogs import ResultModel,results_table,Job
from script_import import ScriptImporter

class ImportDialog(QDialog):
    def __init__(self,editor):
        super().__init__(editor);self.editor=editor;self.job=None;self.result=None
        self.setWindowTitle('Import scripts');self.resize(1240,780)
        layout=QVBoxLayout(self)
        intro=QLabel('Import edited scripts by their stable row IDs. Preview every change before saving; unmentioned rows and languages keep their current edits.')
        intro.setWordWrap(True);layout.addWidget(intro)
        line=QHBoxLayout();self.path=QLineEdit();self.path.setPlaceholderText('Choose a JSON/TXT file or an exported script folder');line.addWidget(self.path)
        self.file=QPushButton('Choose file…');self.file.clicked.connect(self.choose_file);line.addWidget(self.file)
        self.folder=QPushButton('Choose folder…');self.folder.clicked.connect(self.choose_folder);line.addWidget(self.folder);layout.addLayout(line)
        options=QHBoxLayout();options.addWidget(QLabel('Files to read in folders:'));self.format=QComboBox();self.format.addItems(['script.json','EN.txt','JP.txt','Bilingual.txt']);options.addWidget(self.format)
        options.addWidget(QLabel('Untagged TXT language:'));self.language=QComboBox();self.language.addItems(['From filename / EN-JP tags','English','Japanese']);options.addWidget(self.language);options.addStretch();layout.addLayout(options)
        note=QLabel('Folder import reads only the chosen format, so old JSON or TXT copies cannot override the files you edited. JSON supports script.json, edits.json and project.json. Keep [row IDs] in text files.');note.setWordWrap(True);note.setObjectName('subtle');layout.addWidget(note)
        merge=QHBoxLayout();self.reset_source=QCheckBox('Also import source-equal values (can reset local edits)');merge.addWidget(self.reset_source);merge.addStretch()
        merge.addWidget(QLabel('Conflicting local edits:'));self.conflicts=QComboBox();self.conflicts.addItems(['Keep current text','Use imported text']);merge.addWidget(self.conflicts);layout.addLayout(merge)
        self.model=ResultModel([('Action','status'),('Script','title'),('Row','id'),('Field','field'),('Current text','before'),('Imported text','after')])
        self.table=results_table(self.model);self.table.setColumnWidth(0,130);self.table.setColumnWidth(1,220);self.table.setColumnWidth(3,90);self.table.setColumnWidth(4,280);layout.addWidget(self.table,1)
        detail=QHBoxLayout();self.before=QPlainTextEdit();self.after=QPlainTextEdit()
        for label,edit in [('Current text',self.before),('Imported text',self.after)]:
            col=QVBoxLayout();col.addWidget(QLabel(label));edit.setReadOnly(True);edit.setMaximumHeight(130);col.addWidget(edit);detail.addLayout(col)
        layout.addLayout(detail);self.table.selectionModel().currentRowChanged.connect(self.show_detail)
        self.status=QLabel('Choose a file or folder, then preview the import.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        buttons=QHBoxLayout();self.undo=QPushButton('Undo last import');self.undo.setEnabled(bool(getattr(editor,'last_import',None)));self.undo.clicked.connect(self.undo_import);buttons.addWidget(self.undo);buttons.addStretch()
        self.preview=QPushButton('Preview import');self.preview.clicked.connect(self.preview_import);buttons.addWidget(self.preview)
        self.apply=QPushButton('Import previewed changes');self.apply.setObjectName('primary');self.apply.setEnabled(False);self.apply.clicked.connect(self.apply_import);buttons.addWidget(self.apply)
        self.close_button=QPushButton('Close');self.close_button.clicked.connect(self.accept);buttons.addWidget(self.close_button);layout.addLayout(buttons)
        self.inputs=[self.path,self.file,self.folder,self.format,self.language,self.reset_source,self.conflicts,self.preview,self.close_button]
        self.path.textChanged.connect(self.invalidate);self.format.currentIndexChanged.connect(self.invalidate);self.language.currentIndexChanged.connect(self.invalidate);self.reset_source.toggled.connect(self.invalidate);self.conflicts.currentIndexChanged.connect(self.update_plan)
    def choose_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Import script file',str(self.editor.project.path.parent),'Scripts (*.json *.txt)')
        if path:self.path.setText(path)
    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'Import a script folder',str(self.editor.corpus.root.parent))
        if path:self.path.setText(path)
    def invalidate(self,*args):
        self.result=None;self.model.set_rows([]);self.apply.setEnabled(False);self.before.clear();self.after.clear();self.status.setText('Import options changed. Preview again.')
    def selected_plan(self):return [r for r in self.result['plan'] if not r['conflict'] or self.conflicts.currentIndex()==1] if self.result else []
    def update_plan(self,*args):
        if not self.result:return
        rows=[{**r,'status':'Keep current' if r['conflict'] and self.conflicts.currentIndex()==0 else 'Replace conflict' if r['conflict'] else 'Import'} for r in self.result['plan']]
        self.model.set_rows(rows);count=len(self.selected_plan());self.apply.setEnabled(bool(count));self.apply.setText(f'Import {count:,} text fields')
        self.status.setText(f'{self.result["files"]} files validated · {len(rows):,} changed fields · {self.result["conflicts"]:,} conflicts · {count:,} fields will be imported. Source-equal values are skipped unless enabled above.')
        if rows:self.table.selectRow(0)
    def show_detail(self,current,previous):
        row=self.model.rows[current.row()] if current.isValid() and current.row()<len(self.model.rows) else {}
        self.before.setPlainText(row.get('before','') or '');self.after.setPlainText(row.get('after','') or '')
    def busy(self,value):
        for control in self.inputs:control.setEnabled(not value)
        self.progress.setVisible(value);self.apply.setEnabled(not value and bool(self.selected_plan()));self.undo.setEnabled(not value and bool(getattr(self.editor,'last_import',None)))
    def preview_import(self):
        if not self.editor.save():return
        self.invalidate();source=self.path.text().strip();fmt=self.format.currentText();language=[None,'en','jp'][self.language.currentIndex()];include=self.reset_source.isChecked()
        snapshot=EditProject(self.editor.corpus,self.editor.project.path);self.busy(True)
        self.job=Job(lambda progress:ScriptImporter(snapshot).preview(source,fmt,language,include,progress))
        self.job.message.connect(self.status.setText);self.job.done.connect(self.previewed);self.job.failed.connect(self.failed);self.job.finished.connect(lambda:self.busy(False));self.job.start()
    def previewed(self,result):self.result=result;self.update_plan()
    def failed(self,message):self.status.setText('Import stopped: '+message);QMessageBox.warning(self,'Import stopped',message)
    def apply_import(self):
        try:
            plan=self.selected_plan()
            if not plan:return
            count=self.editor.project.apply_replacements(plan);self.editor.last_import=copy.deepcopy(plan)
            self.editor.refresh_after_bulk();self.invalidate();self.undo.setEnabled(True);self.status.setText(f'Imported and saved {count:,} text fields. Undo last import is available. Close this window to edit them with the dialogue preview.')
        except Exception as exc:self.failed(str(exc))
    def undo_import(self):
        try:
            self.editor.project.apply_replacements(self.editor.last_import,undo=True);self.editor.last_import=[]
            self.editor.refresh_after_bulk();self.invalidate();self.undo.setEnabled(False);self.status.setText('Last import undone and saved.')
        except Exception as exc:self.failed(str(exc))
    def reject(self):
        if self.job and self.job.isRunning():return
        super().reject()
    def closeEvent(self,event):
        if self.job and self.job.isRunning():event.ignore()
        else:event.accept()
