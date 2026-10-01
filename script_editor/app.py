"""OGMD native desktop script editor."""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer, QLockFile, QEvent, QLocale
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QImage, QFont, QFontDatabase, QKeySequence, QShortcut, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QSplitter,QTreeWidget,QTreeWidgetItem,QLineEdit,QPlainTextEdit,QTableView,QHeaderView,QComboBox,
    QCheckBox,QSpinBox,QGroupBox,QMessageBox,QFileDialog,QAbstractItemView,QFrame,QScrollArea,QStackedWidget,QDialog,QInputDialog)
from core import Corpus, EditProject, NativeMetrics, atomic_json, sha
from battle_speakers import BattleSpeakers, speaker_id
from text_layout import battle_display, wrap_battle
from native_eboot import BATTLE_CAPTION_LIMITS
from dialogs import SearchDialog,PatchDialog
from local_resources import find_preview_assets, missing_preview_files

HOME=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
BUNDLED_ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'
ASSETS=BUNDLED_ASSETS


def load_ui_fonts():
    # Explicit registration also supports Qt's offscreen QA platform, which
    # does not enumerate installed Windows fonts automatically.
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for name in ['segoeui.ttf','segoeuib.ttf','YuGothM.ttc','YuGothB.ttc']:
        path=fonts/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))

STYLE='''
QWidget { background: #101820; color: #dce7ed; font-family: "Segoe UI"; font-size: 10pt; }
QMainWindow { background: #101820; }
QLabel#brand { font-size: 19pt; font-weight: 650; color: #f2fafc; }
QLabel#subtle { color: #91a7b5; font-size: 9pt; }
QLabel#title { font-size: 13pt; font-weight: 600; }
QLabel#status { color: #83dcbf; padding: 4px; }
QPushButton { background: #22313e; border: 1px solid #364955; border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #304858; border-color: #65b8c9; }
QPushButton:pressed { background: #142c36; }
QPushButton:disabled { color: #6c7e88; }
QPushButton#primary { color: #071c22; background: #68d5c3; font-weight: 600; border-color: #68d5c3; }
QPushButton#primary:disabled { color: #71868b; background: #23383b; border-color: #364955; }
QLineEdit,QPlainTextEdit,QTreeWidget,QTableView { background: #15212b; border: 1px solid #304451; border-radius: 4px; selection-background-color: #285e70; selection-color: white; }
QLineEdit { padding: 7px; }
QPlainTextEdit { padding: 8px; font-family: "Yu Gothic UI", "Segoe UI"; font-size: 11pt; }
QTreeWidget { padding: 4px; font-size: 9pt; }
QTreeWidget::item { padding: 5px 1px; }
QTreeWidget::item:selected { background: #244d5a; border-radius: 3px; }
QTableView { gridline-color: #263844; }
QTableView::item { padding: 5px; }
QHeaderView::section { background: #1c2c38; color: #9fb5c4; padding: 6px; border: 0; border-bottom: 1px solid #354b5a; }
QGroupBox { border: 1px solid #304451; border-radius: 6px; margin-top: 10px; padding-top: 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #9ed5de; }
QComboBox,QSpinBox { background: #20313d; padding: 4px; border: 1px solid #3b5361; border-radius: 3px; }
QComboBox QAbstractItemView { background: #20313d; selection-background-color: #315e71; }
QCheckBox { spacing: 6px; }
QSplitter::handle { background: #263946; }
QScrollBar:vertical { background: #14202a; width: 12px; }
QScrollBar::handle:vertical { background: #385463; min-height: 30px; border-radius: 5px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #213744; color: white; border: 1px solid #5b879b; padding: 5px; }
'''


class Preview(QWidget):
    keywordClicked=Signal(str)
    def __init__(self,metrics,parent=None):
        super().__init__(parent);self.metrics=metrics
        self.atlas=QImage(str(ASSETS/'font_atlas.png'))
        self.teal_atlas=self.atlas.copy();tint=QPainter(self.teal_atlas)
        tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn);tint.fillRect(self.teal_atlas.rect(),QColor('#50e6dd'));tint.end()
        self.link_regions=[];self.transform_info=(1,0,0)
        self.scanlines=QImage(str(ASSETS/'tex_13.png'))
        self.text='';self.speaker='';self.cell=24;self.limit=768;self.compress=True;self.guides=False
        self.setMinimumHeight(190);self.setMaximumHeight(330)
        self.setToolTip('Native PS3 font atlas with the confirmed spacing-v3 apostrophe correction. The frame is reconstructed. Default 24-unit cells / 768-unit width follow the existing offline layout audit, not a captured live font size.')

    def sizeHint(self):return QSize(1000,250)

    def glyph_line(self,painter,text,x,y,cell,color=QColor('white'),compression=1):
        # QImage masks preserve actual game glyph contours rather than using a
        # substitute Windows typeface. Widths are measured before scaling.
        for char in self.metrics.visible(text):
            if char=='\n':continue
            d=self.metrics.descriptor(char)
            if d:
                source=QRectF(d[2]*32,d[3]*32,32,32)
                target=QRectF(x,y,cell*compression,cell)
                painter.drawImage(target,self.teal_atlas if color==QColor('#50e6dd') else self.atlas,source)
            else:
                painter.setPen(QPen(QColor('#ffb66e'),1));painter.drawRect(QRectF(x+2,y+3,cell*compression-4,cell-5))
            x+=self.metrics.advance(char,cell)*compression

    def rich_line(self,painter,parts,x,y,cell,compression=1):
        for char,term in parts:
            width=self.metrics.advance(char,cell)*compression
            self.glyph_line(painter,char,x,y,cell,QColor('#50e6dd') if term else QColor('white'),compression)
            if term:
                painter.setPen(QPen(QColor('#50e6dd'),1));painter.drawLine(QRectF(x,y,width,cell).bottomLeft(),QRectF(x,y,width,cell).bottomRight())
                self.link_regions.append((QRectF(x,y,width,cell+3),term))
            x+=width

    def mousePressEvent(self,event):
        scale,dx,dy=self.transform_info
        point=(event.position()-QPointF(dx,dy))/scale
        for rect,term in self.link_regions:
            if rect.contains(point):self.keywordClicked.emit(term);return
        super().mousePressEvent(event)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        logical_w=self.limit+76;logical_h=228
        scale=min((self.width()-12)/logical_w,(self.height()-10)/logical_h)
        self.transform_info=(scale,(self.width()-logical_w*scale)/2,(self.height()-logical_h*scale)/2);self.link_regions=[]
        p.translate((self.width()-logical_w*scale)/2,(self.height()-logical_h*scale)/2);p.scale(scale,scale)
        # Reconstructed neutral backdrop keeps text contrast assessable.
        p.fillRect(QRectF(0,0,logical_w,logical_h),QColor('#111d28'))
        path=QPainterPath();path.moveTo(12,74);path.lineTo(33,53);path.lineTo(logical_w-33,53)
        path.lineTo(logical_w-12,74);path.lineTo(logical_w-12,200);path.lineTo(logical_w-30,218)
        path.lineTo(30,218);path.lineTo(12,200);path.closeSubpath()
        p.fillPath(path,QColor('#071624'));p.setPen(QPen(QColor('#c2d7e0'),2));p.drawPath(path)
        p.setPen(QPen(QColor('#2c92b8'),2));p.drawLine(34,58,int(logical_w-35),58)
        p.drawLine(31,212,int(logical_w-32),212)
        p.save();p.setClipPath(path);p.setOpacity(.08)
        if not self.scanlines.isNull():
            for y in range(68,218,32):p.drawImage(QRectF(18,y,logical_w-36,32),self.scanlines)
        p.restore()
        tag=QPainterPath();tag.moveTo(35,31);tag.lineTo(min(395,logical_w-50),31)
        tag.lineTo(min(418,logical_w-27),52);tag.lineTo(35,52);tag.closeSubpath()
        p.fillPath(tag,QColor('#144458'));p.setPen(QPen(QColor('#74cde5'),1));p.drawPath(tag)
        name_cell=22;name_width=self.metrics.width(self.speaker,name_cell)
        self.glyph_line(p,self.speaker,46,26,name_cell,compression=min(1,340/max(name_width,1)))
        a=self.metrics.assess(self.text,self.cell,self.limit)
        line_h=self.cell+10;top=87
        if self.guides:
            p.setPen(QPen(QColor('#456c7d'),.8,Qt.PenStyle.DashLine))
            for i in range(3):p.drawRect(QRectF(38,top+i*line_h,self.limit,self.cell))
        p.save();p.setClipRect(QRectF(38,top,self.limit,3*line_h))
        from glossary import rich_lines
        for i,line in enumerate(rich_lines(self.text)[:3]):
            shrink=min(1,self.limit/max(a['widths'][i],1)) if self.compress else 1
            # Original color markup is retained in the editor; this preview
            # concentrates on glyph shape/width. Keyword marker brackets hide.
            self.rich_line(p,line,38,top+i*line_h,self.cell,compression=shrink)
        p.restore()
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#bceeff'))
        triangle=QPainterPath();triangle.moveTo(logical_w-43,201);triangle.lineTo(logical_w-29,201);triangle.lineTo(logical_w-36,208);triangle.closeSubpath();p.drawPath(triangle)
        if a['too_many_lines']:
            p.setPen(QColor('#ffac8f'));p.setFont(QFont('Segoe UI',10));p.drawText(QRectF(40,logical_h-18,self.limit-30,18),Qt.AlignmentFlag.AlignLeft,f"{len(a['lines'])-3} additional line(s) outside the dialogue box")


class DataPreview(Preview):
    def __init__(self,metrics,parent=None):
        super().__init__(metrics,parent);self.setMaximumHeight(16777215);self.heading='';self.caption=''

    def set_content(self,heading,text,caption):
        self.heading=heading;self.text=text;self.caption=caption
        self.setMinimumHeight(max(210,95+len(self.metrics.visible(text).split('\n'))*32));self.update()

    def paintEvent(self,event):
        from glossary import rich_lines
        p=QPainter(self);p.fillRect(self.rect(),QColor('#102f49'));p.setPen(QPen(QColor('#4acccf'),2));p.drawRect(self.rect().adjusted(2,2,-3,-3))
        p.setPen(QColor('#9ce5e2'));p.setFont(QFont('Segoe UI',10));p.drawText(18,23,self.caption)
        self.glyph_line(p,self.heading,18,35,24,compression=min(1,(self.width()-36)/max(1,self.metrics.width(self.heading))))
        self.link_regions=[];self.transform_info=(1,0,0)
        for i,line in enumerate(rich_lines(self.text)):
            width=sum(self.metrics.advance(c) for c,t in line)
            self.rich_line(p,line,18,78+i*32,24,min(1,(self.width()-36)/max(1,width)))


class RowsModel(QAbstractTableModel):
    HEADERS=('Line / field','Speaker / entry','English text')
    def __init__(self,window):super().__init__();self.window=window;self.rows=[]
    def rowCount(self,parent=QModelIndex()):return len(self.rows) if not parent.isValid() else 0
    def columnCount(self,parent=QModelIndex()):return 3
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal:return self.HEADERS[section]
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        row=self.rows[index.row()];w=self.window;v=w.project.values(w.key,row)
        if role==Qt.ItemDataRole.DisplayRole:
            if index.column()==0:return ('● ' if w.project.changed(w.key,row) else '')+(row.get('block','') if row.get('fixed_table') or row.get('location_field') else str(index.row()+1))
            if index.column()==1:
                if w.battle.is_battle(w.key):return w.battle.label(speaker_id(row))
                return v.get('speaker_en') or v.get('speaker_jp') or w.entry_label(row,'en') or '—'
            return (v.get('en') or ('[Empty banner]' if row.get('location_field') else '[No official English text]')).replace('\n',' ↵ ')
        if role==Qt.ItemDataRole.ToolTipRole:
            attribution=w.battle.details(speaker_id(row))+'\n\n' if w.battle.is_battle(w.key) else ''
            return attribution+row.get('block','')+'\n'+row['id']+'\n'+(v.get('jp') or '')
        if role==Qt.ItemDataRole.ForegroundRole and w.project.changed(w.key,row):return QColor('#79d8bd')
    def reset_rows(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()


class RowFilter(QSortFilterProxyModel):
    def __init__(self,window):super().__init__();self.window=window;self.query='';self.only_edited=False;self.speaker_filter='all';self.setDynamicSortFilter(False)
    def filterAcceptsRow(self,i,parent):
        w=self.window;row=w.model.rows[i];v=w.project.values(w.key,row)
        if self.only_edited and not w.project.changed(w.key,row):return False
        haystack='\n'.join(str(v.get(k) or '') for k in ['id','block','speaker_en','speaker_jp','en','jp','label_en','label_jp'])+'\n'+w.entry_label(row,'en')+'\n'+w.entry_label(row,'jp')
        if w.battle.is_battle(w.key):
            sid=speaker_id(row)
            if self.speaker_filter!='all' and sid!=self.speaker_filter:return False
            haystack+='\n'+w.battle.search_text(sid)
        return all(word in haystack.casefold() for word in self.query.split())


class Editor(QMainWindow):
    def __init__(self,corpus,project_path=None):
        super().__init__();self.corpus=corpus;self.project=EditProject(corpus,project_path or HOME/'edits'/'project.json')
        self.assets=ASSETS
        self.battle=BattleSpeakers(self.project,BUNDLED_ASSETS/'battle_speakers.json')
        self.weapon_units={r['fixed_logical']:r for r in corpus.load('06_Game_data/Mech_names')[0]['rows']}
        self.metrics=NativeMetrics(ASSETS/'font.bin');self.key=None;self.row_index=None;self.loading=False
        self.setLocale(QLocale.c())
        self.setWindowTitle('OGMD Script Editor v3.16');self.resize(1530,960);self.setMinimumSize(1100,760)
        self.speaker_refresh=QTimer(self);self.speaker_refresh.setSingleShot(True);self.speaker_refresh.setInterval(250);self.speaker_refresh.timeout.connect(self.refresh_battle_library)
        self.autosave=QTimer(self);self.autosave.setSingleShot(True);self.autosave.setInterval(1500);self.autosave.timeout.connect(self.save)
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root);layout.setContentsMargins(18,14,18,10);layout.setSpacing(12)
        bar=QHBoxLayout();brand=QLabel('OGMD  /  SCRIPT EDITOR');brand.setObjectName('brand');bar.addWidget(brand);bar.addStretch()
        self.global_search_button=QPushButton('Find / replace all');self.global_search_button.clicked.connect(self.global_search);bar.addWidget(self.global_search_button)
        self.patch_button=QPushButton('Patch edits');self.patch_button.clicked.connect(self.patch_game);bar.addWidget(self.patch_button)
        self.full_patch_button=QPushButton('Full English patcher');self.full_patch_button.clicked.connect(self.full_patch_game);bar.addWidget(self.full_patch_button)
        self.save_button=QPushButton('Save  ·  Ctrl+S');self.save_button.clicked.connect(self.save);bar.addWidget(self.save_button)
        self.import_button=QPushButton('Import scripts');self.import_button.clicked.connect(self.import_scripts);bar.addWidget(self.import_button)
        export=QPushButton('Export edits');export.setObjectName('primary');export.clicked.connect(self.export_edits);bar.addWidget(export)
        help_button=QPushButton('Help');help_button.clicked.connect(self.help);bar.addWidget(help_button);layout.addLayout(bar)
        self.summary=QLabel('Japanese source + official English  •  Native font preview  •  Edits saved separately');self.summary.setObjectName('subtle');layout.addWidget(self.summary)
        split=QSplitter(Qt.Orientation.Horizontal);layout.addWidget(split,1)
        library=QWidget();lv=QVBoxLayout(library);lv.setContentsMargins(0,0,4,0)
        self.title_cards_button=QPushButton('Stage title cards…');self.title_cards_button.clicked.connect(self.edit_title_cards);lv.addWidget(self.title_cards_button)
        lv.addWidget(QLabel('SCRIPT LIBRARY'));self.library_search=QLineEdit();self.library_search.setPlaceholderText('Find a stage, pilot or script ID…');self.library_search.textChanged.connect(self.filter_library);lv.addWidget(self.library_search)
        self.tree=QTreeWidget();self.tree.setHeaderHidden(True);self.tree.setMinimumWidth(235);lv.addWidget(self.tree,1)
        self.library_info=QLabel(f'{len(corpus.collections)} text collections');self.library_info.setObjectName('subtle');lv.addWidget(self.library_info);split.addWidget(library)
        workspace=QWidget();wv=QVBoxLayout(workspace);wv.setContentsMargins(7,0,0,0);wv.setSpacing(7)
        self.title=QLabel();self.title.setObjectName('title');self.title.setWordWrap(True);wv.addWidget(self.title)
        self.context=QLabel();self.context.setObjectName('subtle');self.context.setWordWrap(True);wv.addWidget(self.context)
        preview_box=QGroupBox('Game text preview');pv=QVBoxLayout(preview_box);pv.setSpacing(2)
        controls=QHBoxLayout();self.preview_language=QComboBox();self.preview_language.addItems(['English','Japanese']);controls.addWidget(self.preview_language)
        self.compression=QCheckBox('Simulate compression');self.compression.setChecked(True);controls.addWidget(self.compression)
        self.guides=QCheckBox('Show guides');controls.addWidget(self.guides);controls.addStretch()
        controls.addWidget(QLabel('Cell'));self.cell=QSpinBox();self.cell.setRange(16,40);self.cell.setValue(24);controls.addWidget(self.cell)
        controls.addWidget(QLabel('Width'));self.width_limit=QSpinBox();self.width_limit.setRange(320,1200);self.width_limit.setSingleStep(24);self.width_limit.setValue(768);controls.addWidget(self.width_limit)
        pv.addLayout(controls);self.preview=Preview(self.metrics);self.preview_stack=QStackedWidget();self.preview_stack.addWidget(self.preview)
        self.data_preview=DataPreview(self.metrics);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.data_preview);self.preview_stack.addWidget(scroll);pv.addWidget(self.preview_stack,1)
        self.preview.keywordClicked.connect(self.open_keyword);self.data_preview.keywordClicked.connect(self.open_keyword)
        self.rename_term=QPushButton('Rename term and linked text…');self.rename_term.clicked.connect(self.rename_glossary);pv.addWidget(self.rename_term);self.rename_term.hide()
        self.fit=QLabel();self.fit.setWordWrap(True);pv.addWidget(self.fit)
        note=QLabel('Native PS3 font. Reconstructed frames: story 24 / 768; battle subtitles 28 / 768.');note.setObjectName('subtle');pv.addWidget(note);wv.addWidget(preview_box,2)
        lower=QSplitter(Qt.Orientation.Horizontal)
        rows_panel=QWidget();rv=QVBoxLayout(rows_panel);rv.setContentsMargins(0,2,5,0)
        self.search=QLineEdit();self.search.setPlaceholderText('Search this script: EN, JP, speaker…  Ctrl+F');rv.addWidget(self.search)
        filter_bar=QHBoxLayout();self.only_edited=QCheckBox('Edited rows only');filter_bar.addWidget(self.only_edited);filter_bar.addStretch();self.row_count=QLabel();self.row_count.setObjectName('subtle');filter_bar.addWidget(self.row_count);rv.addLayout(filter_bar)
        self.battle_filter_bar=QWidget();battle_filters=QHBoxLayout(self.battle_filter_bar);battle_filters.setContentsMargins(0,0,0,0)
        battle_filters.addWidget(QLabel('Battle speaker'));self.battle_filter=QComboBox();self.battle_filter.setAccessibleName('Battle speaker filter')
        self.battle_filter.setMinimumContentsLength(12);self.battle_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        battle_filters.addWidget(self.battle_filter,1);rv.addWidget(self.battle_filter_bar);self.battle_filter_bar.hide()
        self.model=RowsModel(self);self.proxy=RowFilter(self);self.proxy.setSourceModel(self.model)
        self.table=QTableView();self.table.setModel(self.proxy);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setShowGrid(False);self.table.setWordWrap(False);self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Interactive);self.table.setColumnWidth(1,210);self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        rv.addWidget(self.table,1);lower.addWidget(rows_panel)
        edit_panel=QWidget();ev=QVBoxLayout(edit_panel);ev.setContentsMargins(5,2,0,0)
        self.row_label=QLabel('Choose a line');self.row_label.setWordWrap(True);self.row_label.setObjectName('subtle');ev.addWidget(self.row_label)
        self.editors={};self.speakers={}
        for lang,label in [('jp','Japanese'),('en','English')]:
            group=QGroupBox(label);gl=QVBoxLayout(group);gl.setContentsMargins(10,16,10,8)
            speaker=QLineEdit();speaker.setPlaceholderText('Speaker name');speaker.setAccessibleName(label+' speaker');self.speakers[lang]=speaker;gl.addWidget(speaker)
            editor=QPlainTextEdit();editor.setAccessibleName(label+' text');editor.setTabChangesFocus(True);editor.setPlaceholderText('Type '+label+' text here…');editor.setMinimumHeight(74);self.editors[lang]=editor;gl.addWidget(editor,1)
            editor.installEventFilter(self);editor.textChanged.connect(lambda lang=lang:self.changed(lang,False));speaker.textChanged.connect(lambda value,lang=lang:self.changed(lang,True));ev.addWidget(group,1)
        actions=QHBoxLayout();prev=QPushButton('← Previous');prev.clicked.connect(lambda:self.navigate(-1));actions.addWidget(prev)
        nxt=QPushButton('Next →');nxt.clicked.connect(lambda:self.navigate(1));actions.addWidget(nxt);actions.addStretch()
        wrap=QPushButton('Wrap preview language');wrap.clicked.connect(self.wrap);actions.addWidget(wrap)
        restore=QPushButton('Restore source');restore.clicked.connect(self.restore);actions.addWidget(restore);ev.addLayout(actions)
        lower.addWidget(edit_panel);lower.setSizes([400,600]);wv.addWidget(lower,4);split.addWidget(workspace);split.setSizes([285,1220])
        self.status=QLabel('Ready');self.status.setObjectName('status');layout.addWidget(self.status)
        for widget,signal in [(self.preview_language,self.preview_language.currentIndexChanged),(self.cell,self.cell.valueChanged),(self.width_limit,self.width_limit.valueChanged),(self.compression,self.compression.toggled),(self.guides,self.guides.toggled)]:signal.connect(self.refresh_preview)
        self.search.textChanged.connect(self.filter_rows);self.only_edited.toggled.connect(self.filter_rows)
        self.battle_filter.currentIndexChanged.connect(self.filter_rows)
        self.table.selectionModel().currentRowChanged.connect(self.select_row)
        self.tree.currentItemChanged.connect(self.select_collection)
        for key,func in [('Ctrl+S',self.save),('Ctrl+F',lambda:self.search.setFocus()),('Ctrl+Shift+F',self.global_search),('Ctrl+H',self.global_search),('Ctrl+Return',lambda:self.navigate(1))]:QShortcut(QKeySequence(key),self,activated=func)
        self.populate();self.status.setText(f'{self.project.count()} edited rows  ·  Autosave enabled  ·  {self.project.path}')

    def global_search(self):
        SearchDialog(self).exec()

    def import_scripts(self):
        from import_dialog import ImportDialog
        if not self.save():return
        self.autosave.stop();ImportDialog(self).exec()

    def patch_game(self):
        if not self.save():return
        self.autosave.stop();PatchDialog(self,HOME).exec()

    def edit_title_cards(self):
        from title_card_dialog import TitleCardDialog
        if not self.save():return
        self.autosave.stop()
        try:TitleCardDialog(self).exec()
        except Exception as exc:QMessageBox.warning(self,'Title cards unavailable',str(exc))

    def full_patch_game(self):
        from full_dialog import FullPatchDialog
        if not self.save():return
        self.autosave.stop();FullPatchDialog(HOME.parent/'full_patcher',self).exec()

    def open_keyword(self,term):
        from glossary import resolve
        lang='en' if self.preview_language.currentIndex()==0 else 'jp';matches=resolve(self.project,term,lang)
        if len(matches)!=1:
            QMessageBox.information(self,'Glossary link',f'No unique glossary entry matches “{term.strip()}”. Check the marked text and glossary term spelling.');return
        key,row=matches[0];doc,_=self.corpus.load(key)
        values={r['fixed_field']:self.project.values(key,r)[lang] for r in doc['rows'] if r['fixed_record']==row['fixed_record']}
        dialog=QDialog(self);dialog.setWindowTitle('Glossary · '+values['term']);dialog.resize(930,650);layout=QVBoxLayout(dialog)
        area=QScrollArea();area.setWidgetResizable(True);preview=DataPreview(self.metrics)
        body='\n\n'.join(values[k] for k in ('definition_1','definition_2') if values[k].strip().casefold() not in ('','dummy'))
        preview.set_content(values['term'],body,'Glossary · '+('English' if lang=='en' else 'Japanese'));area.setWidget(preview);layout.addWidget(area)
        preview.keywordClicked.connect(self.open_keyword)
        edit=QPushButton('Edit this glossary entry');layout.addWidget(edit)
        def jump():
            dialog.accept();self.open_line(key,row['id']);self.search.setText(str(row['fixed_logical']).zfill(4))
        edit.clicked.connect(jump);dialog.exec()

    def rename_glossary(self):
        from glossary import rename_plan
        if self.row_index is None:return
        row=self.model.rows[self.row_index];lang='en' if self.preview_language.currentIndex()==0 else 'jp'
        old=self.project.values(self.key,row)[lang]
        value,ok=QInputDialog.getText(self,'Rename glossary term','New term (updates matching marked links in this language):',text=old)
        if not ok:return
        try:plan=rename_plan(self.project,self.key,row,lang,value)
        except ValueError as e:QMessageBox.information(self,'Cannot rename term',str(e));return
        if not plan:return
        dialog=QDialog(self);dialog.setWindowTitle('Review glossary rename');dialog.resize(850,580);layout=QVBoxLayout(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText('\n\n'.join(p['id']+'\n'+p['before']+'\n→ '+p['after'] for p in plan));layout.addWidget(text)
        button=QPushButton(f'Apply {len(plan)} text changes');layout.addWidget(button);button.clicked.connect(dialog.accept)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.project.apply_replacements(plan);self.refresh_after_bulk()

    def refresh_after_bulk(self):
        self.autosave.stop();rid=self.model.rows[self.row_index]['id'] if self.row_index is not None else None
        self.refresh_battle_library();self.populate_battle_filter(preserve=True)
        self.model.dataChanged.emit(self.model.index(0,0),self.model.index(max(0,len(self.model.rows)-1),2))
        self.filter_rows()
        if rid:
            row_index=next((i for i,row in enumerate(self.model.rows) if row['id']==rid),None)
            if row_index is not None:
                index=self.proxy.mapFromSource(self.model.index(row_index,0))
                if index.isValid():self.table.setCurrentIndex(index)
        # A bulk edit can keep the same selection, which emits no row-change signal.
        if self.table.currentIndex().isValid():self.select_row(self.table.currentIndex(),QModelIndex())
        self.status.setText(f'Saved  ·  {self.project.count():,} edited rows  ·  {self.project.path}')

    def open_line(self,key,rid):
        self.library_search.clear();self.search.clear();self.only_edited.setChecked(False)
        self.battle_filter.setCurrentIndex(0)
        for i in range(self.tree.topLevelItemCount()):
            parent=self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item=parent.child(j)
                if item.data(0,Qt.ItemDataRole.UserRole)==key:
                    parent.setExpanded(True);self.tree.setCurrentItem(item)
                    index=next(i for i,row in enumerate(self.model.rows) if row['id']==rid)
                    self.table.setCurrentIndex(self.proxy.mapFromSource(self.model.index(index,0)))
                    self.tree.scrollToItem(item);return

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.FocusIn:
            for lang,edit in self.editors.items():
                if obj is edit:self.preview_language.setCurrentIndex(0 if lang=='en' else 1)
        return super().eventFilter(obj,event)

    def populate(self):
        parents={}
        for name in ['Pilot names','Mech names','Spirit Commands','Weapon names','Location banners','Glossary','Stages','Alternate versions','Interludes','Extras','Shared & narration','Map event text','Battle messages','Developer scripts']:
            parent=QTreeWidgetItem([name]);self.tree.addTopLevelItem(parent);parents[name]=parent
            parent.setExpanded(name in ('Pilot names','Mech names','Spirit Commands','Weapon names','Location banners','Glossary','Stages','Alternate versions','Interludes'))
        for c in self.corpus.collections:
            parent=parents.get(c['group'])
            if parent is None:
                parent=QTreeWidgetItem([c['group']]);self.tree.addTopLevelItem(parent);parents[c['group']]=parent
                parent.setExpanded(c['group'] in ('Stages','Alternate versions','Interludes'))
            item=QTreeWidgetItem([c['title']]);item.setData(0,Qt.ItemDataRole.UserRole,c['key']);item.setToolTip(0,c['title']+'\n'+c['meta'].get('title_jp',''));parent.addChild(item)
        self.refresh_battle_library()
        self.tree.setCurrentItem(parents['Stages'].child(0))

    def refresh_battle_library(self):
        for i in range(self.tree.topLevelItemCount()):
            parent=self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item=parent.child(j);key=item.data(0,Qt.ItemDataRole.UserRole)
                if self.battle.is_battle(key):
                    item.setText(0,self.battle.collection_label(key));item.setToolTip(0,self.battle.collection_details(key))
        self.filter_library(self.library_search.text())
        if self.battle.is_battle(self.key):self.title.setText(self.battle.collection_label(self.key))

    def populate_battle_filter(self,preserve=False):
        selected=self.battle_filter.currentData() if preserve else 'all'
        self.battle_filter.blockSignals(True);self.battle_filter.clear();self.battle_filter.addItem('All speakers','all')
        enabled=self.battle.is_battle(self.key);self.battle_filter_bar.setVisible(enabled)
        if enabled:
            for sid,count in self.battle.counts(self.key).most_common():
                self.battle_filter.addItem(f'{self.battle.label(sid)} · ID {sid} · {count} rows',sid)
                self.battle_filter.setItemData(self.battle_filter.count()-1,self.battle.details(sid),Qt.ItemDataRole.ToolTipRole)
        index=self.battle_filter.findData(selected)
        self.battle_filter.setCurrentIndex(max(0,index));self.battle_filter.blockSignals(False)
        self.proxy.speaker_filter=self.battle_filter.currentData()

    def entry_label(self,row,lang):
        main=getattr(self,'fixed_entities',{}).get(row.get('fixed_record')) if row.get('fixed_table') else None
        label=self.project.values(self.key,main)[lang] if main else row.get('label_'+lang,'')
        return label+' · '+self.weapon_owner(row,lang) if row.get('fixed_table')=='WeaponData' else label

    def weapon_owner(self,row,lang):
        unit=self.weapon_units.get(row['weapon_unit']) if row['weapon_unit'] else None
        return self.project.values('06_Game_data/Mech_names',unit)[lang] if unit else row['weapon_owner_'+lang]

    def filter_library(self,query):
        terms=query.casefold().split();matches=0
        for i in range(self.tree.topLevelItemCount()):
            parent=self.tree.topLevelItem(i);visible=0
            for j in range(parent.childCount()):
                item=parent.child(j);text=(item.text(0)+' '+item.toolTip(0)).casefold();hit=all(t in text for t in terms)
                item.setHidden(not hit);visible+=hit
            parent.setHidden(not visible);matches+=visible
            if terms and visible:parent.setExpanded(True)
        self.library_info.setText(f'{matches} / {len(self.corpus.collections)} collections')

    def select_collection(self,item,previous=None):
        if item is None:return
        key=item.data(0,Qt.ItemDataRole.UserRole)
        if not key:return
        was_battle=self.battle.is_battle(self.key)
        self.loading=True;self.key=key;self.row_index=None
        if was_battle!=self.battle.is_battle(key):
            for control,value in ((self.cell,28 if self.battle.is_battle(key) else 24),(self.width_limit,BATTLE_CAPTION_LIMITS['full'] if self.battle.is_battle(key) else 768)):
                control.blockSignals(True);control.setValue(value);control.blockSignals(False)
        try:
            doc,_=self.corpus.load(key);self.document=doc
            self.fixed_entities={r['fixed_record']:r for r in doc['rows'] if r.get('fixed_field') in ('short_name','name','term')}
            self.title.setText(self.battle.collection_label(key) if self.battle.is_battle(key) else self.corpus.by_key[key]['title'])
            meta=doc['metadata'];self.context.setText(meta.get('title_jp','')+'  ·  '+meta.get('description',''))
            if self.battle.is_battle(key):self.context.setText('Speakers are matched per line by character ID. Filter below or search pilot names across banks in the library. Unknown IDs remain unassigned.')
            self.search.blockSignals(True);self.search.clear();self.search.blockSignals(False)
            self.populate_battle_filter()
            self.proxy.query='';self.model.reset_rows(doc['rows']);self.proxy.invalidate()
            self.clear_editors();self.row_count.setText(f'{self.proxy.rowCount()} / {len(doc["rows"])} rows')
        finally:self.loading=False
        if self.proxy.rowCount():self.table.setCurrentIndex(self.proxy.index(0,0))
        else:self.refresh_preview()

    def clear_editors(self):
        for w in [*self.editors.values(),*self.speakers.values()]:w.setEnabled(False);w.clear()
        self.row_label.setText('No rows match this filter')

    def select_row(self,current,previous):
        if self.loading:return
        self.loading=True
        try:
            if not current.isValid():self.row_index=None;self.clear_editors();return
            self.row_index=self.proxy.mapToSource(current).row();row=self.model.rows[self.row_index];v=self.project.values(self.key,row)
            for lang in ['en','jp']:
                self.editors[lang].setEnabled(not row.get('null_text',False));self.editors[lang].setPlainText(v.get(lang) or '')
                battle=self.battle.is_battle(self.key);self.speakers[lang].setReadOnly(battle)
                self.speakers[lang].setEnabled(battle or 'speaker_'+lang in row)
                self.speakers[lang].setText(self.battle.name(speaker_id(row),lang) if battle else v.get('speaker_'+lang) or '')
                self.speakers[lang].setToolTip(self.battle.details(speaker_id(row)) if battle else '')
            self.row_label.setText(f"{row['id']}   ·   {row.get('block','Text')}"+('   ·   EDITED' if self.project.changed(self.key,row) else ''))
            if self.battle.is_battle(self.key):self.row_label.setText(self.row_label.text()+f'   ·   Speaker ID {speaker_id(row)} (read-only)')
        finally:self.loading=False;self.refresh_preview()

    def filter_rows(self,*args):
        if not self.key:return
        self.proxy.query=self.search.text().casefold();self.proxy.only_edited=self.only_edited.isChecked();self.proxy.speaker_filter=self.battle_filter.currentData();self.proxy.invalidate()
        self.row_count.setText(f'{self.proxy.rowCount()} / {len(self.model.rows)} rows')
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0,0));self.select_row(self.table.currentIndex(),QModelIndex())
        else:
            self.loading=True;self.row_index=None;self.clear_editors();self.loading=False;self.refresh_preview()

    def changed(self,lang,speaker):
        if self.loading or self.row_index is None:return
        row=self.model.rows[self.row_index];field='speaker_'+lang if speaker else lang
        if speaker and self.battle.is_battle(self.key):return
        value=self.speakers[lang].text() if speaker else self.editors[lang].toPlainText()
        try:self.project.set(self.key,row,field,value)
        except Exception as e:self.status.setText('Cannot save this edit: '+str(e));return
        self.model.dataChanged.emit(self.model.index(self.row_index,0),self.model.index(self.row_index,2))
        self.row_label.setText(f"{row['id']}   ·   {row.get('block','Text')}"+('   ·   EDITED' if self.project.changed(self.key,row) else ''))
        if self.battle.is_battle(self.key):self.row_label.setText(self.row_label.text()+f'   ·   Speaker ID {speaker_id(row)} (read-only)')
        self.status.setText(f'Unsaved changes  ·  {self.project.count()} edited rows');self.autosave.start();self.refresh_preview()
        if row.get('fixed_table')=='PilotData' and row.get('fixed_field')=='short_name':self.speaker_refresh.start()

    def refresh_preview(self,*args):
        if not hasattr(self,'editors'):return
        lang='en' if self.preview_language.currentIndex()==0 else 'jp';text=self.editors[lang].toPlainText()
        if self.battle.is_battle(self.key):text=battle_display(text)
        self.preview.text=text;self.preview.speaker=self.speakers[lang].text();self.preview.cell=self.cell.value();self.preview.limit=self.width_limit.value();self.preview.compress=self.compression.isChecked();self.preview.guides=self.guides.isChecked();self.preview.update()
        row=self.model.rows[self.row_index] if self.row_index is not None else {}
        fixed=row.get('fixed_table');location=bool(row.get('location_field'));self.preview_stack.setCurrentIndex(1 if fixed or location else 0)
        self.rename_term.setVisible(fixed=='KeyWordData' and row.get('fixed_field')=='term')
        for speaker in self.speakers.values():speaker.setVisible(not fixed and not location)
        if location:
            self.data_preview.set_content(text,'',self.entry_label(row,lang)+' · '+row['block'])
            self.fit.setStyleSheet('color: #9ed5de;');self.fit.setText('Location / scene banner · one line. Find / replace all includes every occurrence in every stage.')
            return
        if fixed:
            related={r['fixed_field']:self.project.values(self.key,r)[lang] for r in self.model.rows if r['fixed_record']==row['fixed_record']}
            if fixed=='PilotData':
                heading=related['short_name'];body='・'.join(t for t in [related['given_name'],related['family_name']] if t);caption='Pilot menu · short name / full name'
            elif fixed=='UnitData':heading=related['name'];body=related['name'];caption='Mech menu · unit name'
            elif fixed=='SpiritData':heading=related['name'];body=related['description'];caption='Spirit Commands · name / description'
            elif fixed=='WeaponData':heading=related['name'];body=self.weapon_owner(row,lang);caption=f'Weapon name · unit {row["weapon_unit"]} · slot {row["weapon_slot"]}'
            else:
                heading=related['term'];body='\n\n'.join(related[k] for k in ('definition_1','definition_2') if related[k].strip().casefold() not in ('','dummy'));caption='Glossary · scroll to read · click teal links'
            self.data_preview.set_content(heading,body,caption)
            self.fit.setStyleSheet('color: #9ed5de;');self.fit.setText('Native font reference; menu and glossary frames are reconstructed. Use Rename term and linked text to keep glossary links consistent.' if fixed=='KeyWordData' else 'Native font reference. Changing menu names does not automatically rename dialogue; Find / replace all covers both.')
            return
        a=self.metrics.assess(text,self.cell.value(),self.width_limit.value());widths=' / '.join(f'{x:g}' for x in a['widths'][:5])
        warnings=[]
        if a['too_many_lines']:warnings.append(f"{a['line_count']} lines — only 3 fit")
        if a['overflow']:warnings.append('wide lines will compress' if self.compression.isChecked() else 'text exceeds the box')
        if a['missing']:warnings.append('unsupported glyphs: '+''.join(a['missing']))
        if self.key and self.corpus.by_key[self.key]['group'] in ('Map event text','Shared & narration'):
            warnings.append('dialogue reference layout; this script can use another in-game screen')
        if self.battle.is_battle(self.key):warnings.append('battle / markers display as line breaks; embedded battle fix fits wide lines')
        self.fit.setStyleSheet('color: '+('#ffc08c' if warnings else '#84dfbf')+';')
        self.fit.setText(('  ·  '.join(warnings) if warnings else 'Fits the reference dialogue box')+f"  |  Width: {widths} / {self.width_limit.value()}  |  {a['line_count']}/3 lines")

    def navigate(self,delta):
        n=self.proxy.rowCount()
        if n:self.table.setCurrentIndex(self.proxy.index(max(0,min(n-1,self.table.currentIndex().row()+delta)),0))

    def wrap(self):
        if self.row_index is None:return
        row=self.model.rows[self.row_index]
        if row.get('location_field') or row.get('fixed_field') in ('short_name','given_name','family_name','name','term'):
            QMessageBox.information(self,'Single-line field','Names and location banners use one line. Shorten the text if needed.');return
        lang='en' if self.preview_language.currentIndex()==0 else 'jp';editor=self.editors[lang]
        try:
            text=(wrap_battle(self.metrics,editor.toPlainText(),self.cell.value(),self.width_limit.value())
                  if self.battle.is_battle(self.key) else self.metrics.wrap(editor.toPlainText(),self.cell.value(),self.width_limit.value()))
        except ValueError as e:QMessageBox.information(self,'Manual line breaks needed',str(e));return
        cursor=editor.textCursor();cursor.beginEditBlock();cursor.select(cursor.SelectionType.Document);cursor.insertText(text);cursor.endEditBlock()

    def restore(self):
        if self.row_index is None:return
        lang='en' if self.preview_language.currentIndex()==0 else 'jp';row=self.model.rows[self.row_index];editor=self.editors[lang]
        cursor=editor.textCursor();cursor.beginEditBlock();cursor.select(cursor.SelectionType.Document);cursor.insertText(row.get(lang) or '');cursor.endEditBlock()
        if 'speaker_'+lang in row:self.speakers[lang].setText(row.get('speaker_'+lang) or '')

    def save(self):
        try:self.project.save();self.status.setText(f'Saved  ·  {self.project.count()} edited rows  ·  {self.project.path}');return True
        except Exception as e:self.status.setText('SAVE FAILED: '+str(e));QMessageBox.critical(self,'Edits were not saved',str(e));return False

    def export_edits(self):
        from title_cards import project_cards
        if not self.project.count() and not project_cards(self.project).count():QMessageBox.information(self,'No edits yet','Edit a line or save a title-card edit first.');return
        if not self.save():return
        destination=HOME/'exports'/datetime.now().strftime('edited_scripts_%Y%m%d_%H%M%S_%f')
        try:
            count=self.project.export(destination)
            self.status.setText(f'Exported {count} edited collections to {destination}')
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))
        except Exception as e:QMessageBox.critical(self,'Export failed',str(e))

    def help(self):
        QMessageBox.information(self,'Using the OGMD Script Editor',
            '1. Choose a stage or collection on the left. Search works in English and Japanese.\n'
            '2. Select a line. Edit either language or the speaker name; the preview updates immediately.\n'
            '3. Use Wrap to reflow the preview language using native character widths. Ctrl+Z undoes edits in the current text field.\n'
            '4. Autosave stores edits in edits/project.json with timestamped backups. Ctrl+S saves immediately.\n'
            '5. Find / replace all (Ctrl+H) searches every collection and previews replacements; bulk changes can be undone.\n'
            '6. Export edits creates JSON and EN/JP/paired text for changed collections.\n'
            '7. Import scripts reads JSON, EN.txt, JP.txt or Bilingual.txt files/folders by stable row IDs. Preview, choose how to handle conflicts, then import. Undo last import reverses it.\n'
            '8. Patch game builds verified native PS3 archives from edited fields. Choose Game folders to install with backups (close RPCS3 first), or ISO image to create a verified patched copy of a decrypted ISO. Unedited text stays as in the selected game/ISO.\n\n'
            'BATTLE SPEAKERS\nBattle messages show English/Japanese names matched from each record, including guest speakers in another pilot’s bank. Use Battle speaker to filter the current bank. The library search finds every bank containing a pilot. Names follow Pilot names edits and are read-only on battle lines. Missing names show an Unknown ID; English-only fallback names are identified. Find / replace all still changes only editable text.\n\n'
            'PREVIEW ACCURACY\nNative PS3 glyph atlas and the confirmed spacing-v3 apostrophe correction. The border is reconstructed. '
            'Default 24-unit cells and 768-unit width follow the existing offline audit; they are not a confirmed live-game capture. '
            'Portraits, animation, scene backgrounds and text color effects are omitted. Narration, map menus and battle subtitles can use different layouts. '
            'Keyword brackets and color controls are retained in the saved text; marker brackets are hidden when measuring.\n\n'
            'Original files: '+str(self.corpus.root)+'\nEdits: '+str(self.project.path))

    def closeEvent(self,event):
        self.autosave.stop()
        if self.project.dirty and not self.save():event.ignore();return
        event.accept()


def main():
    global ASSETS
    parser=argparse.ArgumentParser();parser.add_argument('--corpus',type=Path);parser.add_argument('--project',type=Path);parser.add_argument('--self-check',type=Path)
    parser.add_argument('--assets',type=Path,help='Folder containing locally supplied font.bin, font_atlas.png, and tex_13.png.')
    parser.add_argument('--startup-check',type=Path,help='Check the public resource-selection GUI without opening game data.')
    parser.add_argument('--check-unit-data',type=Path,help='With --self-check, verify name patching against a supplied UnitData.dat without modifying it.')
    parser.add_argument('--check-pilot-data',type=Path,help='With --self-check, verify name patching against a supplied PilotData.dat without modifying it.')
    parser.add_argument('--check-weapon-data',type=Path,help='With --self-check, verify name patching against a supplied WeaponData.dat without modifying it.')
    args=parser.parse_args()
    if args.check_unit_data and not args.self_check:parser.error('--check-unit-data requires --self-check')
    if args.check_pilot_data and not args.self_check:parser.error('--check-pilot-data requires --self-check')
    if args.check_weapon_data and not args.self_check:parser.error('--check-weapon-data requires --self-check')
    if args.self_check or args.startup_check:os.environ['QT_QPA_PLATFORM']='offscreen'
    app=QApplication(sys.argv[:1]);load_ui_fonts();app.setApplicationName('OGMD Script Editor');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    if args.startup_check:
        if args.assets or args.corpus:
            if not args.assets or not args.corpus:parser.error('--startup-check needs both --assets and --corpus to check the populated editor')
            import tempfile
            ASSETS=find_preview_assets([args.assets])
            if ASSETS is None:raise FileNotFoundError('Preview resources missing')
            with tempfile.TemporaryDirectory() as temporary:
                window=Editor(Corpus(args.corpus),Path(temporary)/'project.json')
                window.show();app.processEvents()
                assert not QImage(str(ASSETS/'font_atlas.png')).isNull()
                assert not QImage(str(ASSETS/'tex_13.png')).isNull()
                window.grab().save(str(args.startup_check.with_suffix('.png')))
                atomic_json(args.startup_check,dict(ok=True,gui_constructed=True,external_preview_loaded=True,collections=len(window.corpus.collections),frozen=bool(getattr(sys,'frozen',False))))
                window.close()
            return 0
        dialog=QFileDialog(None,'Choose your local native preview resources')
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True);dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.show();app.processEvents()
        mapping=json.loads((BUNDLED_ASSETS/'battle_speakers.json').read_text(encoding='utf8'))
        assert mapping['version']==1
        atomic_json(args.startup_check,dict(ok=True,resource_picker_constructed=True,battle_speaker_map_loaded=True,frozen=bool(getattr(sys,'frozen',False))))
        dialog.close();return 0
    config_path=HOME/'settings.json'
    try:config=json.loads(config_path.read_text(encoding='utf8')) if config_path.exists() else {}
    except Exception:config={}
    candidates=[args.assets] if args.assets else [config.get('assets'),HOME/'assets',BUNDLED_ASSETS]
    ASSETS=find_preview_assets(candidates)
    if ASSETS is None:
        if args.self_check:raise FileNotFoundError('Native preview resources not located; supply --assets.')
        QMessageBox.information(None,'Local preview resources required',
            'The public download does not include game fonts or artwork. Choose your local folder containing font.bin, font_atlas.png, and tex_13.png. See START_HERE.txt or docs/LOCAL_DATA.md for setup details.')
        selected=QFileDialog.getExistingDirectory(None,'Choose your local native preview resources')
        if not selected:return 0
        ASSETS=Path(selected)
        missing=missing_preview_files(ASSETS)
        if missing:
            QMessageBox.warning(None,'Preview resources missing','Missing or empty files: '+', '.join(missing));return 1
    roots=[args.corpus,Path(config['corpus']) if config.get('corpus') else None]
    roots += [parent/'script_export/OGMD_EN_JP_20260908' for parent in [HOME,*HOME.parents]]
    root=next((r for r in roots if r and (r/'data/stage_index.json').is_file()),None)
    if not root:
        if args.self_check:raise FileNotFoundError('Source corpus not located')
        selected=QFileDialog.getExistingDirectory(None,'Choose the OGMD_EN_JP script export folder')
        if not selected:return 0
        root=Path(selected)
    if args.self_check:
        import tempfile
        from runtime_check import check_runtime_package
        runtime_check=check_runtime_package(ASSETS/'runtime')
        with tempfile.TemporaryDirectory() as tmp:
            corpus=Corpus(root);window=Editor(corpus,Path(tmp)/'edits.json');window.show();app.processEvents()
            assert not window.preview.atlas.isNull() and window.preview.atlas.width()==1024
            assert window.metrics.raw_width("「...That's fast,Al-Van」")==306.75
            assert window.model.rowCount()==160
            from Crypto.Cipher import AES
            sample=b'0123456789abcdef';key=bytes(16);iv=bytes(16)
            encrypted=AES.new(key,AES.MODE_CBC,iv).encrypt(sample)
            assert AES.new(key,AES.MODE_CBC,iv).decrypt(encrypted)==sample
            search=SearchDialog(window);search.find.setPlainText('E-Selda');search.replacement.setPlainText('Check');search.search()
            assert search.model.rowCount()>0 and search.replace.isEnabled();search.accept()
            from import_dialog import ImportDialog
            from script_import import ScriptImporter
            from iso_image import DiscImage
            from zopfli.zlib import compress as compact_zlib
            import zlib
            assert zlib.decompress(compact_zlib(b'compression check',numiterations=5))==b'compression check'
            from native_formats import _dialogue_pool,read_cstring
            pool,pointers=_dialogue_pool(['日本語 suffix','suffix',''],True)
            assert [read_cstring(bytes(128)+pool,p) for p in pointers]==['日本語 suffix','suffix','']
            assert len(pool)==len('日本語 suffix'.encode('utf8'))+1
            sample=EditProject(corpus,Path(tmp)/'sample.json');sample.set(window.key,window.model.rows[0],'en','Packaged import check');sample.save()
            importer=ImportDialog(window);importer.previewed(ScriptImporter(window.project).preview(sample.path));importer.apply_import()
            assert window.editors['en'].toPlainText()=='Packaged import check'
            importer.undo_import();assert window.project.count()==0;importer.close()
            # Exercise the embedded patcher against the actual sibling release,
            # including the button that exports this editor's current text.
            from full_dialog import FullPatchDialog
            from full_patch import package_info
            from edit_bundle import read_bundle
            full=FullPatchDialog(Path(tmp)/'full_patcher',window)
            full.data.setText(str(HOME.parent/'full_patcher/data'))
            release=package_info(full.data.text())
            assert release['version']==2 and release.get('movie') and release.get('custom_notice')
            assert full.windowTitle()=='OGMD Full English Patcher 1.6.3'
            assert release.get('battle_caption_limits')==BATTLE_CAPTION_LIMITS
            assert release.get('battle_fit_visual_tested') and release.get('diagnostic_recorder') is False
            assert 'The reported Azuki battle line was also confirmed in game' in full.details.toPlainText()
            row=window.model.rows[0];window.project.set(window.key,row,'en','Packaged full patcher check')
            full.use_edits_button.click();groups,_=read_bundle(full.edits.text(),release)
            assert any(item['edits'].get('en')=='Packaged full patcher check' for items in groups.values() for item in items)
            window.project.set(window.key,row,'en',row['en']);window.project.save()
            assert window.project.count()==0
            full.show();app.processEvents();args.self_check.parent.mkdir(parents=True,exist_ok=True)
            full.grab().save(str(args.self_check.with_name(args.self_check.stem+'_full_patcher.png')))
            full.font_only.setChecked(True);assert not full.use_edits_button.isEnabled();full.close()
            patch=PatchDialog(window,Path(tmp));patch.mode.setCurrentIndex(1)
            assert patch.install.text()=='Create patched ISO' and patch.backlog.isChecked()
            from backlog_layout import WIDTH
            assert WIDTH==720
            args.self_check.parent.mkdir(parents=True,exist_ok=True)
            patch.show();app.processEvents();patch.grab().save(str(args.self_check.with_name(args.self_check.stem+'_patch.png')));patch.close()
            iso_candidates=list((corpus.root.parents[1]/'PS3').glob('*.iso'));iso_checked=False
            if iso_candidates:
                with DiscImage(iso_candidates[0]) as disc:iso_checked=len(disc.views)>=1
            from glossary import resolve
            from fixed_data import SCHEMAS
            assert len(corpus.fixed_hashes)==5 and len(SCHEMAS)==5
            unit_data_check=None
            if args.check_unit_data:
                from fixed_data import parse_fixed
                from patcher import compile_entry
                raw=args.check_unit_data.read_bytes();before=parse_fixed(raw)
                row=next(r for r in corpus.load('06_Game_data/Mech_names')[0]['rows'] if r['id']=='UnitData_name:0140')
                result,review=compile_entry(raw,[dict(row=row,edits={'en':'Packaged skill compatibility check'})],'en')
                after=parse_fixed(result)
                assert before.logical_indices==after.logical_indices and len(before.records)==len(after.records)
                for record,(old,new) in enumerate(zip(before.records,after.records)):
                    assert (old[:2]+old[4:]==new[:2]+new[4:]) if record==row['fixed_record'] else old==new
                name=int.from_bytes(after.records[row['fixed_record']][2:4],'big')
                assert after.strings[name]=='Packaged skill compatibility check' and len(review)==1
                unit_data_check=dict(source=str(args.check_unit_data),records=len(after.records),custom_skills_preserved=True)
            weapon_data_check=None
            if args.check_weapon_data:
                from fixed_data import parse_fixed
                from patcher import compile_entry
                raw=args.check_weapon_data.read_bytes();before=parse_fixed(raw)
                row=next(r for r in corpus.load('06_Game_data/Weapon_names')[0]['rows'] if r['id']=='WeaponData_name:0366')
                result,review=compile_entry(raw,[dict(row=row,edits={'en':'Packaged weapon compatibility check'})],'en')
                after=parse_fixed(result)
                assert before.logical_indices==after.logical_indices and len(before.records)==len(after.records)
                for record,(old,new) in enumerate(zip(before.records,after.records)):
                    assert (old[:4]+old[6:]==new[:4]+new[6:]) if record==row['fixed_record'] else old==new
                name=int.from_bytes(after.records[row['fixed_record']][4:6],'big')
                assert after.strings[name]=='Packaged weapon compatibility check' and len(review)==1
                weapon_data_check=dict(source=str(args.check_weapon_data),records=len(after.records),custom_weapon_settings_preserved=True)
            pilot_data_check=None
            if args.check_pilot_data:
                from fixed_data import parse_fixed
                from patcher import compile_entry
                raw=args.check_pilot_data.read_bytes();before=parse_fixed(raw)
                rows=corpus.load('06_Game_data/Pilot_names')[0]['rows']
                selected=[r for r in rows if r['fixed_logical']==10]
                assert {r['fixed_field'] for r in selected}==set(SCHEMAS['PilotData'][1])
                items=[dict(row=r,edits={'en':'Packaged '+r['fixed_field']+' check'}) for r in selected]
                result,review=compile_entry(raw,items,'en');after=parse_fixed(result)
                allowed={(r['fixed_record'],i) for r in selected
                         for o,w in [SCHEMAS['PilotData'][1][r['fixed_field']]] for i in range(o,o+w)}
                assert before.logical_indices==after.logical_indices and len(before.records)==len(after.records)
                assert all(a==b or (record,i) in allowed for record,(old,new) in enumerate(zip(before.records,after.records))
                           for i,(a,b) in enumerate(zip(old,new)))
                for item in items:
                    row=item['row'];o,w=SCHEMAS['PilotData'][1][row['fixed_field']]
                    name=int.from_bytes(after.records[row['fixed_record']][o:o+w],'big')
                    assert after.strings[name]==item['edits']['en']
                assert len(review)==len(items)
                pilot_data_check=dict(source=str(args.check_pilot_data),records=len(after.records),custom_pilot_settings_preserved=True)
            glossary_key,glossary_row=resolve(window.project,'ATX Team','en')[0]
            window.open_line(glossary_key,glossary_row['id']);app.processEvents()
            assert window.data_preview.link_regions and window.rename_term.isVisible()
            battle_key='04_Shared/Battle_messages/0002';battle_rows=corpus.load(battle_key)[0]['rows']
            guest=next(r for r in battle_rows if speaker_id(r)==7)
            window.open_line(battle_key,guest['id']);app.processEvents()
            assert window.preview.speaker=='Azuki' and window.speakers['en'].isReadOnly()
            assert window.battle.counts(battle_key)=={2:153,3:78,5:38,7:16}
            window.battle_filter.setCurrentIndex(window.battle_filter.findData(7));assert window.proxy.rowCount()==16
            window.open_line(battle_key,battle_rows[0]['id']);assert window.proxy.rowCount()==285
            window.preview_language.setCurrentIndex(1);assert window.preview.speaker==window.battle.name(2,'jp')
            window.preview_language.setCurrentIndex(0);assert window.preview.speaker=='Ginto'
            assert window.project.count()==0
            args.self_check.parent.mkdir(parents=True,exist_ok=True)
            app.processEvents()
            window.grab().save(str(args.self_check.with_suffix('.png')))
            slash_key='04_Shared/Battle_messages/0112';window.open_line(slash_key,'0112:2261')
            assert '/' in window.editors['en'].toPlainText() and '/' not in window.preview.text and '\n' in window.preview.text
            app.processEvents();window.grab().save(str(args.self_check.with_suffix('.png')))
            expanded_counts={}
            for key in ('06_Game_data/Spirit_commands','06_Game_data/Weapon_names','07_Location_banners/Locations'):
                rows=corpus.load(key)[0]['rows'];row=next(r for r in rows if r['en']);expanded_counts[key]=len(rows)
                window.open_line(key,row['id']);app.processEvents()
                assert window.preview_stack.currentIndex()==1 and window.data_preview.heading
                assert not window.speakers['en'].isVisible()
            assert list(expanded_counts.values())==[88,856,764]
            assert len([h for h in window.project.find_all('Hagwane','Hagane') if h['key']=='07_Location_banners/Locations'])==117
            assert window.project.count()==0
            from title_card_dialog import TitleCardDialog
            from title_cards import catalog,project_cards
            from title_card_correction import ST084_PNG_SHA256
            assert sha(catalog().source_png('st_084','en'))==ST084_PNG_SHA256
            cards=TitleCardDialog(window);cards.show();app.processEvents()
            assert len(catalog().cards)==115 and not cards.current.image.isNull()
            cards.grab().save(str(args.self_check.with_name(args.self_check.stem+'_title_cards.png')))
            png=catalog().source_png('st_000','jp')
            cards.project.stage('st_000','en',png)
            from patcher import collect_changes,compile_entry
            card_items=collect_changes(window.project,'en')[('Common',catalog().card('st_000')['entry'])]
            card_native=catalog().native('st_000',catalog().source_png('st_000','en'))
            compiled,card_review=compile_entry(card_native,card_items,'en')
            assert compiled==catalog().native('st_000',png) and card_review[0]['title_card']
            cards.project.reset('st_000','en');assert cards.project.count()==0;cards.close()
            atomic_json(args.self_check,dict(status='passed',version='3.16',backlog_fix_default=True,runtime_workflow=runtime_check,collections=len(corpus.collections),
                title_card_sheets=115,title_card_preview_loaded=True,title_card_save_compile_reset_verified=True,
                corrected_st084_png_sha256=ST084_PNG_SHA256,
                unit_data_compatibility=unit_data_check,
                pilot_data_compatibility=pilot_data_check,
                weapon_data_compatibility=weapon_data_check,
                native_font_loaded=True,native_reference_width=306.75,source_rows_loaded=160,
                global_search_loaded=True,native_patch_crypto_loaded=True,
                import_and_undo_passed=True,iso_workflow_loaded=True,local_iso_indexes_verified=iso_checked,lossless_compression_loaded=True,dialogue_pool_compaction_loaded=True,
                confirmed_apostrophe_spacing=True,full_game_patcher_available=True,embedded_patcher_version='1.6.3',
                battle_caption_limits=BATTLE_CAPTION_LIMITS,battle_fit_user_confirmed=True,diagnostic_recorder=False,
                release_format=release['version'],english_intro=bool(release.get('movie')),custom_notice=bool(release.get('custom_notice')),current_editor_edits_verified=True,
                fixed_data_sections=5,location_fields=764,expanded_previews_verified=expanded_counts,glossary_links_rendered=True,portable_edit_bundle_available=True,
                battle_speaker_asset_loaded=True,battle_mixed_bank_filter_verified=True,battle_speakers_bilingual=True,
                battle_slash_preview_verified=True,
                frozen=bool(getattr(sys,'frozen',False)),source_files_modified=False))
            window.close()
        return 0
    lock_path=(args.project or HOME/'edits/project.json').parent;lock_path.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(lock_path/'editor.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(100):QMessageBox.information(None,'Editor already open','An editor is already using this edits workspace. Switch to the existing window.');return 0
    try:
        corpus=Corpus(root);window=Editor(corpus,args.project);atomic_json(config_path,dict(corpus=str(root.resolve()),assets=str(ASSETS.resolve())))
    except Exception as e:QMessageBox.critical(None,'Cannot open the script editor',str(e));return 1
    window.show();result=app.exec();lock.unlock();return result


if __name__=='__main__':sys.exit(main())
