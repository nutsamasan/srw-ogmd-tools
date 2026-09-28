"""Standalone desktop pilot Spirit Command, personality and current Will editor."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
import pilot_patch as core
import will_save as saves
import will_behavior as behavior
from ui_dialogs import ReviewDialog

VERSION = '1.1'
SPIRIT_LABELS = {sid: value['name'] if not sid else f"{value['name']} [{sid}]" for sid, value in core.SPIRITS.items()}
SPIRIT_IDS = {v: k for k, v in SPIRIT_LABELS.items()}
SPIRIT_OPTIONS = [SPIRIT_LABELS[0]] + sorted(SPIRIT_LABELS[sid] for sid in SPIRIT_LABELS if sid)
PROFILE_LABELS = {key: f"{item['name']} (profile {key})" for key, item in core.PERSONALITIES.items()}
PROFILE_IDS = {v: k for k, v in PROFILE_LABELS.items()}


def app_dir():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


class App:
    def __init__(self, root):
        self.root, self.busy = root, False
        self.session = None
        self.save_path, self.save_snapshot = None, None
        self.will_pilots = {}
        self.pending, self.will_pending = {}, {}
        self.selected, self.will_selected = None, None
        self.messages = queue.Queue()
        root.title('OGMD Pilot Editor '+VERSION)
        root.geometry('1180x840')
        root.minsize(1080, 800)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Treeview', rowheight=max(26, tkfont.nametofont('TkDefaultFont').metrics('linespace')+6))
        top = ttk.Frame(root, padding=(16, 12, 16, 8))
        top.grid(row=0, column=0, sticky='ew')
        ttk.Label(top, text='Moon Dwellers · Pilot Editor', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(top, text='Spirit Commands (Seishin), Will response profiles, and saved current Will/Ki.').pack(anchor='w', pady=(4, 0))
        search = ttk.Frame(root, padding=(16, 0, 16, 8))
        search.grid(row=1, column=0, sticky='ew')
        ttk.Label(search, text='Search current tab').pack(side='left', padx=(0, 10))
        self.query = tk.StringVar()
        ttk.Entry(search, textvariable=self.query, width=45).pack(side='left')
        self.query.trace_add('write', lambda *_: self.populate())
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=2, column=0, sticky='nsew', padx=16)
        self.archive_tab = ttk.Frame(self.notebook, padding=12)
        self.will_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.archive_tab, text='Spirit Commands & Will behavior')
        self.notebook.add(self.will_tab, text='Current Will · Save file')
        self.build_archive()
        self.build_will()
        self.status = tk.StringVar(value='Read a game archive or save to begin. Changes are staged until you write them.')
        ttk.Label(root, textvariable=self.status, padding=16, wraplength=1110).grid(row=3, column=0, sticky='ew')
        self.notebook.bind('<<NotebookTabChanged>>', lambda _: self.populate())
        root.after(80, self.poll)

    def layout(self, tab):
        tab.columnconfigure(0, weight=4)
        tab.columnconfigure(1, weight=5)
        tab.rowconfigure(2, weight=1)

    def tree(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.grid(row=2, column=0, sticky='nsew', padx=(0, 16))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=tuple(c[0] for c in columns), show='headings', selectmode='browse')
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, stretch=key == 'name')
        tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def build_archive(self):
        tab = self.archive_tab
        self.layout(tab)
        path = app_dir()/'archive_locations.json'
        known = json.loads(path.read_text(encoding='utf8')) if path.is_file() else []
        known = [p for p in known if Path(p).is_file()]
        self.target_var = tk.StringVar(value=known[0] if known else '')
        row = ttk.Frame(tab)
        row.grid(row=0, column=0, columnspan=2, sticky='ew')
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text='Game archive').grid(row=0, column=0, padx=(0, 8))
        ttk.Combobox(row, textvariable=self.target_var, values=known).grid(row=0, column=1, sticky='ew')
        ttk.Button(row, text='Browse…', command=self.browse_archive).grid(row=0, column=2, padx=8)
        ttk.Button(row, text='Read archive', command=self.read_archive).grid(row=0, column=3)
        ttk.Label(tab, text='Installed Logic.psarc.sdat · settings apply to every use of the selected pilot ID.', wraplength=1020).grid(row=1, column=0, columnspan=2, sticky='w', pady=10)
        self.pilot_tree = self.tree(tab, [('name', 'Pilot', 225), ('id','ID',45), ('state','State',80)])
        self.pilot_tree.bind('<<TreeviewSelect>>', self.select_pilot)
        detail = self.detail = ttk.LabelFrame(tab, text='Select a pilot', padding=12)
        detail.grid(row=2, column=1, sticky='nsew')
        detail.columnconfigure(1, weight=1)
        for col, label in enumerate(('Slot', 'Spirit Command', 'SP cost', 'Level')):
            ttk.Label(detail, text=label).grid(row=0, column=col, sticky='w', padx=(0, 8), pady=(0, 8))
        self.command_vars, self.cost_vars, self.level_vars = [], [], []
        self.cost_boxes, self.level_boxes = [], []
        self.default_labels = []
        for i in range(6):
            r = 1+i*2
            ttk.Label(detail, text='Twin' if i == 5 else str(i+1)).grid(row=r, column=0, sticky='w')
            c, cost, level = tk.StringVar(), tk.StringVar(), tk.StringVar()
            box = ttk.Combobox(detail, textvariable=c, values=SPIRIT_OPTIONS, state='readonly', width=23)
            box.grid(row=r, column=1, sticky='ew', padx=(0, 8))
            box.bind('<<ComboboxSelected>>', lambda _, k=i: self.command_changed(k))
            cost_box = ttk.Spinbox(detail, textvariable=cost, from_=0, to=999, width=5)
            level_box = ttk.Spinbox(detail, textvariable=level, from_=1, to=99, width=5)
            cost_box.grid(row=r, column=2, padx=(0,8)); level_box.grid(row=r, column=3)
            self.cost_boxes.append(cost_box); self.level_boxes.append(level_box)
            label = ttk.Label(detail, text='Original: —', foreground='#626262')
            label.grid(row=r+1, column=1, columnspan=3, sticky='w', pady=(2, 4))
            self.command_vars.append(c); self.cost_vars.append(cost); self.level_vars.append(level)
            self.default_labels.append(label)
        ttk.Label(detail, text='Will behavior').grid(row=13, column=0, sticky='w', padx=(0,8))
        self.profile_var = tk.StringVar()
        ttk.Combobox(detail, textvariable=self.profile_var, values=list(PROFILE_IDS), state='readonly').grid(row=13, column=1, columnspan=3, sticky='ew')
        profile_help = ttk.Frame(detail)
        profile_help.grid(row=14, column=0, columnspan=4, sticky='ew', pady=(7, 10))
        profile_help.columnconfigure(0, weight=1)
        self.profile_description = tk.StringVar(value='Choose a profile to see its Will gains and losses.')
        ttk.Label(profile_help, textvariable=self.profile_description).grid(row=0, column=0, sticky='w')
        ttk.Button(profile_help, text='Compare profiles…', command=self.compare_profiles).grid(row=0, column=1, sticky='e', padx=(8, 0))
        self.profile_var.trace_add('write', self.describe_profile)
        self.description = tk.StringVar(value='Choose a command to see its description.')
        self.description_box = tk.Text(detail, height=3, width=48, wrap='word', font=('Segoe UI',9), relief='flat', state='disabled', background='#f0f0f0')
        self.description_box.grid(row=15, column=0, columnspan=4, sticky='nsew')
        def describe(*_):
            self.description_box.configure(state='normal')
            self.description_box.delete('1.0','end')
            self.description_box.insert('1.0',self.description.get())
            self.description_box.configure(state='disabled')
        self.description.trace_add('write',describe)
        describe()
        detail.rowconfigure(15, weight=1)
        ttk.Button(detail, text='Stage selected pilot', command=self.stage_archive).grid(row=16, column=0, columnspan=4, sticky='ew', pady=(10,0))
        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(12,0))
        for title, fn in [('Selected defaults', self.defaults_selected), ('All original defaults', self.defaults_all), ('Discard', self.discard_archive), ('Restore exact backup…', self.restore_archive), ('Review and write…', self.review_archive)]:
            ttk.Button(actions, text=title, command=fn).pack(side='left', padx=(0,8))

    def build_will(self):
        tab = self.will_tab
        self.layout(tab)
        found = saves.discover_saves()
        self.save_var = tk.StringVar(value=str(found[0].slot_path) if found else '')
        row = ttk.Frame(tab)
        row.grid(row=0, column=0, columnspan=2, sticky='ew')
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text='Save slot').grid(row=0, column=0, padx=(0,8))
        ttk.Combobox(row, textvariable=self.save_var, values=[str(s.slot_path) for s in found]).grid(row=0, column=1, sticky='ew')
        ttk.Button(row, text='Browse…', command=self.browse_save).grid(row=0, column=2, padx=8)
        ttk.Button(row, text='Read save', command=self.read_save).grid(row=0, column=3)
        self.save_info = tk.StringVar(value='Choose a scenario save. Exit the game before writing; RPCS3 can stay open.')
        ttk.Label(tab, textvariable=self.save_info, wraplength=1020).grid(row=1, column=0, columnspan=2, sticky='w', pady=10)
        self.will_tree = self.tree(tab, [('name','Pilot',220),('will','Will',55),('state','State',80)])
        self.will_tree.bind('<<TreeviewSelect>>', self.select_will)
        detail = self.will_detail = ttk.LabelFrame(tab, text='Select a pilot', padding=18)
        detail.grid(row=2, column=1, sticky='nsew')
        self.will_var = tk.StringVar(value='100')
        ttk.Label(detail, text='Current Will / Ki', font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Spinbox(detail, textvariable=self.will_var, from_=50, to=200, width=10, font=('Segoe UI',18)).pack(anchor='w', pady=15)
        ttk.Label(detail, text='50–200. This edits the value stored in this save.\n\nThe game can reset Will at deployment or a new stage and enforce a pilot’s normal cap. This is not a live Will lock.\n\nUse Spirit Commands & Will behavior to choose a permanent gain/loss profile.', wraplength=430, justify='left').pack(anchor='w')
        ttk.Button(detail, text='Stage selected pilot', command=self.stage_will).pack(anchor='w', pady=(20,8))
        ttk.Button(detail, text='Set selected to 100', command=lambda: self.set_will(100)).pack(anchor='w')
        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(12,0))
        for title, fn in [('Discard', self.discard_will), ('Restore Will from backup…', self.restore_will), ('Review and save…', self.review_will)]:
            ttk.Button(actions, text=title, command=fn).pack(side='left', padx=(0,8))

    def error(self, exc):
        messagebox.showerror('Check the selected settings', str(exc), parent=self.root)

    def job(self, function, callback):
        if self.busy:
            return
        self.busy = True
        self.status.set('Working…')
        # Disable all editable controls, keeping the UI repainting and the worker responsive.
        self.states = []
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
                    self.states.append((child, child.cget('state')))
                    child.configure(state='disabled')
                walk(child)
        walk(self.root)
        def run():
            try:
                result = function(lambda msg: self.messages.put(('progress', msg)))
                self.messages.put(('done', (callback, result)))
            except Exception as exc:
                self.messages.put(('error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == 'progress':
                    self.status.set(payload)
                    continue
                self.busy = False
                for widget, state in self.states:
                    widget.configure(state=state)
                if kind == 'error':
                    self.status.set('Operation stopped: '+payload)
                    self.error(payload)
                else:
                    callback, result = payload
                    callback(result)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def browse_archive(self):
        path = filedialog.askopenfilename(title='Select Logic archive', filetypes=[('Logic archive','Logic.psarc.sdat Logic.psarc')])
        if path:
            self.target_var.set(path)

    def read_archive(self):
        if self.busy:
            return
        if not self.stage_archive():
            return
        if self.pending and not messagebox.askyesno('Discard changes?', 'Reading again discards the staged archive edits.', parent=self.root):
            return
        path = self.target_var.get()
        self.job(lambda progress: core.Session(path, progress), self.loaded_archive)

    def loaded_archive(self, session):
        if self.session:
            self.session.close()
        self.session = session
        self.target_var.set(str(session.target))
        self.pending.clear(); self.selected = None
        self.populate()
        children = self.pilot_tree.get_children()
        if children:
            self.pilot_tree.selection_set(children[0]); self.select_pilot()
        self.status.set(f'Read {len(session.pilots)} pilots. Stop the game before writing; boot fresh afterward.')

    def populate(self):
        if self.busy or not hasattr(self, 'will_tree'):
            return
        q = self.query.get().casefold().strip()
        for tree, items, selected, mode in ((self.pilot_tree, self.session.pilots if self.session else {}, self.selected, 'archive'),
                                            (self.will_tree, self.will_pilots, self.will_selected, 'will')):
            position = tree.yview()[0]
            tree.delete(*tree.get_children())
            for pid, p in items.items():
                name = p.name if mode == 'archive' else p.pilot.name
                if q and q not in f'{name} {pid} {pid:02x}'.casefold():
                    continue
                if mode == 'archive':
                    state = 'Staged' if pid in self.pending else 'Custom' if p.settings != p.defaults else 'Original'
                    values = (name, f'{pid:02X}', state)
                else:
                    values = (name, self.will_pending.get(pid, p.will), 'Staged' if pid in self.will_pending else '')
                tree.insert('', 'end', iid=str(pid), values=values)
            if selected is not None and tree.exists(str(selected)):
                tree.selection_set(str(selected))
            tree.yview_moveto(position)

    def collect_archive(self):
        pid = self.selected
        old = self.pending.get(pid, self.session.pilots[pid].settings)
        commands = []
        for i, (c, cost, level) in enumerate(zip(self.command_vars, self.cost_vars, self.level_vars)):
            sid = SPIRIT_IDS[c.get()]
            if sid == old.spirits[i].command and (sid == 0 or (cost.get() == str(old.spirits[i].cost) and level.get() == str(old.spirits[i].level))):
                commands.append(old.spirits[i])
            elif sid == 0:
                commands.append(core.SpiritSlot(0,65535,-1,-1))
            else:
                commands.append(core.SpiritSlot(sid, int(cost.get()), int(level.get()), old.spirits[i].flag if old.spirits[i].command else 0))
        return core.PilotSettings(PROFILE_IDS[self.profile_var.get()], tuple(commands))

    def stage_archive(self):
        if self.busy:
            return False
        if self.selected is None:
            return True
        try:
            value = self.collect_archive()
            p = self.session.pilots[self.selected]
            core.validate_settings(value, p.settings, p.defaults)
            if value == p.settings:
                self.pending.pop(self.selected, None)
            else:
                self.pending[self.selected] = value
            self.populate()
            self.status.set(f'{len(self.pending)} pilot archive edits staged · {len(self.will_pending)} current Will edits staged.')
            return True
        except (ValueError, KeyError) as exc:
            self.error(exc)
            return False

    def select_pilot(self, _event=None):
        if self.busy or not self.session or not self.pilot_tree.selection():
            return
        pid = int(self.pilot_tree.selection()[0])
        if pid == self.selected:
            return
        if not self.stage_archive():
            if self.pilot_tree.exists(str(self.selected)):
                self.pilot_tree.selection_set(str(self.selected))
            return
        self.selected = pid
        self.show_pilot()
        self.populate()
        self.pilot_tree.see(str(pid))

    def show_pilot(self):
        if self.selected is None:
            return
        p = self.session.pilots[self.selected]
        self.detail.configure(text=f'{p.name} · ID {p.pilot_id:02X}')
        value = self.pending.get(self.selected, p.settings)
        for i, (s,d) in enumerate(zip(value.spirits, p.defaults.spirits)):
            self.command_vars[i].set(SPIRIT_LABELS[s.command])
            self.cost_vars[i].set(str(s.cost) if s.command else '')
            self.level_vars[i].set(str(s.level) if s.command else '')
            self.cost_boxes[i].configure(state='normal' if s.command else 'disabled')
            self.level_boxes[i].configure(state='normal' if s.command else 'disabled')
            label = 'Empty' if not d.command else f'{SPIRIT_LABELS[d.command]} · SP {d.cost} · Lv {d.level}'
            self.default_labels[i].configure(text='Original: '+label)
        self.profile_var.set(PROFILE_LABELS[value.personality])
        self.description.set(core.SPIRITS[value.spirits[0].command]['description'])

    def command_changed(self, index):
        if self.selected is None:
            return
        sid = SPIRIT_IDS[self.command_vars[index].get()]
        self.description.set(core.SPIRITS[sid]['description'])
        self.cost_boxes[index].configure(state='normal' if sid else 'disabled')
        self.level_boxes[index].configure(state='normal' if sid else 'disabled')
        if not sid:
            self.cost_vars[index].set(''); self.level_vars[index].set('')
        elif not self.cost_vars[index].get() or not self.level_vars[index].get():
            self.cost_vars[index].set('20'); self.level_vars[index].set('1')

    def describe_profile(self, *_):
        pid = PROFILE_IDS.get(self.profile_var.get())
        if pid is not None:
            self.profile_description.set(behavior.summary(pid))

    def compare_profiles(self):
        window = tk.Toplevel(self.root)
        window.title('Will behavior · compare profiles')
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(window, text='Will gained or lost for each event', font=('Segoe UI', 14, 'bold'), padding=14).grid(row=0, column=0, sticky='w')
        frame = ttk.Frame(window, padding=(14, 0))
        frame.grid(row=1, column=0, sticky='nsew')
        frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
        columns = ('profile',) + behavior.EVENTS
        table = ttk.Treeview(frame, columns=columns, show='headings', height=12, selectmode='browse')
        for key in columns:
            table.heading(key, text='Profile / example pilots' if key == 'profile' else key)
            width = max(94, tkfont.nametofont('TkHeadingFont').measure(key)+24)
            table.column(key, width=295 if key == 'profile' else width, minwidth=90, stretch=key == 'profile', anchor='w' if key == 'profile' else 'center')
        for pid, item in core.PERSONALITIES.items():
            table.insert('', 'end', iid=str(pid), values=(f"{pid}: {item['name']}",) + tuple(map(behavior.signed, item['native_response_values'])))
        table.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(frame, command=table.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        details = tk.StringVar()
        description = ttk.Label(window, textvariable=details, padding=(14, 10), justify='left', wraplength=870)
        description.grid(row=2, column=0, sticky='ew')
        def select(_=None):
            if table.selection():
                pid = int(table.selection()[0])
                details.set(PROFILE_LABELS[pid] + '\n' + behavior.EXPLANATIONS[pid])
        table.bind('<<TreeviewSelect>>', select)
        table.selection_set(str(PROFILE_IDS.get(self.profile_var.get(), 0)))
        select()
        notes_frame = ttk.Frame(window)
        notes_frame.grid(row=3, column=0, sticky='nsew')
        notes_frame.columnconfigure(0, weight=1); notes_frame.rowconfigure(0, weight=1)
        notes = tk.Text(notes_frame, height=8, width=1, wrap='word', font=('Segoe UI', 9), relief='flat', padx=14, pady=8)
        notes.insert('1.0', behavior.GUIDE_NOTES); notes.configure(state='disabled')
        notes.grid(row=0, column=0, sticky='nsew')
        notes_scroll = ttk.Scrollbar(notes_frame, command=notes.yview)
        notes_scroll.grid(row=0, column=1, sticky='ns')
        notes.configure(yscrollcommand=notes_scroll.set)
        ttk.Button(window, text='Close guide', command=window.destroy).grid(row=4, column=0, sticky='e', padx=14, pady=12)
        window.bind('<Escape>', lambda _: window.destroy())
        window.bind('<Configure>', lambda e: description.configure(wraplength=max(250, e.width-28)) if e.widget == window else None)
        window.geometry('970x720'); window.minsize(680, 620)
        return window

    def defaults_selected(self):
        if self.selected is not None and not self.busy:
            p = self.session.pilots[self.selected]
            self.pending[self.selected] = p.defaults
            self.show_pilot(); self.stage_archive()

    def defaults_all(self):
        if self.session and not self.busy:
            self.pending = {pid:p.defaults for pid,p in self.session.pilots.items() if p.settings != p.defaults}
            self.show_pilot(); self.populate()

    def discard_archive(self):
        if not self.busy:
            self.pending.clear(); self.show_pilot(); self.populate()

    def review_archive(self):
        if not self.session or not self.stage_archive():
            return
        try:
            if core.resolve_target(self.target_var.get()) != self.session.target:
                raise core.PatchError('The path changed. Read that archive before writing.')
            _, changes = core.prepare_pilot(self.session.pilot, self.pending)
            if not changes:
                raise core.PatchError('No archive changes to write.')
            lines = [str(self.session.target), '', 'A verified backup is created before writing.', '']
            for item in changes:
                lines.append(item['name'])
                for i, (before, after) in enumerate(zip(item['before']['spirits'], item['after']['spirits'])):
                    if before != after:
                        def label(s):
                            return 'Empty' if not s['command'] else f"{SPIRIT_LABELS[s['command']]} · SP {s['cost']} · Lv {s['level']}"
                        lines.append(f"  {'Twin' if i == 5 else 'Slot '+str(i+1)}: {label(before)} → {label(after)}")
                if item['before']['personality'] != item['after']['personality']:
                    lines.append('  Will behavior: '+PROFILE_LABELS[item['before']['personality']]+' → '+PROFILE_LABELS[item['after']['personality']])
            updates = dict(self.pending)
            self.confirm('Review archive edits', '\n'.join(lines), lambda: self.job(lambda progress: self.session.install(updates, progress), self.written_archive), 'Write archive changes')
        except ValueError as exc:
            self.error(exc)

    def written_archive(self, result):
        messagebox.showinfo('Archive verified', 'Written and verified.\nBackup: '+result['backup']+'\n\nFresh-boot the game and load normally to test the changes.', parent=self.root)
        target = self.session.target
        self.job(lambda progress: core.Session(target, progress), self.loaded_archive)

    def restore_archive(self):
        if not self.session or self.busy or not self.stage_archive():
            return
        if self.pending:
            self.error('Write or discard staged archive changes before restoring an exact backup.'); return
        try:
            if core.resolve_target(self.target_var.get()) != self.session.target:
                raise ValueError('Read the selected archive first.')
        except ValueError as exc:
            self.error(exc); return
        path = filedialog.askopenfilename(title='Select backup patch.json', initialdir=self.session.target.parent/'_pilot_settings_backups', filetypes=[('Backup receipt','patch.json')])
        if path:
            self.confirm('Restore archive backup', 'Restore the exact archive preceding this patch:\n'+path+'\n\nThis requires a matching current archive. Use original defaults to preserve newer translations or other patches.', lambda: self.job(lambda progress: self.session.restore_backup(path, progress), self.written_archive), 'Restore archive backup')

    def browse_save(self):
        path = filedialog.askdirectory(title='Choose the BLJS10335_OMI-SCN save folder')
        if path:
            self.save_var.set(path)

    def read_save(self):
        if self.busy or not self.stage_will():
            return
        if self.will_pending and not messagebox.askyesno('Discard changes?', 'Reading again discards staged current Will edits.', parent=self.root):
            return
        try:
            path = Path(self.save_var.get()).resolve()
            snap = saves.snapshot_slot(path)
            info = saves.load_save(path)
            pilots = saves.load_will(path)
            if saves.snapshot_slot(path) != snap:
                raise ValueError('Save changed while reading. Exit the game and read it again.')
            self.save_path, self.save_snapshot = path, snap
            self.save_var.set(str(path))
            self.will_pilots = {p.pilot.pilot_id:p for p in pilots}
            self.will_pending.clear(); self.will_selected = None
            self.save_info.set(info.subtitle+' · '+str(len(pilots))+' pilots')
            self.populate()
            children = self.will_tree.get_children()
            if children:
                self.will_tree.selection_set(children[0]); self.select_will()
            self.status.set('Save read. Exit the game before writing; load normally afterward.')
        except (OSError, ValueError) as exc:
            self.error(exc)

    def select_will(self, _event=None):
        if self.busy or not self.will_tree.selection():
            return
        pid = int(self.will_tree.selection()[0])
        if pid == self.will_selected:
            return
        if not self.stage_will():
            if self.will_tree.exists(str(self.will_selected)):
                self.will_tree.selection_set(str(self.will_selected))
            return
        self.will_selected = pid
        self.will_detail.configure(text=self.will_pilots[pid].pilot.name)
        self.will_var.set(str(self.will_pending.get(pid, self.will_pilots[pid].will)))
        self.populate()
        self.will_tree.see(str(pid))

    def stage_will(self):
        if self.busy:
            return False
        if self.will_selected is None:
            return True
        try:
            value = int(self.will_var.get())
            old = self.will_pilots[self.will_selected].will
            if value != old and not 50 <= value <= 200:
                raise ValueError('Current Will must be from 50 to 200.')
            if value == old:
                self.will_pending.pop(self.will_selected, None)
            else:
                self.will_pending[self.will_selected] = value
            self.populate()
            self.status.set(f'{len(self.will_pending)} current Will edits staged.')
            return True
        except ValueError as exc:
            self.error(exc); return False

    def set_will(self, value):
        if self.will_selected is not None and not self.busy:
            self.will_var.set(str(value)); self.stage_will()

    def discard_will(self):
        if not self.busy:
            self.will_pending.clear()
            if self.will_selected is not None:
                self.will_var.set(str(self.will_pilots[self.will_selected].will))
            self.populate()

    def restore_will(self):
        if self.save_path is None or self.busy:
            return
        path = filedialog.askdirectory(title='Choose this slot inside its full backup folder', initialdir=self.save_path.parent/'_save_editor_backups')
        if path:
            try:
                self.will_pending = saves.backup_will_updates(self.save_path, path)
                if self.will_selected is not None:
                    self.will_var.set(str(self.will_pending.get(self.will_selected, self.will_pilots[self.will_selected].will)))
                self.populate()
                self.status.set('Backup Will values staged. Review and save to apply them; other save fields are preserved.')
            except (OSError, ValueError) as exc:
                self.error(exc)

    def review_will(self):
        if self.save_path is None or not self.stage_will():
            return
        try:
            if Path(self.save_var.get()).resolve() != self.save_path:
                raise ValueError('The path changed. Read that save first.')
            saves.prepare_will(self.save_path, self.will_pending)
            updates = dict(self.will_pending)
            lines = [str(self.save_path), '', 'A complete save-slot backup is created before writing.', '']
            lines += [f'{self.will_pilots[pid].pilot.name}: {self.will_pilots[pid].will} → {value}' for pid,value in updates.items()]
            self.confirm('Review current Will edits', '\n'.join(lines), lambda: self.job(lambda _: saves.write_will(self.save_path, updates, expected_snapshot=self.save_snapshot), self.written_will), 'Save current Will')
        except ValueError as exc:
            self.error(exc)

    def written_will(self, result):
        self.save_snapshot = result.snapshot
        self.will_pilots = {p.pilot.pilot_id:p for p in result.pilots}
        self.will_pending.clear()
        if self.will_selected is not None:
            self.will_var.set(str(self.will_pilots[self.will_selected].will))
        self.populate()
        self.status.set('Save verified. Backup: '+str(result.backup_path))
        messagebox.showinfo('Current Will saved', 'Written and verified.\nBackup: '+str(result.backup_path)+'\n\nLoad the slot normally to test it.', parent=self.root)

    def confirm(self, title, text, action, action_label='Write changes'):
        return ReviewDialog(self.root, title, text, action, action_label)

    def close(self):
        if self.busy:
            self.error('Wait for verification to finish before closing.'); return
        if not self.stage_archive() or not self.stage_will():
            return
        if (self.pending or self.will_pending) and not messagebox.askyesno('Discard changes?', 'Close without writing staged edits?', parent=self.root):
            return
        if self.session:
            self.session.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--save', type=Path)
    args = parser.parse_args()
    if args.check:
        result = dict(version=VERSION, pilots=len(core.PILOTS), commands=len(core.SPIRITS)-1, will_profiles=len(core.PERSONALITIES))
        check_root = None
        try:
            check_root = tk.Tk(); check_root.withdraw()
            check_app = App(check_root)
            check_root.update_idletasks()
            result['gui_constructed'] = True
            guide = check_app.compare_profiles()
            guide.destroy()
            review = check_app.confirm('Package check', 'No write action is attached.', lambda: None, 'Write archive changes')
            check_root.update_idletasks()
            result['review_actions_constructed'] = review.write_button.cget('text') == 'Write archive changes' and review.cancel_button.cget('text') == 'Cancel'
            result['write_requires_exit_checkbox'] = review.write_button.instate(['disabled'])
            review.destroy()
            result['profile_guide_constructed'] = True
            result['profile_8_summary'] = behavior.summary(8)
            if args.target:
                s = core.Session(args.target)
                check_app.loaded_archive(s)
                result.update(archive_read=True, archive_sha256=s.original['sha256'])
                s.close()
            if args.save:
                result.update(save_read=True, saved_pilots=len(saves.load_will(args.save)))
            result['ok'] = True
        except Exception as exc:
            result.update(ok=False,error=str(exc))
        finally:
            if check_root is not None:
                check_root.destroy()
        args.check.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        return
    root = tk.Tk(); app = App(root)
    if args.target:
        app.target_var.set(str(args.target)); root.after(100, app.read_archive)
    root.mainloop()


if __name__ == '__main__':
    main()
