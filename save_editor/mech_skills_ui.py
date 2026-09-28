"""Mech Ability equipment and built-in enable switches for the Tk editor."""
import tkinter as tk
from tkinter import ttk, messagebox

from ogmd_save import SaveFormatError
from mech_skills import ABILITY_NAMES, BUILTINS, prepare_mech_changes, write_mech_changes


class MechSkillsUI:
    def build_mech_skills(self):
        self.mechs = {}
        self.pending_mech_equipped = {}
        self.pending_mech_builtins = {}
        self.mech_heading = tk.StringVar(value='Select a mech')
        self.mech_shared = tk.StringVar()
        self.mech_notice = tk.StringVar(value='Read a save first.')
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text='Mech skills')
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(2, weight=2)
        frame.rowconfigure(0, weight=1)
        self.mech_tree = ttk.Treeview(frame, columns=('name', 'id'), show='headings', selectmode='browse', height=10)
        self.mech_tree.heading('name', text='Saved mech / form (* = pending)')
        self.mech_tree.heading('id', text='ID')
        self.mech_tree.column('name', width=235, minwidth=150)
        self.mech_tree.column('id', width=55, stretch=False)
        self.mech_tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.mech_tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.mech_tree.configure(yscrollcommand=scroll.set)
        self.mech_tree.bind('<<TreeviewSelect>>', self.mech_selected)
        form = ttk.Frame(frame, padding=(16, 0, 0, 0))
        form.grid(row=0, column=2, sticky='nsew')
        form.columnconfigure(0, weight=1)
        ttk.Label(form, textvariable=self.mech_heading, font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=(0, 5))
        equipment = ttk.LabelFrame(form, text='Equipped Ability slots', padding=6)
        equipment.grid(row=1, column=0, sticky='ew')
        self.mech_ability_vars, self.mech_ability_boxes = [], []
        for i in range(3):
            equipment.columnconfigure(i, weight=1)
            value = tk.StringVar(value='Empty')
            self.mech_ability_vars.append(value)
            ttk.Label(equipment, text=f'Slot {i+1}').grid(row=0, column=i, sticky='w', padx=3)
            box = ttk.Combobox(equipment, textvariable=value, values=ABILITY_NAMES, state='readonly', width=15)
            box.grid(row=1, column=i, sticky='ew', padx=3)
            self.mech_ability_boxes.append(box)
        ttk.Label(form, textvariable=self.mech_shared, wraplength=530).grid(row=2, column=0, sticky='w', pady=5)
        builtin = ttk.LabelFrame(form, text='Built-in abilities — enabled when checked', padding=6)
        builtin.grid(row=3, column=0, sticky='ew')
        self.mech_builtin_vars, self.mech_builtin_boxes = [], []
        for i in range(5):
            value = tk.BooleanVar()
            self.mech_builtin_vars.append(value)
            box = ttk.Checkbutton(builtin, text=f'{i+1}. Empty', variable=value, state='disabled')
            box.grid(row=i//2, column=i%2, sticky='w', padx=(0, 12), pady=1)
            self.mech_builtin_boxes.append(box)
        ttk.Label(frame, textvariable=self.mech_notice, wraplength=930).grid(row=1, column=0, columnspan=3, sticky='w', pady=(8, 6))
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky='ew')
        buttons.columnconfigure(2, weight=1)
        ttk.Button(buttons, text='Apply to selected mech', command=self.stage_mech_skills).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text='Discard pending', command=self.discard_mech_skills).grid(row=0, column=1)
        ttk.Button(buttons, text='Save mech changes', command=self.save_mech_skills).grid(row=0, column=3)

    def set_mechs(self, mechs=(), error=None):
        self.mechs = {m.slot_index: m for m in mechs}
        self.pending_mech_equipped.clear()
        self.pending_mech_builtins.clear()
        self.mech_notice.set(str(error) if error else (
            'Equipped Abilities use your available inventory; shared forms stay synchronized. Add stock in Abilities inventory if needed.\n'
            'Built-in switches affect this form only. Adding or replacing a built-in skill requires a game-data patch. Names follow the bundled unit data.'
            if mechs else 'Read a save first.'))
        self.populate_mechs()
        self.mech_selected()

    def populate_mechs(self):
        selected = self.mech_tree.selection()
        self.mech_tree.delete(*self.mech_tree.get_children())
        query = self.search_var.get().strip().casefold()
        for index, mech in self.mechs.items():
            group = mech.shared_slots[0]
            equipment = self.pending_mech_equipped.get(group, mech.equipped)
            names = ' '.join(ABILITY_NAMES[i] for i in equipment) + ' ' + ' '.join(BUILTINS[i]['name'] for i in mech.builtins if i)
            if self._matches_search(query, mech.name, f'0x{mech.unit_id:X}', names):
                pending = group in self.pending_mech_equipped or index in self.pending_mech_builtins
                self.mech_tree.insert('', 'end', iid=str(index), values=(mech.name + (' *' if pending else ''), f'0x{mech.unit_id:02X}'))
        if selected and self.mech_tree.exists(selected[0]):
            self.mech_tree.selection_set(selected)
        else:
            self.mech_selected()
        self._set_search_count(6, len(self.mech_tree.get_children()), len(self.mechs))

    def mech_selected(self, _event=None):
        selected = self.mech_tree.selection()
        mech = self.mechs.get(int(selected[0])) if selected else None
        self.mech_heading.set(f'{mech.name} — 0x{mech.unit_id:02X}' if mech else 'Select a mech')
        self.mech_shared.set('Shared equipment: ' + ', '.join(self.mechs[i].name for i in mech.shared_slots) if mech and len(mech.shared_slots)>1 else '')
        for i in range(3):
            equipped = self.pending_mech_equipped.get(mech.shared_slots[0], mech.equipped) if mech else (0, 0, 0)
            self.mech_ability_vars[i].set(ABILITY_NAMES[equipped[i]])
            self.mech_ability_boxes[i].configure(state='readonly' if mech else 'disabled')
        for i in range(5):
            aid = mech.builtins[i] if mech else 0
            enabled = self.pending_mech_builtins.get(mech.slot_index, mech.enabled)[i] if mech else False
            # Empty slots retain their on-disk flags even though the UI shows no skill.
            self.mech_builtin_vars[i].set(enabled if aid else False)
            self.mech_builtin_boxes[i].configure(text=f'{i+1}. ' + (BUILTINS[aid]['name'] if aid else 'Empty'), state='normal' if aid else 'disabled')

    def stage_mech_skills(self):
        selected = self.mech_tree.selection()
        if not selected:
            messagebox.showinfo('Mech skills', 'Select a mech first.', parent=self.master)
            return
        mech = self.mechs[int(selected[0])]
        equipped = tuple(ABILITY_NAMES.index(v.get()) for v in self.mech_ability_vars)
        enabled = tuple(v.get() if mech.builtins[i] else mech.enabled[i] for i, v in enumerate(self.mech_builtin_vars))
        group = mech.shared_slots[0]
        if equipped == mech.equipped:
            self.pending_mech_equipped.pop(group, None)
        else:
            self.pending_mech_equipped[group] = equipped
        if enabled == mech.enabled:
            self.pending_mech_builtins.pop(mech.slot_index, None)
        else:
            self.pending_mech_builtins[mech.slot_index] = enabled
        self.populate_mechs()
        self.status_var.set('Mech changes staged. Use Save mech changes to validate inventory and write them.')

    def discard_mech_skills(self):
        self.pending_mech_equipped.clear()
        self.pending_mech_builtins.clear()
        self.populate_mechs()
        self.mech_selected()
        self.status_var.set('Pending mech changes discarded.')

    def save_mech_skills(self):
        if not self.current_slot or not (self.pending_mech_equipped or self.pending_mech_builtins):
            messagebox.showinfo('Mech skills', 'Apply a mech change first.', parent=self.master)
            return
        try:
            prepared = prepare_mech_changes(self.current_slot, self.pending_mech_equipped, self.pending_mech_builtins)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Cannot save mech changes', str(exc), parent=self.master)
            return
        changed = [m.name for m in prepared[4] if m != self.mechs.get(m.slot_index)]
        summary = ', '.join(changed[:10]) + (f' and {len(changed)-10} more' if len(changed)>10 else '')
        if not messagebox.askyesno('Save mech changes', f'Write changes for {summary}?\n\nShared Ability slots and available inventory will be updated together. Built-in switches affect only the selected forms.\n\nExit the game first. A complete slot backup will be created.', parent=self.master):
            return
        try:
            result = write_mech_changes(self.current_slot, self.pending_mech_equipped, self.pending_mech_builtins, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror('Cannot save mech changes', str(exc), parent=self.master)
            return
        self.loaded_snapshot = result.snapshot
        self.set_mechs(result.mechs)
        self.abilities = {a.ability_id: a for a in result.abilities}
        # Staged inventory totals remain valid intents; revalidate them on their own save.
        self._populate_abilities(result.abilities)
        self.status_var.set(f'Mech changes saved. Backup: {result.backup_path}')
        messagebox.showinfo('Mech changes saved', f'Load this slot through the normal in-game Load menu.\n\nBackup: {result.backup_path}', parent=self.master)
