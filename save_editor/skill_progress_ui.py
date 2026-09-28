"""Skill and game-progress tabs for the existing guarded Tk editor."""
import tkinter as tk
from tkinter import ttk, messagebox

from ogmd_save import SaveFormatError
from skill_progress import (
    SKILLS, SkillSlot, PilotSkills, MAX_COMPLETED_GAMES, natural_levels, learned_limit,
    load_pilot_skills, load_progress, validate_skill_changes,
    write_pilot_skills, write_completed_games, move_skill, changed_skill_mask,
)


class SkillProgressUI:
    def build_skill_progress(self):
        self.skill_pilots = {}
        self.pending_skills = {}
        self.pending_skill_masks = {}
        self.skill_form_mask = 0
        self.skill_drag_source = None
        self.skill_drag_target = None
        self.progress = None
        self.completed_var = tk.StringVar()
        self.progress_var = tk.StringVar(value="Read a save first.")
        self.skill_heading = tk.StringVar(value="Select a pilot")
        self.skill_names = ["Empty"] + [SKILLS[i]["name"] for i in range(2, 45)]
        self.skill_ids = [0] + list(range(2, 45))
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Pilot skills")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(2, weight=2)
        frame.rowconfigure(0, weight=1)
        self.skill_tree = ttk.Treeview(frame, columns=("pilot",), show="headings", selectmode="browse", height=9)
        self.skill_tree.heading("pilot", text="Pilot (* = pending)")
        self.skill_tree.column("pilot", width=200, minwidth=150)
        self.skill_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.skill_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.skill_tree.configure(yscrollcommand=scroll.set)
        self.skill_tree.bind("<<TreeviewSelect>>", self.skill_selected)
        form = ttk.Frame(frame, padding=(16, 0, 0, 0))
        self.skill_form = form
        form.grid(row=0, column=2, sticky="nsew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, textvariable=self.skill_heading, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        for col, label in enumerate(("Slot", "Skill", "Training +", "Natural / limit")):
            ttk.Label(form, text=label).grid(row=1, column=col, sticky="w", padx=3)
        self.skill_vars, self.skill_level_vars, self.skill_notes, self.skill_boxes = [], [], [], []
        self.skill_level_boxes, self.skill_handles = [], []
        ttk.Style().configure("SkillDrop.TLabel", background="#cce8ff", foreground="#003b65")
        for index in range(6):
            name, level, note = tk.StringVar(value="Empty"), tk.StringVar(value="0"), tk.StringVar()
            self.skill_vars.append(name)
            self.skill_level_vars.append(level)
            self.skill_notes.append(note)
            handle = ttk.Label(form, text=f"↕ {index+1}", cursor="hand2", padding=3, takefocus=True)
            handle.grid(row=index+2, column=0, padx=3)
            handle.bind("<ButtonPress-1>", lambda e, i=index: self.skill_drag_start(e, i))
            handle.bind("<B1-Motion>", self.skill_drag_motion)
            handle.bind("<ButtonRelease-1>", self.skill_drag_end)
            handle.bind("<Escape>", self.cancel_skill_drag)
            handle.bind("<Alt-Up>", lambda e, i=index: self.move_skill_row(i, i-1))
            handle.bind("<Alt-Down>", lambda e, i=index: self.move_skill_row(i, i+1))
            self.skill_handles.append(handle)
            box = ttk.Combobox(form, textvariable=name, values=self.skill_names, state="readonly", width=23)
            box.grid(row=index+2, column=1, sticky="ew", padx=3, pady=3)
            box.bind("<<ComboboxSelected>>", lambda e, i=index: self.skill_choice_changed(i))
            self.skill_boxes.append(box)
            level_box = ttk.Spinbox(form, from_=0, to=9, textvariable=level, width=5)
            level_box.grid(row=index+2, column=2, padx=6)
            self.skill_level_boxes.append(level_box)
            ttk.Label(form, textvariable=note, width=17).grid(row=index+2, column=3, sticky="w")
        ttk.Label(form, text="Drag ↕ to reorder (or focus it and press Alt+↑/↓).\nMoves are staged automatically; use Save skill changes.\nCurrent levels and future growth are preserved. Incompatible moves are blocked.",
                  wraplength=490).grid(row=8, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Label(frame, text="Training adds to natural skill levels. Keep 0 for natural growth; new leveled skills need at least 1.\nLimits leave room for future natural growth. Skills without levels use 0 or 1; their name enables them.", wraplength=930).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 6))
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew")
        buttons.columnconfigure(2, weight=1)
        ttk.Button(buttons, text="Apply to selected pilot", command=self.stage_skills).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Discard pending", command=self.discard_skills).grid(row=0, column=1)
        ttk.Button(buttons, text="Save skill changes", command=self.save_skills).grid(row=0, column=3)

        progress = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(progress, text="Completed games")
        ttk.Label(progress, text="Completed-game count", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(progress, textvariable=self.progress_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(progress, text="Completed games").grid(row=2, column=0, sticky="w", padx=(0, 12))
        ttk.Spinbox(progress, from_=0, to=MAX_COMPLETED_GAMES, textvariable=self.completed_var, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(progress, text="0 = no completed games; 1 = completed once.\nDuring a normal playthrough, the lap number is completed games + 1.\nThis edits the count in this scenario save; it does not finish a scenario or create clear data.", wraplength=830).grid(row=3, column=0, columnspan=2, sticky="w", pady=16)
        ttk.Button(progress, text="Save completed-game count", command=self.save_completed_games).grid(row=4, column=0, columnspan=2, sticky="w")

    def set_skill_progress(self, pilots=(), progress=None):
        self.skill_pilots = {p.pilot.pilot_id: p for p in pilots}
        self.pending_skills.clear()
        self.pending_skill_masks.clear()
        self.progress = progress
        self.completed_var.set(str(progress.completed_games) if progress else "")
        self.progress_var.set(f"Loaded count: {progress.completed_games}" + (" (clear-data save)" if progress.clear_save else "") if progress else "Read a save first.")
        self.populate_skills()

    def populate_skills(self):
        selected = self.skill_tree.selection()
        self.skill_tree.delete(*self.skill_tree.get_children())
        query = self.search_var.get().strip().casefold()
        for pid, item in self.skill_pilots.items():
            slots = self.pending_skills.get(pid, item.slots)
            names = " ".join(SKILLS[s.skill_id]["name"] for s in slots)
            if self._matches_search(query, item.pilot.name, f"0x{pid:X}", names):
                self.skill_tree.insert("", "end", iid=str(pid), values=(item.pilot.name + (" *" if pid in self.pending_skills else ""),))
        if selected and self.skill_tree.exists(selected[0]):
            self.skill_tree.selection_set(selected)
        else:
            self.skill_selected()
        self._set_search_count(4, len(self.skill_tree.get_children()), len(self.skill_pilots))

    def skill_selected(self, _event=None):
        self.cancel_skill_drag()
        selected = self.skill_tree.selection()
        if not selected:
            self.skill_form_mask = 0
            self.skill_heading.set("Select a pilot")
            for i in range(6):
                self.skill_vars[i].set("Empty")
                self.skill_level_vars[i].set("0")
                self.skill_notes[i].set("")
            return
        pid = int(selected[0])
        item = self.skill_pilots[pid]
        self.skill_form_mask = self.pending_skill_masks.get(pid, item.natural_disabled)
        self.skill_heading.set(f"{item.pilot.name} — pilot level {min(item.pilot.experience, 49000)//500+1}")
        for i, skill in enumerate(self.pending_skills.get(pid, item.slots)):
            self.skill_vars[i].set(SKILLS[skill.skill_id]["name"])
            self.skill_level_vars[i].set(str(skill.learned_levels))
            self.update_skill_note(i, item.pilot, skill.skill_id)

    def update_skill_note(self, index, pilot, sid):
        self.skill_level_boxes[index].configure(state="disabled")
        if sid < 2:
            self.skill_notes[index].set("Empty" if sid == 0 else "Reserved")
        elif not SKILLS[sid]["has_levels"]:
            self.skill_notes[index].set("No levels")
        else:
            disabled = bool(self.skill_form_mask & (1 << index))
            base = natural_levels(pilot, index, sid, disabled=disabled)
            limit = learned_limit(pilot, index, sid, disabled=disabled)
            minimum = 0 if natural_levels(pilot, index, sid, maximum=True, disabled=disabled) else 1
            self.skill_level_boxes[index].configure(from_=minimum, to=limit, state="normal" if limit else "disabled")
            self.skill_notes[index].set(f"{base} natural / +{limit}")

    def skill_choice_changed(self, index):
        selected = self.skill_tree.selection()
        if not selected:
            return
        pilot = self.skill_pilots[int(selected[0])].pilot
        sid = self.skill_ids[self.skill_names.index(self.skill_vars[index].get())]
        # Only this deliberately changed choice gets a new replacement flag.
        slots = tuple(SkillSlot(0, 0) for _ in range(6))
        original = list(slots)
        original[index] = SkillSlot(-1, 0)
        changed = list(slots)
        changed[index] = SkillSlot(sid, 0)
        self.skill_form_mask = changed_skill_mask(pilot, original, changed, self.skill_form_mask)
        level = 0 if sid < 2 or natural_levels(pilot, index, sid, maximum=True) else 1
        self.skill_level_vars[index].set(str(level))
        self.update_skill_note(index, pilot, sid)

    def read_skill_form(self):
        selected = self.skill_tree.selection()
        if not selected:
            raise SaveFormatError("Select a pilot first.")
        item = self.skill_pilots[int(selected[0])]
        slots = tuple(SkillSlot(next(k for k, v in SKILLS.items() if v["name"] == name.get()), int(level.get()))
                      for name, level in zip(self.skill_vars, self.skill_level_vars))
        slots = validate_skill_changes(item.pilot, item.slots, slots,
                    original_mask=item.natural_disabled, natural_disabled=self.skill_form_mask)
        return PilotSkills(item.pilot, slots, self.skill_form_mask)

    def cancel_skill_drag(self, _event=None):
        self.skill_drag_source = self.skill_drag_target = None
        for handle in self.skill_handles:
            handle.configure(style="TLabel")

    def skill_drag_start(self, event, index):
        if not self.skill_tree.selection():
            return "break"
        self.cancel_skill_drag()
        self.skill_drag_source = self.skill_drag_target = index
        event.widget.focus_set()
        self.skill_handles[index].configure(style="SkillDrop.TLabel")
        return "break"

    def skill_drag_motion(self, event):
        if self.skill_drag_source is None:
            return "break"
        target = None
        left = self.skill_handles[0].winfo_rootx()
        right = self.skill_form.winfo_rootx() + self.skill_form.winfo_width()
        if left <= event.x_root <= right:
            for index, box in enumerate(self.skill_boxes):
                if box.winfo_rooty()-3 <= event.y_root < box.winfo_rooty()+box.winfo_height()+3:
                    target = index
                    break
        self.skill_drag_target = target
        for index, handle in enumerate(self.skill_handles):
            handle.configure(style="SkillDrop.TLabel" if index == target else "TLabel")
        return "break"

    def skill_drag_end(self, event):
        self.skill_drag_motion(event)
        source, target = self.skill_drag_source, self.skill_drag_target
        self.cancel_skill_drag()
        if source is not None and target is not None:
            self.move_skill_row(source, target)
        return "break"

    def move_skill_row(self, source, target):
        if not 0 <= target < 6 or source == target:
            return "break"
        try:
            moved = move_skill(self.read_skill_form(), source, target)
            original = self.skill_pilots[moved.pilot.pilot_id]
            validate_skill_changes(moved.pilot, original.slots, moved.slots,
                original_mask=original.natural_disabled, natural_disabled=moved.natural_disabled)
        except (ValueError, StopIteration) as exc:
            messagebox.showerror("Cannot move skill", str(exc) or "Enter whole-number training levels first.", parent=self.master)
            return "break"
        self.skill_form_mask = moved.natural_disabled
        for index, skill in enumerate(moved.slots):
            self.skill_vars[index].set(SKILLS[skill.skill_id]["name"])
            self.skill_level_vars[index].set(str(skill.learned_levels))
            self.update_skill_note(index, moved.pilot, skill.skill_id)
        self.stage_skills()
        self.skill_handles[target].focus_set()
        return "break"

    def stage_skills(self):
        selected = self.skill_tree.selection()
        if not selected:
            messagebox.showinfo("Pilot skills", "Select a pilot first.", parent=self.master)
            return
        pid = int(selected[0])
        item = self.skill_pilots[pid]
        try:
            slots = self.read_skill_form().slots
        except (ValueError, StopIteration) as exc:
            messagebox.showerror("Invalid skill change", str(exc) or "Choose a skill and a whole-number training level.", parent=self.master)
            return
        if slots == item.slots and self.skill_form_mask == item.natural_disabled:
            self.pending_skills.pop(pid, None)
            self.pending_skill_masks.pop(pid, None)
        else:
            self.pending_skills[pid] = slots
            self.pending_skill_masks[pid] = self.skill_form_mask
        self.populate_skills()
        self.status_var.set(f"Skill changes staged for {len(self.pending_skills)} pilot(s). Use Save skill changes to write them.")

    def discard_skills(self):
        self.pending_skills.clear()
        self.pending_skill_masks.clear()
        self.populate_skills()
        self.skill_selected()
        self.status_var.set("Pending skill changes discarded.")

    def save_skills(self):
        if not self.current_slot or not self.pending_skills:
            messagebox.showinfo("Pilot skills", "Apply a skill change first.", parent=self.master)
            return
        names = ", ".join(self.skill_pilots[pid].pilot.name for pid in self.pending_skills)
        if not messagebox.askyesno("Save pilot skills", f"Write the staged skills for {names}?\n\nExit the game first. A complete slot backup will be created.", parent=self.master):
            return
        try:
            result = write_pilot_skills(self.current_slot, self.pending_skills,
                natural_disabled_updates=self.pending_skill_masks, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Could not save skills", str(exc), parent=self.master)
            return
        self.loaded_snapshot = result.snapshot
        self.skill_pilots = {p.pilot.pilot_id: p for p in result.pilots}
        self.pending_skills.clear()
        self.pending_skill_masks.clear()
        self.populate_skills()
        self.skill_selected()
        self.status_var.set(f"Skills saved. Backup: {result.backup_path}")
        messagebox.showinfo("Skills saved", f"Saved and verified.\n\nBackup: {result.backup_path}", parent=self.master)

    def save_completed_games(self):
        if not self.current_slot or self.progress is None:
            messagebox.showinfo("Completed games", "Read a save first.", parent=self.master)
            return
        try:
            count = int(self.completed_var.get())
            if not 0 <= count <= MAX_COMPLETED_GAMES:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid count", f"Enter a whole number from 0 to {MAX_COMPLETED_GAMES}.", parent=self.master)
            return
        if count == self.progress.completed_games:
            self.status_var.set("Completed-game count is unchanged.")
            return
        if not messagebox.askyesno("Save completed games", f"Change completed games from {self.progress.completed_games} to {count}?\n\nExit the game first. A complete slot backup will be created.", parent=self.master):
            return
        try:
            result = write_completed_games(self.current_slot, count, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Could not save count", str(exc), parent=self.master)
            return
        self.loaded_snapshot = result.snapshot
        self.progress = result.progress
        self.progress_var.set(f"Loaded count: {result.progress.completed_games}")
        self.status_var.set(f"Completed-game count saved. Backup: {result.backup_path}")
        messagebox.showinfo("Completed games saved", f"Saved and verified.\n\nBackup: {result.backup_path}", parent=self.master)
