"""Standalone complete-game patcher UI, also accessible from the editor."""
import json
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QPushButton,
    QFileDialog,QPlainTextEdit,QCheckBox,QProgressBar,QMessageBox)
from core import atomic_json
from dialogs import Job
from full_patch import package_info,prepare_full_patch,prepare_font_patch,write_full_game,source_folder
from runtime_setup import setup_runtime,restore_setup


class FullPatchDialog(QDialog):
    def __init__(self,home,parent=None):
        super().__init__(parent);self.home=Path(home);self.manifest=None;self.setup_plan=None;self.output_ready=False;self.job=None
        self.setWindowTitle('OGMD Full English Patcher 1.6.4');self.resize(1050,920)
        self.config_path=self.home/'settings.json'
        try:self.config=json.loads(self.config_path.read_text(encoding='utf8'))
        except (OSError,ValueError):self.config={}
        layout=QVBoxLayout(self)
        title=QLabel('OGMD · Full English patch');title.setObjectName('brand');layout.addWidget(title)
        intro=QLabel('Create a separate English ISO or game folder with proportional fonts and battle text fitting built in. RPCS3 only; physical PS3 support has not been validated.');intro.setWordWrap(True);layout.addWidget(intro)
        row=QHBoxLayout();row.addWidget(QLabel('Source type'));self.mode=QComboBox();self.mode.addItems(['ISO image','Game folder']);row.addWidget(self.mode);row.addStretch();layout.addLayout(row)
        self.mode.setCurrentIndex(self.config.get('mode',0))
        self.controls=[self.mode]
        self.font_only=QCheckBox('Font / battle text fix only · upgrade an existing game and keep its current text');layout.addWidget(self.font_only);self.controls.append(self.font_only)
        self.source=self.path_row(layout,'Source game · vanilla Japanese for full translation; existing game for font / battle text fix only',self.config.get('source',''),lambda:self.browse_source())
        source_note=QLabel('Select a boot ISO or complete disc folder containing PS3_GAME. For installed USRDIR/PSARC data, use the editor’s Patch edits.');source_note.setWordWrap(True);source_note.setObjectName('subtle');layout.addWidget(source_note)
        self.output=self.path_row(layout,'New game output',self.config.get('output',''),lambda:self.browse_output())
        self.data=self.path_row(layout,'Release data folder',str(self.home/'data'),lambda:self.browse_folder(self.data,'Choose release data'))
        self.edits=self.path_row(layout,'Editor corrections (optional · patch_edits.json from Export edits)','',self.browse_edits)
        if parent is not None and hasattr(parent,'project'):
            use_edits=QPushButton('Use current editor edits');use_edits.clicked.connect(self.use_current_edits)
            self.use_edits_button=use_edits;layout.addWidget(use_edits);self.controls.append(use_edits)
        self.runtime=self.path_row(layout,'RPCS3 folder',self.config.get('runtime',''),lambda:self.browse_folder(self.runtime,'Choose the folder containing rpcs3.exe'))
        self.setup=QCheckBox('Set up RPCS3 after creating the game output');self.setup.setChecked(True);layout.addWidget(self.setup);self.controls.append(self.setup)
        note=QLabel('Proportional text, apostrophe spacing and battle subtitle fitting are embedded in EBOOT; no font YAML is needed. Optional RPCS3 setup applies compatibility settings and removes our legacy font patch with backups. Full translation also synchronizes installed data; Font / battle text fix only keeps it intact. Close the selected RPCS3 before setup.');note.setWordWrap(True);note.setObjectName('subtle');layout.addWidget(note)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        self.status=QLabel('Ready. Choose the vanilla source and a new output location.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        buttons=QHBoxLayout();self.open_button=QPushButton('Open build…');self.open_button.clicked.connect(self.open_build);buttons.addWidget(self.open_button)
        self.restore=QPushButton('Restore RPCS3 setup…');self.restore.clicked.connect(self.restore_runtime);buttons.addWidget(self.restore)
        self.configure=QPushButton('Set up RPCS3');self.configure.setEnabled(False);self.configure.clicked.connect(self.configure_runtime);buttons.addWidget(self.configure);buttons.addStretch()
        self.build=QPushButton('Build and verify patch');self.build.clicked.connect(self.build_patch);buttons.addWidget(self.build)
        self.write=QPushButton('Create English output');self.write.setObjectName('primary');self.write.setEnabled(False);self.write.clicked.connect(self.write_game);buttons.addWidget(self.write)
        self.close_button=QPushButton('Close');self.close_button.clicked.connect(self.close);buttons.addWidget(self.close_button);layout.addLayout(buttons)
        for field in (self.source,self.data,self.edits):field.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.font_only.toggled.connect(self.invalidate)
        self.describe_release()
    def path_row(self,layout,label,value,callback):
        layout.addWidget(QLabel(label));row=QHBoxLayout();field=QLineEdit(value);row.addWidget(field);button=QPushButton('Browse…');button.clicked.connect(callback);row.addWidget(button);layout.addLayout(row);self.controls.extend([field,button]);return field
    def browse_folder(self,field,title):
        path=QFileDialog.getExistingDirectory(self,title,field.text())
        if path:field.setText(path)
    def browse_source(self):
        if self.mode.currentIndex()==0:path,_=QFileDialog.getOpenFileName(self,'Choose the source OGMD ISO',self.source.text(),'PS3 ISO (*.iso)')
        else:path=QFileDialog.getExistingDirectory(self,'Choose the source OGMD game folder',self.source.text())
        if path:
            self.source.setText(path);p=Path(path)
            self.output.setText(str(p.with_name(p.stem+' - Full English.iso') if p.is_file() else p.with_name(p.name+' - Full English')))
    def browse_edits(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose exported editor corrections',self.edits.text(),'Editor corrections (patch_edits.json)')
        if path:self.edits.setText(path)
    def use_current_edits(self):
        from edit_bundle import export_bundle
        parent=self.parent()
        if not parent.save():return
        snapshot=self.home/'editor_exports'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')/'patch_edits.json'
        export_bundle(parent.project,snapshot);self.edits.setText(str(snapshot))
        self.status.setText('Attached current English edits, including any test text still saved in the editor. Clear Editor corrections to use only the bundled release.')
    def browse_output(self):
        if self.mode.currentIndex()==0:path,_=QFileDialog.getSaveFileName(self,'Choose a NEW English ISO',self.output.text(),'PS3 ISO (*.iso)')
        else:
            parent=QFileDialog.getExistingDirectory(self,'Choose the parent folder for a NEW English game folder',str(Path(self.output.text()).parent))
            path=str(Path(parent)/'OGMD - Full English') if parent else ''
        if path:self.output.setText(path)
    def describe_release(self):
        try:
            doc=json.loads((Path(self.data.text())/'release.json').read_text(encoding='utf8'))
            self.details.setPlainText(doc['release']+' · BLJS10335 01.00\n\n'+'\n'.join('• '+x for x in doc['features'])+
                f'\n\n{doc["baseline_overrides"]} English asset replacements plus {doc["edited_rows"]} saved edited rows.\n'+
                ('Font / battle text fix only replaces EBOOT in a new game copy. Current scripts, menus, archives and installed data are preserved.' if self.font_only.isChecked() else
                 'The English content and font fixes are built into the output. No spacing YAML is required. Start the output game fresh.')+
                '\nRPCS3 only. The font and backlog fixes were confirmed in game. '+
                ('The reported Azuki battle line was also confirmed in game; both battle layouts and all three rows passed offline checks.'
                 if doc.get('battle_fit_visual_tested') else
                 'The battle fit passed offline checks; a fresh battle visual check is pending.'))
        except (OSError,ValueError,KeyError):self.details.setPlainText('Choose your locally prepared full-English release-data folder. Game resources and translation payloads are not included in the public GUI download. See START_HERE.txt or docs/LOCAL_DATA.md for setup details.')
    def invalidate(self,*args):
        self.manifest=None;self.setup_plan=None;self.output_ready=False;self.write.setEnabled(False);self.configure.setEnabled(False);self.describe_release()
        self.edits.setEnabled(not self.font_only.isChecked())
        if hasattr(self,'use_edits_button'):self.use_edits_button.setEnabled(not self.font_only.isChecked())
        self.write.setText('Create game output' if self.font_only.isChecked() else 'Create English output')
    def busy(self,value):
        for control in self.controls+[self.build,self.open_button,self.restore,self.close_button]:control.setEnabled(not value)
        self.edits.setEnabled(not value and not self.font_only.isChecked())
        if hasattr(self,'use_edits_button'):self.use_edits_button.setEnabled(not value and not self.font_only.isChecked())
        self.write.setEnabled(not value and self.manifest is not None)
        self.configure.setEnabled(not value and self.manifest is not None and self.output_ready)
        self.progress.setVisible(value)
    def job_start(self,work,done):
        self.busy(True);self.job=Job(work);self.job.message.connect(self.status.setText);self.job.done.connect(done)
        self.job.failed.connect(self.failed);self.job.finished.connect(lambda:self.busy(False));self.job.start()
    def failed(self,message):
        self.status.setText('Stopped: '+message);QMessageBox.warning(self,'Operation stopped',message)
    def save_config(self):
        atomic_json(self.config_path,dict(source=self.source.text().strip(),output=self.output.text().strip(),runtime=self.runtime.text().strip(),mode=self.mode.currentIndex()))
    def build_patch(self):
        source=self.source.text().strip();output=self.output.text().strip()
        if not source or not output:self.failed('Choose a vanilla source and new output path.');return
        try:
            if self.mode.currentIndex()==1:source_folder(source)
            elif not Path(source).is_file() or Path(source).suffix.lower()!='.iso':raise ValueError('Choose an existing decrypted OGMD ISO, or change Source type to Game folder for a complete extracted disc.')
        except ValueError as exc:self.failed(str(exc));return
        if Path(output).exists():self.failed('The output already exists. Choose a new name.');return
        if self.setup.isChecked() and not (Path(self.runtime.text())/'rpcs3.exe').is_file():self.failed('Choose the RPCS3 folder, or uncheck setup to build the game output first.');return
        self.invalidate();self.save_config();build=self.home/'builds'/datetime.now().strftime('full_%Y%m%d_%H%M%S_%f')
        data=self.data.text();edits=self.edits.text().strip() or None
        if self.font_only.isChecked():self.job_start(lambda progress:prepare_font_patch(data,source,build,progress),self.built)
        else:self.job_start(lambda progress:prepare_full_patch(data,source,build,progress,edits=edits),self.built)
    def built(self,manifest):
        self.manifest=Path(manifest);doc=json.loads(self.manifest.read_text(encoding='utf8'))
        if doc['archives']:self.details.appendPlainText('\nVerified all five complete English archives:\n'+'\n'.join(f'{a["name"]}: {a["size"]:,} bytes · SHA-256 checked' for a in doc['archives']))
        if doc.get('movie'):self.details.appendPlainText('\nEnglish intro movie verified · original PS3 audio and timing preserved')
        if doc.get('eboot'):self.details.appendPlainText('\nEmbedded font EBOOT verified · proportional spacing and apostrophe fix\n'+doc['eboot']['after']+'\nNo font YAML is required. RPCS3 only.')
        else:self.details.appendPlainText('\nLegacy build: font spacing uses YAML. Use Font / battle text fix only on its game output to upgrade to embedded EBOOT.')
        self.status.setText('Patch verified. Create the new game output when ready. Your source is preserved.')
        if doc.get('editor_corrections_review'):
            changes=[r for r in doc['editor_corrections_review'] if r['before']!=r['after']]
            self.details.appendPlainText(f'\n{len(changes)} editor text / artwork corrections applied:\n'+'\n\n'.join(r['id']+'\n'+r['before']+'\n→ '+r['after'] for r in changes))
    def open_build(self):
        path,_=QFileDialog.getOpenFileName(self,'Open a verified full-English build',str(self.home/'builds'),'Full patch build (iso_patch.json full_patch.json)')
        if not path:return
        def work(progress):
            from archive_patch import digest
            manifest=Path(path);doc=json.loads(manifest.read_text(encoding='utf8'))
            if doc.get('profile') not in ('full-english','font-only') or doc.get('status')!='ready':raise ValueError('Choose a verified game build.')
            if doc.get('version') not in (1,2):raise ValueError('Unsupported game build format.')
            from movie_patch import validate_movie
            validate_movie(manifest.parent,doc)
            if doc['profile']=='full-english' and (len(doc['archives'])!=5 or {a['name'] for a in doc['archives']}!={'Logic','Common','Battle','General2d','General3d'}):raise ValueError('Incomplete English build.')
            if doc.get('font_mode')=='embedded-eboot':
                from native_eboot import validate_prepared
                validate_prepared(manifest.parent,doc['eboot'])
            elif doc['profile']=='font-only':raise ValueError('The font-only build is missing its EBOOT.')
            for a in doc['archives']:
                if a['file']!='native/'+a['name']+'.psarc.sdat':raise ValueError('Invalid build filename.')
                progress('Checking prepared '+a['name']+'…')
                if digest(manifest.parent/a['file'])!=a['after']:raise ValueError('Prepared archive changed: '+a['name'])
            return manifest,doc
        def done(result):
            manifest,doc=result
            self.font_only.setChecked(doc['profile']=='font-only')
            self.mode.setCurrentIndex(0 if doc['kind']=='ogmd-iso' else 1);self.source.setText(doc['source'])
            if doc.get('output'):self.output.setText(doc['output'])
            self.built(manifest);self.output_ready=bool(doc.get('output') and Path(doc['output']).exists())
            if self.output_ready:self.status.setText('Verified build reopened. The game output is present; RPCS3 setup is available.')
        self.job_start(work,done)
    def write_game(self):
        self.save_config();manifest=self.manifest;output=self.output.text().strip();runtime=self.runtime.text().strip();setup=self.setup.isChecked()
        def work(progress):
            result=write_full_game(manifest,output,progress)
            if setup:
                try:
                    installed=setup_runtime(runtime,manifest,manifest.parent/'runtime',progress)
                    result.update(setup_plan=installed['setup_plan'],patch_path=installed['patch_path'],rpcs3_setup='installed')
                except Exception as exc:result['rpcs3_setup']='pending';result['setup_error']=str(exc)
            return result
        self.job_start(work,self.written)
    def written(self,result):
        self.output_ready=True
        self.setup_plan=Path(result['setup_plan']) if result.get('setup_plan') else None
        self.status.setText('English game output created and verified: '+result['output']+
            (' · RPCS3 setup installed. Start the game fresh.' if result.get('rpcs3_setup')=='installed' else ' · RPCS3 setup remains available below.'))
        if result.get('setup_error'):self.details.appendPlainText('\nThe English output is safe. Finish RPCS3 setup: '+result['setup_error'])
        if result.get('patch_path'):self.details.appendPlainText('\nInstalled and enabled: '+result['patch_path']+'\nBackup: '+result['setup_plan'])
    def configure_runtime(self):
        if not self.manifest or not self.output_ready:return
        self.save_config()
        runtime=self.runtime.text().strip();manifest=self.manifest
        def done(result):
            self.setup_plan=Path(result['setup_plan'])
            self.status.setText(('Installed and enabled: '+result['patch_path'] if result['patch_path'] else 'RPCS3 compatibility configured; no font YAML installed.')+' · Start the game fresh.')
            self.details.appendPlainText('\nRPCS3 setup verified. Backup: '+result['setup_plan'])
        self.job_start(lambda progress:setup_runtime(runtime,manifest,manifest.parent/'runtime',progress),done)
    def restore_runtime(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose a setup.json backup',str(self.home/'builds'),'Setup manifest (setup.json)')
        if path:self.job_start(lambda progress:restore_setup(path,progress),lambda result:self.status.setText('Previous RPCS3 configuration and installed data restored.'))
    def reject(self):
        if self.job and self.job.isRunning():return
        super().reject()
    def closeEvent(self,event):
        if self.job and self.job.isRunning():event.ignore()
        else:event.accept()
