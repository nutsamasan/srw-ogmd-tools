"""Searchable weapon definitions with staged edits and guarded archive writes."""
from dataclasses import asdict
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from . import weapon_patch as core
from .weapon_data import FIELDS, LABELS, LIMITS, WeaponSettings, validate_settings
from .ui_dialogs import ReviewDialog


def app_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent


def suggested_archive():
    try:
        locations = json.loads((app_dir()/'weapon_archive_locations.json').read_text(encoding='utf8'))
        for path in locations:
            if Path(path).is_file():
                return path
    except (ValueError, OSError):
        pass
    # Derive the install from the save editor's existing RPCS3 save roots.
    try:
        roots = json.loads((app_dir()/'locations.json').read_text(encoding='utf8'))
        for root in roots:
            for parent in Path(root).parents:
                if parent.name == 'dev_hdd0':
                    path = parent/'game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat'
                    if path.is_file():
                        return str(path)
    except (ValueError, OSError):
        pass
    return ''


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, weapon, value, apply):
        super().__init__(parent)
        self.title('Edit weapon stats')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        body = ttk.Frame(self, padding=18)
        body.grid(sticky='nsew')
        ttk.Label(body, text=weapon.name, font=('Segoe UI', 13, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(body, text=f'{weapon.owner} · unit {weapon.unit:03d}, slot {weapon.slot}').grid(row=1, column=0, columnspan=3, sticky='w', pady=(3, 14))
        ttk.Label(body, text='New value').grid(row=2, column=1, sticky='w')
        ttk.Label(body, text='Original default').grid(row=2, column=2, sticky='w', padx=(18,0))
        self.values = {}
        self.entries = []
        for row, (field, label, (low, high)) in enumerate(zip(FIELDS, LABELS, LIMITS), 3):
            ttk.Label(body, text=f'{label} ({low:,}–{high:,})').grid(row=row, column=0, sticky='w', padx=(0,18), pady=7)
            var = tk.StringVar(self, value=str(getattr(value, field)))
            self.values[field] = var
            entry = ttk.Spinbox(body, textvariable=var, from_=low, to=high, width=12)
            entry.grid(row=row, column=1, sticky='ew')
            self.entries.append(entry)
            ttk.Label(body, text=str(getattr(weapon.defaults, field))).grid(row=row, column=2, sticky='w', padx=(18,0))
        ttk.Label(body, text='EN 0 / ammo 0: no cost of that type. Attack is before upgrades and bonuses.\n'
            'Some combination attacks calculate power from other weapons.\n'
            'MAP targeting shapes are separate and are not changed here.', wraplength=590).grid(row=8, column=0, columnspan=3, sticky='w', pady=(12,14))
        footer = ttk.Frame(body)
        footer.grid(row=9, column=0, columnspan=3, sticky='ew')
        self.error = tk.StringVar(self)
        ttk.Label(body, textvariable=self.error, foreground='#a32020', wraplength=560).grid(row=10, column=0, columnspan=3, sticky='w', pady=(8,0))

        def stage():
            try:
                settings = WeaponSettings(**{k:int(v.get()) for k,v in self.values.items()})
                validate_settings(settings)
            except (ValueError, TypeError) as exc:
                self.error.set(str(exc) if isinstance(exc, core.PatchError) else 'Enter whole numbers in every field.')
                return
            apply(settings)
            self.destroy()

        def defaults():
            for field, var in self.values.items():
                var.set(str(getattr(weapon.defaults, field)))

        self.apply_button = ttk.Button(footer, text='Stage these stats', command=stage)
        self.apply_button.pack(side='left')
        ttk.Button(footer, text='Use original defaults', command=defaults).pack(side='left', padx=10)
        ttk.Button(footer, text='Cancel', command=self.destroy).pack(side='right')
        self.bind('<Escape>', lambda _:self.destroy())
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        self.grab_set()
        self.entries[0].focus_set()


class WeaponEditor(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('OGMD · Weapon stats')
        self.geometry('1100x700')
        self.minsize(980, 610)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.session = None
        self.pending = {}
        self.busy = False
        self.messages = queue.Queue()
        self.controls = []
        self.path = tk.StringVar(self, value=suggested_archive())
        self.query = tk.StringVar(self)
        self.filter = tk.StringVar(self, value='All weapons')
        self.status = tk.StringVar(self, value='Select the installed Logic archive, then Read weapon data.')
        self.count = tk.StringVar(self)
        self.protocol('WM_DELETE_WINDOW', self.request_close)
        top = ttk.Frame(self, padding=(16,14,16,8))
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text='Weapon stats', font=('Segoe UI', 17, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(top, text='Game-wide weapon definitions · built-in and equippable weapons · PS3 BLJS10335').grid(row=1, column=0, columnspan=3, sticky='w', pady=(3,10))
        entry = ttk.Entry(top, textvariable=self.path)
        entry.grid(row=2, column=0, sticky='ew', padx=(0,8))
        self.controls.append(entry)
        self.button(top, 'Browse archive…', self.browse).grid(row=2,column=1,padx=(0,8))
        self.button(top, 'Read weapon data', self.read).grid(row=2,column=2)
        search = ttk.Frame(self, padding=(16,4,16,8))
        search.grid(row=1,column=0,sticky='ew')
        search.columnconfigure(1,weight=1)
        ttk.Label(search,text='Search weapon / mech').grid(row=0,column=0,padx=(0,10))
        entry=ttk.Entry(search,textvariable=self.query)
        entry.grid(row=0,column=1,sticky='ew'); self.controls.append(entry)
        combo=ttk.Combobox(search,textvariable=self.filter,values=('All weapons','Equippable only','Built-in only','Pending only'),state='readonly',width=18)
        combo.grid(row=0,column=2,padx=10); self.controls.append(combo)
        ttk.Label(search,textvariable=self.count).grid(row=0,column=3)
        area=ttk.Frame(self,padding=(16,0,16,0)); area.grid(row=2,column=0,sticky='nsew')
        area.columnconfigure(0,weight=1); area.rowconfigure(0,weight=1)
        columns=('weapon','owner','identity','power','range','en','ammo')
        self.tree=ttk.Treeview(area,columns=columns,show='headings',selectmode='browse',height=8)
        for key,label,width in zip(columns,('Weapon (* pending)','Mech / type','Unit / slot','Base attack','Range','EN cost','Max ammo'),(275,220,95,95,75,75,85)):
            self.tree.heading(key,text=label)
            self.tree.column(key,width=width,minwidth=65,stretch=key in ('weapon','owner'),anchor='w' if key in ('weapon','owner') else 'center')
        self.tree.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(area,command=self.tree.yview);scroll.grid(row=0,column=1,sticky='ns');self.tree.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.tree.xview);horizontal.grid(row=1,column=0,sticky='ew');self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.bind('<Double-1>',lambda _:self.edit_selected())
        self.tree.bind('<Return>',lambda _:self.edit_selected())
        footer=ttk.Frame(self,padding=16);footer.grid(row=3,column=0,sticky='ew');footer.columnconfigure(0,weight=1)
        edits=ttk.Frame(footer);edits.grid(row=0,column=0,sticky='ew')
        for label,command in (('Edit selected…',self.edit_selected),('Selected defaults',self.selected_defaults),('All original defaults',self.all_defaults),('Discard pending',self.discard)):
            self.button(edits,label,command).pack(side='left',padx=(0,8))
        ttk.Label(footer,text='Writes the loaded game archive and affects all saves using it. Upgrades and bonuses still apply.\n'
            'Restart the game after writing. Existing remaining ammo may require resupply or a new stage.\n'
            'The limits shown are native storage limits; extreme values have not been verified in-game.',wraplength=990).grid(row=1,column=0,sticky='w',pady=(12,10))
        actions=ttk.Frame(footer);actions.grid(row=2,column=0,sticky='ew')
        self.write_button=self.button(actions,'Review and write weapon stats…',self.review)
        self.write_button.pack(side='left')
        self.button(actions,'Restore archive backup…',self.restore).pack(side='left',padx=12)
        self.button(actions,'Close',self.request_close).pack(side='right')
        ttk.Label(footer,textvariable=self.status,wraplength=990).grid(row=3,column=0,sticky='w',pady=(12,0))
        self.query.trace_add('write',lambda *_:self.populate())
        self.filter.trace_add('write',lambda *_:self.populate())
        self.after(100,self.poll)

    def button(self,parent,label,command):
        button=ttk.Button(parent,text=label,command=command,padding=(7,4))
        self.controls.append(button)
        return button

    def request_close(self):
        if self.busy:
            messagebox.showinfo('Archive operation in progress','Wait for the archive operation to finish before closing.',parent=self)
            return False
        if self.pending and not messagebox.askyesno('Discard pending weapon edits?','Close without writing the staged weapon stats?',parent=self):
            return False
        if self.session:
            self.session.close()
        self.destroy()
        return True

    def run(self,job,done):
        if self.busy:return
        self.busy=True
        for control in self.controls:control.configure(state='disabled')
        def worker():
            try:self.messages.put(('done',(job(lambda text:self.messages.put(('progress',text))),done)))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=False).start()

    def poll(self):
        try:
            while True:
                kind,value=self.messages.get_nowait()
                if kind=='progress':self.status.set(value);continue
                self.busy=False
                for control in self.controls:control.configure(state='readonly' if isinstance(control,ttk.Combobox) else 'normal')
                if kind=='error':
                    self.status.set('Operation failed. '+value)
                    messagebox.showerror('Weapon editor',value,parent=self)
                else:
                    result,done=value;done(result)
        except queue.Empty:pass
        self.after(100,self.poll)

    def browse(self):
        value=filedialog.askopenfilename(parent=self,title='Select installed Logic archive',filetypes=[('Logic archives','*.sdat *.psarc'),('All files','*.*')],initialdir=str(Path(self.path.get()).parent) if self.path.get() else None)
        if value:self.path.set(value)

    def read(self):
        if self.busy:return
        if self.pending and not messagebox.askyesno('Discard pending weapon edits?','Reading again discards staged weapon edits. Continue?',parent=self):return
        target=self.path.get()
        self.status.set('Reading and verifying weapon definitions…')
        self.run(lambda progress:core.Session(target,progress),self.loaded)

    def loaded(self,session):
        if self.session:self.session.close()
        self.session=session;self.pending.clear();self.path.set(str(session.target))
        try:(app_dir()/'weapon_archive_locations.json').write_text(json.dumps([str(session.target)],indent=2)+'\n',encoding='utf8')
        except OSError:pass
        self.populate()
        self.status.set(f'Validated {len(session.weapons)} weapon definitions. No pending edits.')

    def populate(self):
        selected=self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        shown=0
        if self.session:
            query=self.query.get().casefold().strip();mode=self.filter.get()
            for key,w in self.session.weapons.items():
                if mode=='Equippable only' and w.unit or mode=='Built-in only' and not w.unit or mode=='Pending only' and key not in self.pending:continue
                if query and query not in f'{w.name} {w.installed_name} {w.owner} {w.unit} {w.slot}'.casefold():continue
                v=self.pending.get(key,w.settings)
                name=w.installed_name if w.installed_name.isascii() else w.name
                self.tree.insert('', 'end',iid=str(key),values=(name+(' *' if key in self.pending else ''),w.owner,f'{w.unit:03d} / {w.slot}',v.power,f'{v.minimum_range}–{v.maximum_range}',v.en_cost,v.ammo))
                shown+=1
        self.count.set(f'{shown} shown · {len(self.pending)} pending')
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected[0])

    def selected(self):
        if self.busy or not self.session:return None
        values=self.tree.selection()
        if not values:
            self.status.set('Select a weapon first.');return None
        return int(values[0])

    def stage(self,key,value):
        validate_settings(value)
        if value==self.session.weapons[key].settings:self.pending.pop(key,None)
        else:self.pending[key]=value
        self.populate();self.status.set(f'{len(self.pending)} weapon edits staged. Review and write when ready.')

    def edit_selected(self):
        key=self.selected()
        if key is not None:
            w=self.session.weapons[key]
            SettingsDialog(self,w,self.pending.get(key,w.settings),lambda value:self.stage(key,value))

    def selected_defaults(self):
        key=self.selected()
        if key is not None:self.stage(key,self.session.weapons[key].defaults)

    def all_defaults(self):
        if self.busy or not self.session:return
        self.pending={key:w.defaults for key,w in self.session.weapons.items() if w.defaults!=w.settings}
        self.populate();self.status.set(f'Original defaults staged for {len(self.pending)} weapons. Review before writing.')

    def discard(self):
        if self.busy:return
        self.pending.clear();self.populate();self.status.set('Pending weapon edits discarded.')

    def review(self):
        if self.busy or not self.session or not self.pending:
            self.status.set('Stage weapon edits before writing.');return
        _,changes=core.prepare_weapons(self.session.weapon,self.pending)
        text=f'Target archive:\n{self.session.target}\n\n{len(changes)} weapon definitions will change for every save using this archive.\n'
        text+='A verified archive backup will be created before installation.\n'
        text+='Restart the game after writing. Current saved ammo is not refilled by this operation.\n\n'
        for change in changes:
            text+=f"{change['owner']} · {change['name']} (unit {change['unit']}, slot {change['slot']})\n"
            for field,label in zip(FIELDS,LABELS):
                a,b=change['before'][field],change['after'][field]
                if a!=b:text+=f'  {label}: {a:,} → {b:,}\n'
            text+='\n'
        updates=dict(self.pending)
        ReviewDialog(self,'Review weapon stats',text,lambda:self.run(lambda p:self.session.install(updates,p),self.written),'Write weapon stats')

    def written(self,result):
        self.pending.clear()
        self.status.set('Archive written and verified. Backup: '+result['backup'])
        messagebox.showinfo('Weapon archive updated','Written and verified. Restart the game before testing.\n\nBackup:\n'+result['backup'],parent=self)
        target=self.session.target
        self.session.close();self.session=None;self.populate()
        self.run(lambda progress:core.Session(target,progress),self.loaded)

    def restore(self):
        if self.busy or not self.session:
            self.status.set('Read the target archive before restoring a backup.');return
        manifest=filedialog.askopenfilename(parent=self,title='Choose the matching weapon backup receipt',initialdir=str(self.session.target.parent/'_weapon_settings_backups'),filetypes=[('Backup receipt','patch.json')])
        if not manifest:return
        text=f'Restore the complete archive backup recorded in:\n{manifest}\n\nTarget:\n{self.session.target}\n\n'
        text+='This restores the exact earlier archive, including all its game data and text. Restoration is blocked if the current archive no longer matches this receipt. A backup of the current archive is created first.\n\nStaged weapon edits will be discarded after a successful restore.'
        ReviewDialog(self,'Restore weapon archive backup',text,lambda:self.run(lambda p:self.session.restore_backup(manifest,p),self.written),'Restore archive backup')


def open_editor(parent):
    existing=getattr(parent,'weapon_editor_window',None)
    if existing is not None and existing.winfo_exists():
        existing.lift();return existing
    window=WeaponEditor(parent)
    parent.weapon_editor_window=window
    return window
