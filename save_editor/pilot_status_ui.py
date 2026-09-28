"""Pilot status form; edits stay staged until Save pilot changes is pressed."""
from dataclasses import replace
import tkinter as tk
from tkinter import ttk, messagebox

from ogmd_save import SaveFormatError
from pilot_status import (STAT_NAMES, DISPLAY_ORDER, TERRAIN_NAMES, RATINGS, MAX_EXPERIENCE,
                          natural_stats, totals, terrain_ratings, from_totals, profile)


class StatusDialog(tk.Toplevel):
    def __init__(self, owner, pilot_id):
        super().__init__(owner.master)
        self.owner, self.pilot_id = owner, pilot_id
        self.value = owner.pending_status.get(pilot_id, owner.pilot_status[pilot_id])
        self.syncing = False
        self.title('Pilot status — ' + owner.pilots[pilot_id].name)
        self.geometry('680x670')
        self.minsize(580, 440)
        self.transient(owner.master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # Scroll the form, keeping Apply/Cancel visible on smaller displays.
        canvas = tk.Canvas(self, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scroll.set)
        form = ttk.Frame(canvas, padding=16)
        window = canvas.create_window((0, 0), window=form, anchor='nw')
        form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        self.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta / 120), 'units'))
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text=owner.pilots[pilot_id].name, font=('Segoe UI', 14, 'bold')).grid(
            row=0, column=0, columnspan=4, sticky='w', pady=(0, 10))
        self.level_var, self.exp_var = tk.StringVar(), tk.StringVar()
        ttk.Label(form, text='Level (1–99)').grid(row=1, column=0, sticky='w')
        ttk.Spinbox(form, from_=1, to=99, textvariable=self.level_var, width=10).grid(row=1, column=1, padx=8, pady=5)
        ttk.Label(form, text='EXP (0–65,535)').grid(row=1, column=2, sticky='w')
        ttk.Entry(form, textvariable=self.exp_var, width=12).grid(row=1, column=3, sticky='w', padx=8)
        ttk.Label(form, text='Changing level sets EXP to the start of that level. Changing EXP updates level.').grid(
            row=2, column=0, columnspan=4, sticky='w', pady=(0, 10))
        for col, label in enumerate(('Combat stat', 'Natural', 'Edit total', 'Training +')):
            ttk.Label(form, text=label).grid(row=3, column=col, sticky='w', padx=8)
        self.combat_vars = [tk.StringVar() for _ in STAT_NAMES]
        self.base_vars = [tk.StringVar() for _ in STAT_NAMES]
        self.bonus_vars = [tk.StringVar() for _ in STAT_NAMES]
        for row, i in enumerate(DISPLAY_ORDER, 4):
            ttk.Label(form, text=STAT_NAMES[i]).grid(row=row, column=0, sticky='w', padx=8)
            ttk.Label(form, textvariable=self.base_vars[i]).grid(row=row, column=1, sticky='w', padx=8)
            ttk.Entry(form, textvariable=self.combat_vars[i], width=10).grid(row=row, column=2, sticky='w', padx=8, pady=4)
            ttk.Label(form, textvariable=self.bonus_vars[i]).grid(row=row, column=3, sticky='w', padx=8)
        ttk.Label(form, text='Totals can be set from natural growth up to 400. Skill, Ace, Twin and battle bonuses\n'
                  'are calculated by the game and are not included here.', wraplength=610).grid(
            row=10, column=0, columnspan=4, sticky='w', pady=(8, 12))
        self.terrain_vars = [tk.StringVar() for _ in TERRAIN_NAMES]
        for col, label in enumerate(('Terrain', 'Natural', 'Edit rating', '')):
            ttk.Label(form, text=label).grid(row=11, column=col, sticky='w', padx=8)
        for row, (i, name) in enumerate(enumerate(TERRAIN_NAMES), 12):
            base = profile(pilot_id)['terrain'][i]
            ttk.Label(form, text=name).grid(row=row, column=0, sticky='w', padx=8)
            ttk.Label(form, text=RATINGS[base]).grid(row=row, column=1, sticky='w', padx=8)
            ttk.Combobox(form, values=RATINGS[base:], state='readonly', width=8,
                         textvariable=self.terrain_vars[i]).grid(row=row, column=2, sticky='w', padx=8, pady=4)
        ttk.Label(form, text='Terrain ratings can be raised to S or returned to their natural rating.\n'
                  'Base values use the bundled Moon Dwellers pilot data.', wraplength=610).grid(
            row=16, column=0, columnspan=4, sticky='w', pady=(8, 12))
        actions = ttk.Frame(form)
        actions.grid(row=17, column=0, columnspan=4, sticky='w')
        ttk.Button(actions, text='Combat totals to 400', command=self.max_combat).pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='Terrain to S', command=self.max_terrain).pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='Reset training', command=self.reset_training).pack(side='left')
        self.error_var = tk.StringVar()
        footer = ttk.Frame(self, padding=12)
        footer.grid(row=1, column=0, columnspan=2, sticky='ew')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.error_var, foreground='#b00020', wraplength=620).grid(
            row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(footer, text='Apply stages edits; Save pilot changes writes them.').grid(row=1, column=0, sticky='w')
        ttk.Button(footer, text='Cancel', command=self.destroy).grid(row=1, column=1, padx=8)
        self.apply_button = ttk.Button(footer, text='Apply', command=self.apply)
        self.apply_button.grid(row=1, column=2)
        self.render()
        self.level_var.trace_add('write', lambda *_: self.progress_changed('level'))
        self.exp_var.trace_add('write', lambda *_: self.progress_changed('exp'))
        for var in self.combat_vars:
            var.trace_add('write', lambda *_: self.combat_changed())
        self.bind('<Escape>', lambda e: self.destroy())
        self.grab_set()

    def read_form(self):
        try:
            return from_totals(self.pilot_id, self.value, tuple(int(v.get()) for v in self.combat_vars),
                               tuple(RATINGS.index(v.get()) for v in self.terrain_vars))
        except ValueError as exc:
            if isinstance(exc, SaveFormatError):
                raise
            raise SaveFormatError('Enter whole numbers for all combat stats.') from exc

    def render(self):
        self.syncing = True
        self.level_var.set(str(self.value.level))
        self.exp_var.set(str(self.value.experience))
        bases = natural_stats(self.pilot_id, self.value.experience)
        for i, value in enumerate(totals(self.pilot_id, self.value)):
            self.base_vars[i].set(str(bases[i]))
            self.combat_vars[i].set(str(value))
            self.bonus_vars[i].set(str(self.value.training[i]))
        for i, rating in enumerate(terrain_ratings(self.pilot_id, self.value)):
            self.terrain_vars[i].set(RATINGS[rating])
        self.error_var.set('')
        self.syncing = False

    def progress_changed(self, source):
        if self.syncing:
            return
        try:
            if source == 'level':
                level = int(self.level_var.get())
                if not 1 <= level <= 99:
                    raise SaveFormatError('Level must be 1–99.')
                exp = (level - 1) * 500
            else:
                exp = int(self.exp_var.get())
                if not 0 <= exp <= MAX_EXPERIENCE:
                    raise SaveFormatError('EXP must be 0–65,535.')
            # Keep the training already entered while recalculating natural growth.
            self.value = replace(self.read_form(), experience=exp)
            self.render()
        except ValueError as exc:
            self.error_var.set(str(exc) if isinstance(exc, SaveFormatError) else 'Enter a valid level / EXP.')

    def combat_changed(self):
        if self.syncing:
            return
        try:
            value = self.read_form()
            for i, bonus in enumerate(value.training):
                self.bonus_vars[i].set(str(bonus))
            self.error_var.set('')
        except SaveFormatError as exc:
            self.error_var.set(str(exc))

    def max_combat(self):
        for var in self.combat_vars:
            var.set('400')

    def max_terrain(self):
        for var in self.terrain_vars:
            var.set('S')

    def reset_training(self):
        self.value = replace(self.value, training=(0,) * 6, terrain_training=(0,) * 4)
        self.render()

    def apply(self):
        try:
            if int(self.exp_var.get()) != self.value.experience or int(self.level_var.get()) != self.value.level:
                raise SaveFormatError('Correct the level / EXP entry before applying.')
            value = self.read_form()
            self.owner.stage_status(self.pilot_id, value)
        except ValueError as exc:
            self.error_var.set(str(exc) if isinstance(exc, SaveFormatError) else 'Enter a valid level / EXP.')
            return
        self.destroy()


class PilotStatusUI:
    def edit_pilot_status(self, _event=None):
        selected = self.pilot_tree.selection()
        if not selected:
            messagebox.showerror('No pilot selected', 'Select a pilot first.', parent=self.master)
            return
        pid = int(selected[0])
        try:
            if self.pilot_status_error:
                raise SaveFormatError(self.pilot_status_error)
            profile(pid)
        except SaveFormatError as exc:
            messagebox.showerror('Status unavailable', str(exc), parent=self.master)
            return
        return StatusDialog(self, pid)

    def stage_status(self, pilot_id, value):
        from pilot_status import validate_status
        validate_status(pilot_id, value, self.pilot_status[pilot_id])
        if value == self.pilot_status[pilot_id]:
            self.pending_status.pop(pilot_id, None)
        else:
            self.pending_status[pilot_id] = value
        self._populate_pilots(tuple(self.pilots.values()))
        self._restore_tree_selection(self.pilot_tree, pilot_id)
        self.status_var.set(f'{len(self.pending_status)} pilot status edit(s) staged. Press Save pilot changes to write them.')

    def status_review(self):
        lines = []
        for pid, new in self.pending_status.items():
            old = self.pilot_status[pid]
            changes = []
            if new.experience != old.experience:
                changes.append(f'Lv {old.level} → {new.level}, EXP {old.experience} → {new.experience}')
            for i in DISPLAY_ORDER:
                if new.training[i] != old.training[i]:
                    changes.append(f'{STAT_NAMES[i]} training +{old.training[i]} → +{new.training[i]}')
            for i, name in enumerate(TERRAIN_NAMES):
                if new.terrain_training[i] != old.terrain_training[i]:
                    changes.append(f'{name} {RATINGS[terrain_ratings(pid, old)[i]]} → {RATINGS[terrain_ratings(pid, new)[i]]}')
            lines.append(self.pilots[pid].name + ': ' + ', '.join(changes))
        # The per-pilot dialog shows all values; keep the batch confirmation readable.
        return '\n'.join(lines[:6]) + (f'\n…plus {len(lines) - 6} more pilot(s).' if len(lines) > 6 else '')
