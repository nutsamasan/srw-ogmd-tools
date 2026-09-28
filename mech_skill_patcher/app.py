"""Desktop editor for the five native mech skill assignments."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mech_patch import CATALOG, SKILLS, PatchError, Session, prepare_unit, resolve_target

VERSION = '1.0'
LABELS = {sid: ('Empty' if sid == 0 else f"{value['name']}  [{sid:02d}]") for sid, value in SKILLS.items()}
IDS = {label: sid for sid, label in LABELS.items()}
OPTIONS = [LABELS[0]] + [LABELS[sid] for sid in sorted(SKILLS.keys()-{0}, key=lambda sid: (SKILLS[sid]['name'], sid))]


def app_dir():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


class App:
    def __init__(self, root):
        self.root = root
        self.session = None
        self.pending = {}
        self.selected = None
        self.busy = False
        self.messages = queue.Queue()
        root.title(f'OGMD Mech Skill Patcher {VERSION}')
        root.geometry('1120x760')
        root.minsize(960, 690)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Treeview', rowheight=26)
        top = ttk.Frame(root, padding=(14, 12, 14, 8))
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text='Moon Dwellers · Built-in mech skills', font=('Segoe UI', 16, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(top, text='Choose a game archive, edit its five skill slots, and restore original skill defaults whenever needed.').grid(row=1, column=0, sticky='w', pady=(3, 10))
        self.target_var = tk.StringVar()
        known = app_dir()/'locations.json'
        paths = json.loads(known.read_text(encoding='utf8')) if known.is_file() else []
        paths = [p for p in paths if Path(p).is_file()]
        if paths:
            self.target_var.set(paths[0])
        target_row = ttk.Frame(top)
        target_row.grid(row=2, column=0, sticky='ew')
        target_row.columnconfigure(1, weight=1)
        ttk.Label(target_row, text='Game archive').grid(row=0, column=0, padx=(0, 8))
        self.target_box = ttk.Combobox(target_row, textvariable=self.target_var, values=paths)
        self.target_box.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(target_row, text='Browse…', command=self.browse)
        self.browse_button.grid(row=0, column=2, padx=8)
        self.read_button = ttk.Button(target_row, text='Read archive', command=self.read)
        self.read_button.grid(row=0, column=3)
        content = ttk.Frame(root, padding=(14, 0, 14, 0))
        content.grid(row=1, column=0, sticky='nsew')
        content.columnconfigure(0, weight=4)
        content.columnconfigure(1, weight=5)
        content.rowconfigure(1, weight=1)
        self.search_var = tk.StringVar()
        search_row = ttk.Frame(content)
        search_row.grid(row=0, column=0, sticky='ew', pady=(0, 8), padx=(0, 12))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text='Search mechs / skills').grid(row=0, column=0, padx=(0, 8))
        self.search = ttk.Entry(search_row, textvariable=self.search_var)
        self.search.grid(row=0, column=1, sticky='ew')
        self.search_var.trace_add('write', lambda *_: self.populate())
        tree_frame = ttk.Frame(content)
        tree_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 12))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=('name', 'id', 'state'), show='headings', selectmode='browse')
        for name, title, width in [('name', 'Mech / form', 250), ('id', 'ID', 44), ('state', 'Skills', 75)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, stretch=name == 'name')
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.detail = ttk.LabelFrame(content, text='Select a mech', padding=12)
        self.detail.grid(row=0, column=1, rowspan=2, sticky='nsew')
        self.detail.columnconfigure(1, weight=1)
        self.skill_vars = []
        self.skill_boxes = []
        self.default_labels = []
        for index in range(5):
            ttk.Label(self.detail, text=f'Slot {index+1}').grid(row=index*2, column=0, sticky='w', padx=(0, 12))
            value = tk.StringVar(value='Empty')
            box = ttk.Combobox(self.detail, textvariable=value, values=OPTIONS, state='disabled', width=35)
            box.grid(row=index*2, column=1, sticky='ew', pady=(2, 0))
            box.bind('<<ComboboxSelected>>', lambda _event, i=index: self.edit(i))
            box.bind('<FocusIn>', lambda _event, i=index: self.describe(i))
            self.skill_vars.append(value)
            self.skill_boxes.append(box)
            label = ttk.Label(self.detail, text='Original: —')
            label.grid(row=index*2+1, column=1, sticky='w', pady=(2, 12))
            self.default_labels.append(label)
        self.description = tk.StringVar(value='Skill descriptions appear here when you choose a slot.')
        ttk.Label(self.detail, textvariable=self.description, wraplength=420, justify='left').grid(row=10, column=0, columnspan=2, sticky='nw', pady=(10, 12))
        self.detail.rowconfigure(10, weight=1)
        ttk.Label(self.detail, text='Each form is separate. Changes affect every occurrence of that mech ID, including enemies. Skill requirements still apply.', wraplength=420, justify='left').grid(row=11, column=0, columnspan=2, sticky='sw')
        bottom = ttk.Frame(root, padding=14)
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(0, weight=1)
        self.summary = tk.StringVar(value='Read an archive to begin.')
        ttk.Label(bottom, textvariable=self.summary, font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(bottom, text='Choices are staged automatically. Restore defaults changes only skills and keeps English text.').grid(row=1, column=0, sticky='w', pady=(4, 8))
        buttons = ttk.Frame(bottom)
        buttons.grid(row=2, column=0, sticky='ew')
        buttons.columnconfigure(3, weight=1)
        self.default_button = ttk.Button(buttons, text='Restore selected defaults', command=self.defaults_selected)
        self.default_button.grid(row=0, column=0, padx=(0, 8))
        self.all_button = ttk.Button(buttons, text='Restore all defaults', command=self.defaults_all)
        self.all_button.grid(row=0, column=1, padx=(0, 8))
        self.discard_button = ttk.Button(buttons, text='Discard changes', command=self.discard)
        self.discard_button.grid(row=0, column=2)
        self.write_button = ttk.Button(buttons, text='Review and write…', command=self.review)
        self.write_button.grid(row=0, column=4)
        self.backup_button = ttk.Button(bottom, text='Restore exact backup…', command=self.restore_backup)
        self.backup_button.grid(row=3, column=0, sticky='w', pady=(9, 4))
        self.status = tk.StringVar(value='RPCS3 · PS3 BLJS10335 · Stop the game before writing. Fresh boot after patching.')
        ttk.Label(bottom, textvariable=self.status, wraplength=1030).grid(row=4, column=0, sticky='w')
        self.controls = [self.browse_button, self.read_button, self.search, self.default_button,
                         self.all_button, self.discard_button, self.write_button, self.backup_button]
        self.ready()
        root.after(80, self.poll)

    def ready(self):
        for widget in self.controls:
            widget.configure(state='disabled' if self.busy else 'normal')
        self.target_box.configure(state='disabled' if self.busy else 'normal')
        for widget in (self.default_button, self.all_button, self.backup_button):
            widget.configure(state='normal' if self.session and not self.busy else 'disabled')
        for widget in (self.write_button, self.discard_button):
            widget.configure(state='normal' if self.pending and not self.busy else 'disabled')
        for box in self.skill_boxes:
            box.configure(state='readonly' if self.selected is not None and not self.busy else 'disabled')

    def job(self, function, callback):
        if self.busy:
            return
        self.busy = True
        self.ready()
        def run():
            try:
                result = function(lambda msg: self.messages.put(('progress', msg)))
                self.messages.put(('done', (callback, result)))
            except Exception as exc:
                self.messages.put(('error', str(exc) or repr(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == 'progress':
                    self.status.set(payload)
                else:
                    self.busy = False
                    if kind == 'error':
                        self.status.set('Operation stopped: '+payload)
                        messagebox.showerror('Archive was not updated successfully', payload, parent=self.root)
                    else:
                        callback, value = payload
                        callback(value)
                    self.ready()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def browse(self):
        value = filedialog.askopenfilename(title='Select the game’s Logic archive', filetypes=[('Logic archive', 'Logic.psarc.sdat Logic.psarc'), ('All files', '*.*')])
        if value:
            self.target_var.set(value)

    def read(self):
        if self.pending and not messagebox.askyesno('Discard staged changes?', 'Reading an archive discards the staged changes.', parent=self.root):
            return
        target = self.target_var.get()
        self.job(lambda progress: Session(target, progress), self.loaded)

    def loaded(self, session):
        if self.session:
            self.session.close()
        self.session = session
        self.target_var.set(str(session.target))
        self.pending.clear()
        self.selected = None
        self.populate()
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.select()
        self.status.set('Loaded: '+str(session.target))

    def populate(self):
        if not hasattr(self, 'tree') or self.busy:
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        if not self.session:
            return
        query = self.search_var.get().strip().casefold()
        custom = 0
        for uid, mech in self.session.mechs.items():
            current = self.pending.get(uid, mech.skills)
            custom += current != mech.defaults
            haystack = f'{mech.name} {mech.installed_name} {uid} {uid:02x} '+ ' '.join(SKILLS[sid]['name'] for sid in current)
            if query and query not in haystack.casefold():
                continue
            state = 'Pending' if uid in self.pending else 'Custom' if current != mech.defaults else 'Default'
            self.tree.insert('', 'end', iid=str(uid), values=(mech.name, f'{uid:02X}', state))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected)
        else:
            self.selected = None
            self.detail.configure(text='Select a mech')
        self.summary.set(f'{len(self.tree.get_children())} mechs shown · {custom} custom · {len(self.pending)} staged changes')
        self.ready()

    def select(self, _event=None):
        if self.busy:
            return
        selection = self.tree.selection()
        if not selection or not self.session:
            self.selected = None
            self.ready()
            return
        uid = int(selection[0])
        if _event is not None and uid == self.selected:
            return
        self.selected = uid
        mech = self.session.mechs[uid]
        self.detail.configure(text=f'{mech.name} · ID {uid:02X}')
        values = self.pending.get(uid, mech.skills)
        for index, value in enumerate(values):
            self.skill_vars[index].set(LABELS[value])
            self.default_labels[index].configure(text='Original: '+LABELS[mech.defaults[index]])
        self.describe(0)
        self.ready()

    def describe(self, index):
        self.description.set(SKILLS[IDS[self.skill_vars[index].get()]]['description'])

    def set_pending(self, uid, values):
        if tuple(values) == self.session.mechs[uid].skills:
            self.pending.pop(uid, None)
        else:
            self.pending[uid] = tuple(values)

    def edit(self, index):
        if self.selected is None or self.busy:
            return
        self.set_pending(self.selected, [IDS[value.get()] for value in self.skill_vars])
        self.populate()
        self.describe(index)

    def defaults_selected(self):
        if self.selected is not None:
            self.set_pending(self.selected, self.session.mechs[self.selected].defaults)
            self.populate()
            self.select()

    def defaults_all(self):
        if self.session:
            for uid, mech in self.session.mechs.items():
                self.set_pending(uid, mech.defaults)
            self.populate()
            self.select()

    def discard(self):
        self.pending.clear()
        self.populate()
        self.select()

    def review(self):
        if self.busy or not self.session or not self.pending:
            return
        try:
            self.check_loaded_target()
            _, changes = prepare_unit(self.session.unit, self.pending)
        except PatchError as exc:
            messagebox.showerror('Check the skill choices', str(exc), parent=self.root)
            return
        lines = [str(self.session.target), '', 'A verified archive backup will be created before writing.', '']
        for change in changes:
            lines.extend([f"{change['name']} [ID {change['unit_id']:02X}]",
                          '  Current: '+', '.join(LABELS[sid] for sid in change['before']),
                          '  New:     '+', '.join(LABELS[sid] for sid in change['after']), ''])
        self.confirm('Review skill changes', '\n'.join(lines), self.write)

    def check_loaded_target(self):
        if resolve_target(self.target_var.get()) != self.session.target:
            raise PatchError('The selected path differs from the loaded archive. Click Read archive first.')

    def confirm(self, title, text, action):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry('900x570')
        window.minsize(760, 450)
        window.transient(self.root)
        window.grab_set()
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        body = tk.Text(frame, wrap='word', font=('Segoe UI', 10))
        body.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=body.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        body.configure(yscrollcommand=scroll.set)
        body.insert('1.0', text)
        body.configure(state='disabled')
        stopped = tk.BooleanVar()
        button = ttk.Button(frame, text='Write archive', state='disabled', command=lambda: (window.destroy(), action()))
        ttk.Checkbutton(frame, text='The game is stopped. I will start it fresh after writing.', variable=stopped,
                        command=lambda: button.configure(state='normal' if stopped.get() else 'disabled')).grid(row=1, column=0, sticky='w', pady=12)
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky='e')
        ttk.Button(buttons, text='Cancel', command=window.destroy).pack(side='left', padx=8)
        button.grid(row=2, column=0, sticky='w')

    def write(self):
        updates = dict(self.pending)
        self.job(lambda progress: self.session.install(updates, progress), self.written)

    def written(self, receipt):
        self.pending.clear()
        self.status.set('Written and verified. Backup: '+receipt['backup'])
        messagebox.showinfo('Archive verified', 'Changes written and verified.\n\nBackup:\n'+receipt['backup']+
                            '\n\nStart the game fresh, then use its normal Load menu. In-game behavior still needs testing.', parent=self.root)
        target = self.session.target
        self.job(lambda progress: Session(target, progress), self.loaded)

    def restore_backup(self):
        if not self.session or self.busy:
            return
        try:
            self.check_loaded_target()
        except PatchError as exc:
            messagebox.showerror('Read the selected archive first', str(exc), parent=self.root)
            return
        if self.pending:
            messagebox.showinfo('Staged changes', 'Write or discard your staged changes before restoring a backup.', parent=self.root)
            return
        value = filedialog.askopenfilename(title='Choose the backup’s patch.json', initialdir=self.session.target.parent/'_mech_skill_backups', filetypes=[('Patch record', 'patch.json')])
        if value:
            text = ('Restore the exact archive saved before this patch:\n\n'+value+'\n\nThe current archive is backed up first. '
                    'This operation requires the archive to still match that patch. For a newer translation update, use Restore all defaults instead.')
            self.confirm('Restore exact backup', text, lambda: self.job(lambda progress: self.session.restore_backup(value, progress), self.written))

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation in progress', 'Wait for archive verification to finish before closing.', parent=self.root)
            return
        if self.pending and not messagebox.askyesno('Discard staged changes?', 'Close without writing the staged skill changes?', parent=self.root):
            return
        if self.session:
            self.session.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', type=Path, help='Write a read-only packaged-runtime check report.')
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    if args.check:
        result = dict(version=VERSION, units=len(CATALOG['units'])-1, skills=len(SKILLS)-1, archive_read=False)
        try:
            if args.target:
                session = Session(args.target)
                result.update(archive_read=True, target=str(session.target), sha256=session.original['sha256'], mechs=len(session.mechs))
                session.close()
            result['ok'] = True
        except Exception as exc:
            result.update(ok=False, error=str(exc))
        args.check.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
        return
    root = tk.Tk()
    app = App(root)
    if args.target:
        app.target_var.set(str(args.target))
        root.after(100, app.read)
    root.mainloop()


if __name__ == '__main__':
    main()
