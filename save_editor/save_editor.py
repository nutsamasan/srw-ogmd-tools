"""Windows GUI for OG Moon Dwellers saves and native weapon definitions."""

from __future__ import annotations

import argparse
from pathlib import Path
from dataclasses import replace
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ogmd_save import (
    snapshot_slot,
    ABILITY_STOCK_TARGET,
    MAX_ABILITIES,
    MAX_FUNDS,
    MAX_KILLS,
    MAX_PARTS,
    MAX_PP,
    MAX_WILL,
    WEAPON_SLOT_COUNT,
    WEAPON_TARGET_COPIES,
    AbilityInfo,
    PartInfo,
    PilotInfo,
    SaveFormatError,
    WeaponInfo,
    load_abilities,
    load_pilots,
    load_parts,
    load_save,
    load_weapons,
    write_funds,
    write_abilities,
    write_pilot_stats,
    write_parts,
    write_weapon_totals,
)


from skill_progress_ui import SkillProgressUI
from skill_progress import load_pilot_skills, load_progress
from mech_skills_ui import MechSkillsUI
from mech_skills import load_mechs
from seishin_patch import DEFAULT_PPU_HASH, build_patch


from pilot_status_ui import PilotStatusUI
from pilot_status import load_status


class SaveEditor(PilotStatusUI, SkillProgressUI, MechSkillsUI, ttk.Frame):
    def __init__(self, master: tk.Tk, initial_slot: str = "") -> None:
        super().__init__(master, padding=16)
        self.master = master
        self.loaded_snapshot = None
        self.current_slot: Path | None = None
        self.pilots: dict[int, PilotInfo] = {}
        self.pending_pp: dict[int, int] = {}
        self.pending_kills: dict[int, int] = {}
        self.pending_will: dict[int, int] = {}
        self.pilot_status = {}
        self.pilot_status_error = None
        self.pending_status = {}
        self.parts: dict[int, PartInfo] = {}
        self.pending_parts: dict[int, int] = {}
        self.abilities: dict[int, AbilityInfo] = {}
        self.pending_abilities: dict[int, int] = {}
        self.weapons: dict[int, WeaponInfo] = {}
        self.pending_weapons: dict[int, int] = {}
        self.folder_var = tk.StringVar(value=initial_slot)
        self.title_var = tk.StringVar(value="Not loaded")
        self.funds_var = tk.StringVar()
        self.total_funds_var = tk.StringVar(value="Not loaded")
        self.spent_funds_var = tk.StringVar(value="Not loaded")
        self.pilot_pp_var = tk.StringVar()
        self.pilot_kills_var = tk.StringVar()
        self.pilot_will_var = tk.StringVar()
        self.part_total_var = tk.StringVar()
        self.ability_total_var = tk.StringVar()
        self.weapon_total_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.search_result_var = tk.StringVar(value="0 shown")
        self.status_var = tk.StringVar(value="Select an RPCS3 scenario-save folder.")
        self.seishin_ppu_var = tk.StringVar(value=DEFAULT_PPU_HASH)
        self.seishin_vars = [tk.StringVar() for _ in range(6)]
        self.seishin_zero_sp_var = tk.BooleanVar(value=False)
        self.seishin_unlock_all_var = tk.BooleanVar(value=False)
        self._build()
        if initial_slot:
            self.after_idle(self.load_selected)

    def _build(self) -> None:
        self.master.title("OG Moon Dwellers — RPCS3 Save Editor 1.6")
        self.master.protocol('WM_DELETE_WINDOW', self.close_editor)
        self.master.geometry("1050x800")
        self.master.minsize(950, 790)
        self.grid(sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)

        ttk.Label(
            self,
            text="Super Robot Wars OG: The Moon Dwellers — RPCS3 Save Editor",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            self,
            text="Scenario saves only. Exit the game before writing; RPCS3 itself may stay open.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 16))

        ttk.Label(self, text="Save folder").grid(row=2, column=0, sticky="w")
        ttk.Button(self, text="Find saves…", command=self.find_saves).grid(row=2, column=2, sticky="e", pady=(0, 5))
        folder = ttk.Entry(self, textvariable=self.folder_var)
        folder.grid(row=3, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(self, text="Browse…", command=self.browse).grid(row=3, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(self, text="Read save", command=self.load_selected).grid(row=3, column=2, sticky="ew")

        details = ttk.LabelFrame(self, text="Loaded save", padding=12)
        details.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=16)
        details.columnconfigure(1, weight=1)
        ttk.Label(details, text="Scenario").grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Label(details, textvariable=self.title_var, wraplength=570).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(details, text="Funds (current)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        validate = (self.register(self._validate_funds_text), "%P")
        funds = ttk.Entry(details, textvariable=self.funds_var, width=20, validate="key", validatecommand=validate)
        funds.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(details, text=f"Allowed: 0–{MAX_FUNDS:,}").grid(row=2, column=1, sticky="w")
        ttk.Label(details, text="Funds earned (total)").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=4
        )
        ttk.Label(details, textvariable=self.total_funds_var).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(details, text="Funds spent").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Label(details, textvariable=self.spent_funds_var).grid(row=4, column=1, sticky="w", pady=4)
        ttk.Button(details, text="Save funds", command=self.save_funds).grid(
            row=1, column=2, rowspan=2, sticky="e", padx=(16, 0)
        )

        search = ttk.Frame(self)
        search.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Search current tab").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(search, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(search, text="Clear", command=self.clear_search).grid(
            row=0, column=2, padx=(8, 8)
        )
        ttk.Label(search, textvariable=self.search_result_var).grid(row=0, column=3, sticky="e")

        self.notebook = ttk.Notebook(self)
        notebook = self.notebook
        notebook.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(0, 16))

        pilots = ttk.Frame(notebook, padding=12)
        notebook.add(pilots, text="Pilot stats")
        pilots.columnconfigure(0, weight=1)
        pilots.rowconfigure(0, weight=1)
        columns = ("name", "id", "kills", "experience", "will", "pp")
        self.pilot_tree = ttk.Treeview(pilots, columns=columns, show="headings", height=12, selectmode="browse")
        self.pilot_tree.heading("name", text="Pilot")
        self.pilot_tree.heading("id", text="ID")
        self.pilot_tree.heading("kills", text="Kills")
        self.pilot_tree.heading("experience", text="Level / EXP")
        self.pilot_tree.heading("pp", text="PP")
        self.pilot_tree.heading("will", text="Will")
        self.pilot_tree.column("name", width=220, minwidth=130, anchor="w")
        self.pilot_tree.column("id", width=65, minwidth=55, anchor="center", stretch=False)
        self.pilot_tree.column("kills", width=75, minwidth=60, anchor="e", stretch=False)
        self.pilot_tree.column("experience", width=130, minwidth=110, anchor="e", stretch=False)
        self.pilot_tree.column("pp", width=80, minwidth=65, anchor="e", stretch=False)
        self.pilot_tree.column("will", width=70, minwidth=60, anchor="e", stretch=False)
        self.pilot_tree.grid(row=0, column=0, columnspan=5, sticky="nsew")
        scrollbar = ttk.Scrollbar(pilots, orient="vertical", command=self.pilot_tree.yview)
        scrollbar.grid(row=0, column=5, sticky="ns")
        self.pilot_tree.configure(yscrollcommand=scrollbar.set)
        self.pilot_tree.bind("<<TreeviewSelect>>", self._pilot_selected)
        self.pilot_tree.bind("<Double-1>", self.edit_pilot_status)
        ttk.Button(pilots, text="Edit status…", command=self.edit_pilot_status).grid(
            row=1, column=4, sticky="e", pady=(10, 0))

        ttk.Label(pilots, text="Selected pilot PP").grid(row=1, column=0, sticky="w", pady=(10, 0))
        pp_validate = (self.register(self._validate_pp_text), "%P")
        ttk.Entry(
            pilots,
            textvariable=self.pilot_pp_var,
            width=12,
            validate="key",
            validatecommand=pp_validate,
        ).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ttk.Button(pilots, text="Apply to selected", command=self.stage_selected_pp).grid(
            row=1, column=2, sticky="w", pady=(10, 0)
        )
        ttk.Label(pilots, text="Selected pilot kills").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        kills_validate = (self.register(self._validate_kills_text), "%P")
        ttk.Entry(
            pilots,
            textvariable=self.pilot_kills_var,
            width=12,
            validate="key",
            validatecommand=kills_validate,
        ).grid(row=2, column=1, sticky="w", padx=(8, 8), pady=(8, 0))
        ttk.Button(pilots, text="Apply kills", command=self.stage_selected_kills).grid(
            row=2, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(pilots, text="Selected pilot Will").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        will_validate = (self.register(self._validate_will_text), "%P")
        ttk.Entry(
            pilots,
            textvariable=self.pilot_will_var,
            width=12,
            validate="key",
            validatecommand=will_validate,
        ).grid(row=3, column=1, sticky="w", padx=(8, 8), pady=(8, 0))
        ttk.Button(pilots, text="Apply Will", command=self.stage_selected_will).grid(
            row=3, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(pilots, text="0–255 raw byte; 100–190 is the useful gameplay range.").grid(
            row=3, column=3, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        ttk.Button(pilots, text=f"Set all PP to {MAX_PP:,}", command=self.stage_all_pp).grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(pilots, text=f"Set all kills to {MAX_KILLS}", command=self.stage_all_kills).grid(
            row=4, column=1, sticky="w", padx=(8, 8), pady=(8, 0)
        )
        ttk.Button(pilots, text="Discard pending", command=self.discard_pending_pilots).grid(
            row=4, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(pilots, text="Save pilot changes", command=self.save_pilot_changes).grid(
            row=4, column=4, sticky="e", pady=(8, 0)
        )

        parts = ttk.Frame(notebook, padding=12)
        notebook.add(parts, text="Parts inventory")
        parts.columnconfigure(0, weight=1)
        parts.rowconfigure(0, weight=1)
        part_columns = ("name", "id", "available", "equipped", "total")
        self.part_tree = ttk.Treeview(
            parts, columns=part_columns, show="headings", height=12, selectmode="browse"
        )
        self.part_tree.heading("name", text="Part")
        self.part_tree.heading("id", text="ID")
        self.part_tree.heading("available", text="Available")
        self.part_tree.heading("equipped", text="Equipped")
        self.part_tree.heading("total", text="Total owned")
        self.part_tree.column("name", width=270, minwidth=160, anchor="w")
        self.part_tree.column("id", width=60, minwidth=50, anchor="center", stretch=False)
        self.part_tree.column("available", width=90, minwidth=75, anchor="e", stretch=False)
        self.part_tree.column("equipped", width=90, minwidth=75, anchor="e", stretch=False)
        self.part_tree.column("total", width=100, minwidth=85, anchor="e", stretch=False)
        self.part_tree.grid(row=0, column=0, columnspan=5, sticky="nsew")
        part_scrollbar = ttk.Scrollbar(parts, orient="vertical", command=self.part_tree.yview)
        part_scrollbar.grid(row=0, column=5, sticky="ns")
        self.part_tree.configure(yscrollcommand=part_scrollbar.set)
        self.part_tree.bind("<<TreeviewSelect>>", self._part_selected)

        ttk.Label(parts, text="Selected total owned").grid(row=1, column=0, sticky="w", pady=(10, 0))
        part_validate = (self.register(self._validate_part_text), "%P")
        ttk.Entry(
            parts,
            textvariable=self.part_total_var,
            width=12,
            validate="key",
            validatecommand=part_validate,
        ).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ttk.Button(parts, text="Apply to selected", command=self.stage_selected_part).grid(
            row=1, column=2, sticky="w", pady=(10, 0)
        )
        ttk.Button(parts, text=f"Set all totals to {MAX_PARTS}", command=self.stage_all_parts).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(parts, text="Discard pending", command=self.discard_pending_parts).grid(
            row=2, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(parts, text="Save parts changes", command=self.save_parts_changes).grid(
            row=2, column=4, sticky="e", pady=(8, 0)
        )

        abilities = ttk.Frame(notebook, padding=12)
        notebook.add(abilities, text="Abilities inventory")
        abilities.columnconfigure(0, weight=1)
        abilities.rowconfigure(0, weight=1)
        ability_columns = ("name", "id", "available", "equipped", "total")
        self.ability_tree = ttk.Treeview(
            abilities, columns=ability_columns, show="headings", height=12, selectmode="browse"
        )
        self.ability_tree.heading("name", text="Ability")
        self.ability_tree.heading("id", text="ID")
        self.ability_tree.heading("available", text="Available")
        self.ability_tree.heading("equipped", text="Equipped")
        self.ability_tree.heading("total", text="Total owned")
        self.ability_tree.column("name", width=270, minwidth=160, anchor="w")
        self.ability_tree.column("id", width=60, minwidth=50, anchor="center", stretch=False)
        self.ability_tree.column("available", width=90, minwidth=75, anchor="e", stretch=False)
        self.ability_tree.column("equipped", width=90, minwidth=75, anchor="e", stretch=False)
        self.ability_tree.column("total", width=100, minwidth=85, anchor="e", stretch=False)
        self.ability_tree.grid(row=0, column=0, columnspan=5, sticky="nsew")
        ability_scrollbar = ttk.Scrollbar(
            abilities, orient="vertical", command=self.ability_tree.yview
        )
        ability_scrollbar.grid(row=0, column=5, sticky="ns")
        self.ability_tree.configure(yscrollcommand=ability_scrollbar.set)
        self.ability_tree.bind("<<TreeviewSelect>>", self._ability_selected)

        ttk.Label(abilities, text="Selected total owned").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        ability_validate = (self.register(self._validate_ability_text), "%P")
        ttk.Entry(
            abilities,
            textvariable=self.ability_total_var,
            width=12,
            validate="key",
            validatecommand=ability_validate,
        ).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ttk.Button(
            abilities, text="Apply to selected", command=self.stage_selected_ability
        ).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Button(
            abilities,
            text=f"Ensure {ABILITY_STOCK_TARGET} available",
            command=self.stage_all_abilities,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            abilities, text="Discard pending", command=self.discard_pending_abilities
        ).grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Button(
            abilities, text="Save ability changes", command=self.save_ability_changes
        ).grid(row=2, column=4, sticky="e", pady=(8, 0))

        weapons = ttk.Frame(notebook, padding=12)
        notebook.add(weapons, text="Weapons inventory")
        weapons.columnconfigure(0, weight=1)
        weapons.rowconfigure(0, weight=1)
        weapon_columns = ("name", "id", "available", "equipped", "total")
        self.weapon_tree = ttk.Treeview(
            weapons, columns=weapon_columns, show="headings", height=12, selectmode="browse"
        )
        self.weapon_tree.heading("name", text="Equippable weapon")
        self.weapon_tree.heading("id", text="ID")
        self.weapon_tree.heading("available", text="Available")
        self.weapon_tree.heading("equipped", text="Equipped")
        self.weapon_tree.heading("total", text="Total owned")
        self.weapon_tree.column("name", width=270, minwidth=160, anchor="w")
        self.weapon_tree.column("id", width=60, minwidth=50, anchor="center", stretch=False)
        self.weapon_tree.column("available", width=90, minwidth=75, anchor="e", stretch=False)
        self.weapon_tree.column("equipped", width=90, minwidth=75, anchor="e", stretch=False)
        self.weapon_tree.column("total", width=100, minwidth=85, anchor="e", stretch=False)
        self.weapon_tree.grid(row=0, column=0, columnspan=5, sticky="nsew")
        weapon_scrollbar = ttk.Scrollbar(
            weapons, orient="vertical", command=self.weapon_tree.yview
        )
        weapon_scrollbar.grid(row=0, column=5, sticky="ns")
        self.weapon_tree.configure(yscrollcommand=weapon_scrollbar.set)
        self.weapon_tree.bind("<<TreeviewSelect>>", self._weapon_selected)

        ttk.Label(weapons, text="Add-only target total").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        weapon_validate = (self.register(self._validate_weapon_text), "%P")
        ttk.Entry(
            weapons,
            textvariable=self.weapon_total_var,
            width=12,
            validate="key",
            validatecommand=weapon_validate,
        ).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ttk.Button(
            weapons, text="Apply to selected", command=self.stage_selected_weapon
        ).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Button(
            weapons,
            text=f"Add missing copies to {WEAPON_TARGET_COPIES}",
            command=self.stage_all_weapons,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            weapons, text="Discard pending", command=self.discard_pending_weapons
        ).grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Button(
            weapons, text="Save weapon additions", command=self.save_weapon_changes
        ).grid(row=2, column=4, sticky="e", pady=(8, 0))
        ttk.Button(weapons, text="Edit weapon stats…", command=self.open_weapon_editor).grid(
            row=3, column=0, sticky="w", pady=(14, 0))
        ttk.Label(weapons, text="Attack, range, EN cost and maximum ammo — edits the game archive.").grid(
            row=3, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=(14, 0))

        self.build_skill_progress()
        self.build_mech_skills()
        self._build_seishin_patch_tab()
        self.search_var.trace_add("write", self._search_changed)
        self.notebook.bind("<<NotebookTabChanged>>", self._search_changed)

        ttk.Separator(self).grid(row=7, column=0, columnspan=3, sticky="ew")
        ttk.Label(self, textvariable=self.status_var, wraplength=700).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )

    def open_weapon_editor(self) -> None:
        try:
            from weapon_editor.ui import open_editor
            open_editor(self.master)
        except ImportError as exc:
            messagebox.showerror('Weapon editor dependencies',
                'Use the packaged OGMD Save Editor.exe, or install the source requirements.\n\n'+str(exc), parent=self.master)

    def close_editor(self) -> None:
        window = getattr(self.master, 'weapon_editor_window', None)
        if window is not None and window.winfo_exists() and not window.request_close():
            return
        self.master.destroy()

    def _build_seishin_patch_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Seishin patch")
        tab.columnconfigure(1, weight=1)
        ttk.Label(
            tab,
            text="Experimental GLOBAL Seishin override",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(
            tab,
            text=(
                "OGMD does not store each pilot's Spirit/Seishin command IDs in the scenario save. "
                "These known EBOOT patch points override a command slot for every pilot while enabled."
            ),
            wraplength=850,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 14))
        ttk.Label(tab, text="PPU hash").grid(row=2, column=0, sticky="w")
        ttk.Entry(tab, textvariable=self.seishin_ppu_var, width=48).grid(
            row=2, column=1, columnspan=3, sticky="w", padx=(8, 0)
        )
        labels = ["Spirit 1", "Spirit 2", "Spirit 3", "Spirit 4", "Spirit 5", "Twin Spirit"]
        for i, label in enumerate(labels):
            row = 3 + i
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(tab, textvariable=self.seishin_vars[i], width=8).grid(
                row=row, column=1, sticky="w", padx=(8, 8), pady=3
            )
            ttk.Label(tab, text="hex ID 00–FF; blank = keep original").grid(
                row=row, column=2, columnspan=2, sticky="w", pady=3
            )
        row = 9
        ttk.Checkbutton(tab, text="SP cost 0", variable=self.seishin_zero_sp_var).grid(
            row=row, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Checkbutton(
            tab, text="Unlock all Spirit slots regardless of level", variable=self.seishin_unlock_all_var
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(tab, text="Save RPCS3 patch…", command=self.save_seishin_patch).grid(
            row=row + 1, column=0, sticky="w", pady=(14, 0)
        )
        ttk.Button(tab, text="Copy patch text", command=self.copy_seishin_patch).grid(
            row=row + 1, column=1, sticky="w", padx=(8, 0), pady=(14, 0)
        )
        ttk.Label(
            tab,
            text=(
                "This tab is intentionally not labeled per-pilot: the verified public patch locations are global. "
                "A true per-pilot Seishin editor requires the game's PilotData/EBOOT mapping, not PARMDAT.SAV."
            ),
            wraplength=850,
        ).grid(row=row + 2, column=0, columnspan=4, sticky="w", pady=(14, 0))

    def _make_seishin_patch_text(self) -> str | None:
        try:
            return build_patch(
                {i + 1: var.get() for i, var in enumerate(self.seishin_vars)},
                ppu_hash=self.seishin_ppu_var.get(),
                zero_sp=self.seishin_zero_sp_var.get(),
                unlock_all=self.seishin_unlock_all_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid Seishin patch", str(exc), parent=self.master)
            return None

    def save_seishin_patch(self) -> None:
        payload = self._make_seishin_patch_text()
        if payload is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.master,
            title="Save RPCS3 Seishin patch",
            defaultextension=".yml",
            initialfile="OGMD_Seishin_Override.yml",
            filetypes=[("YAML patch", "*.yml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(payload, encoding="utf-8", newline="\n")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.master)
            return
        self.status_var.set(f"Saved global Seishin RPCS3 patch: {path}")

    def copy_seishin_patch(self) -> None:
        payload = self._make_seishin_patch_text()
        if payload is None:
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(payload)
        self.status_var.set("Copied global Seishin RPCS3 patch text to the clipboard.")

    @staticmethod
    def _validate_funds_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 8

    @staticmethod
    def _validate_pp_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 4

    @staticmethod
    def _validate_kills_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 3

    @staticmethod
    def _validate_will_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 3

    @staticmethod
    def _validate_part_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 2

    @staticmethod
    def _validate_ability_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 5

    @staticmethod
    def _validate_weapon_text(value: str) -> bool:
        return value == "" or value.isascii() and value.isdigit() and len(value) <= 1

    def clear_search(self) -> None:
        self.search_var.set("")

    @staticmethod
    def _matches_search(query: str, *values: object) -> bool:
        return not query or any(query in str(value).casefold() for value in values)

    def _set_search_count(self, tab_index: int, shown: int, total: int) -> None:
        try:
            active_tab = self.notebook.index("current")
        except tk.TclError:
            return
        if active_tab == tab_index:
            self.search_result_var.set(f"{shown}/{total} shown")

    def _search_changed(self, *_args: object) -> None:
        try:
            active_tab = self.notebook.index("current")
        except tk.TclError:
            return
        if active_tab == 0:
            self._populate_pilots(tuple(self.pilots.values()))
        elif active_tab == 1:
            self._populate_parts(tuple(self.parts.values()))
        elif active_tab == 2:
            self._populate_abilities(tuple(self.abilities.values()))
        elif active_tab == 3:
            self._populate_weapons(tuple(self.weapons.values()))
        elif active_tab == 4:
            self.populate_skills()
        elif active_tab == 5:
            self.search_result_var.set("Completed-game count")
        elif active_tab == 6:
            self.populate_mechs()
        elif active_tab == 7:
            self.search_result_var.set("Global Seishin patch generator")

    @staticmethod
    def _restore_tree_selection(tree: ttk.Treeview, item_id: int) -> None:
        iid = str(item_id)
        if tree.exists(iid):
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)

    def find_saves(self) -> None:
        from discovery import discover_saves
        saves = discover_saves()
        if not saves:
            messagebox.showinfo("Find saves", "No supported saves found in the known RPCS3 folders. Use Browse to select a scenario-save folder.", parent=self.master)
            return
        dialog = tk.Toplevel(self.master)
        dialog.title("Choose a Moon Dwellers save")
        dialog.geometry("1080x390")
        dialog.transient(self.master)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text="Choose a scenario save. Reading it does not change any files.").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        tree = ttk.Treeview(dialog, columns=("scenario", "funds", "path"), show="headings", selectmode="browse")
        for name, label, width in [("scenario", "Scenario", 270), ("funds", "Funds", 90), ("path", "Save folder", 660)]:
            tree.heading(name, text=label)
            tree.column(name, width=width, stretch=name == "path")
        tree.grid(row=1, column=0, sticky="nsew", padx=12)
        for i, save in enumerate(saves):
            tree.insert("", "end", iid=str(i), values=(save.subtitle, f"{save.funds:,}", str(save.slot_path)))
        tree.selection_set("0")
        def choose(_event=None):
            selected = tree.selection()
            if selected:
                self.folder_var.set(str(saves[int(selected[0])].slot_path))
                dialog.destroy()
                self.load_selected()
        tree.bind("<Double-1>", choose)
        ttk.Button(dialog, text="Read selected save", command=choose).grid(row=2, column=0, padx=12, pady=12, sticky="e")
        dialog.grab_set()

    def browse(self) -> None:
        selected = filedialog.askdirectory(title="Select BLJS10335_OMI-SCN… save folder", mustexist=True)
        if selected:
            self.folder_var.set(selected)
            self.load_selected()

    def load_selected(self) -> None:
        try:
            initial_snapshot = snapshot_slot(self.folder_var.get().strip())
            info = load_save(self.folder_var.get().strip())
            pilots = load_pilots(info.slot_path)
            try:
                pilot_status, status_error = load_status(info.slot_path), None
            except SaveFormatError as exc:
                pilot_status, status_error = {}, str(exc)
            parts = load_parts(info.slot_path)
            abilities = load_abilities(info.slot_path)
            weapons = load_weapons(info.slot_path)
            skills = load_pilot_skills(info.slot_path)
            progress = load_progress(info.slot_path)
            mech_error = None
            try:
                mechs = load_mechs(info.slot_path)
            except SaveFormatError as exc:
                mechs, mech_error = (), exc
            if snapshot_slot(info.slot_path) != initial_snapshot:
                raise SaveFormatError("The save changed while reading. Read it again.")
        except (SaveFormatError, OSError) as exc:
            self.current_slot = None
            self.set_skill_progress()
            self.set_mechs()
            self.pilots.clear()
            self.pending_will.clear()
            self.pilot_will_var.set("")
            self.pending_status.clear()
            self.pilot_status.clear()
            self.pilot_status_error = None
            self.pending_pp.clear()
            self.pending_kills.clear()
            self.parts.clear()
            self.pending_parts.clear()
            self.abilities.clear()
            self.pending_abilities.clear()
            self.weapons.clear()
            self.pending_weapons.clear()
            self.title_var.set("Not loaded")
            self.funds_var.set("")
            self.total_funds_var.set("Not loaded")
            self.spent_funds_var.set("Not loaded")
            self.pilot_pp_var.set("")
            self.pilot_kills_var.set("")
            self.part_total_var.set("")
            self.ability_total_var.set("")
            self.weapon_total_var.set("")
            self._populate_pilots(())
            self._populate_parts(())
            self._populate_abilities(())
            self._populate_weapons(())
            self.status_var.set(f"Could not load save: {exc}")
            messagebox.showerror("Unsupported or invalid save", str(exc), parent=self.master)
            return
        self.set_skill_progress(skills, progress)
        self.set_mechs(mechs, mech_error)
        self.loaded_snapshot = initial_snapshot
        self.current_slot = info.slot_path
        self.folder_var.set(str(info.slot_path))
        self.title_var.set(info.subtitle or info.directory_name)
        self.funds_var.set(str(info.funds))
        self.total_funds_var.set(f"{info.total_funds:,}")
        self.spent_funds_var.set(f"{info.spent_funds:,}")
        self.pilots = {pilot.pilot_id: pilot for pilot in pilots}
        self.pilot_status = pilot_status
        self.pilot_status_error = status_error
        self.pending_pp.clear()
        self.pending_kills.clear()
        self.pending_will.clear()
        self.pending_status.clear()
        self.pilot_pp_var.set("")
        self.pilot_kills_var.set("")
        self.pilot_will_var.set("")
        self._populate_pilots(pilots)
        self.parts = {part.part_id: part for part in parts}
        self.pending_parts.clear()
        self.part_total_var.set("")
        self._populate_parts(parts)
        self.abilities = {ability.ability_id: ability for ability in abilities}
        self.pending_abilities.clear()
        self.ability_total_var.set("")
        self._populate_abilities(abilities)
        self.weapons = {weapon.weapon_id: weapon for weapon in weapons}
        self.pending_weapons.clear()
        self.weapon_total_var.set("")
        self._populate_weapons(weapons)
        self.status_var.set(
            f"Validated {info.directory_name}: {len(pilots)} recruited pilots, funds, "
            f"43 parts, 21 abilities, and {sum(w.total_owned for w in weapons)}/"
            f"{WEAPON_SLOT_COUNT} weapon slots used."
        )

    def _populate_pilots(self, pilots: tuple[PilotInfo, ...] | list[PilotInfo]) -> None:
        for item in self.pilot_tree.get_children():
            self.pilot_tree.delete(item)
        query = self.search_var.get().strip().casefold()
        shown = 0
        for pilot in pilots:
            pp = self.pending_pp.get(pilot.pilot_id, pilot.pp)
            kills = self.pending_kills.get(pilot.pilot_id, pilot.kills)
            will = self.pending_will.get(pilot.pilot_id, pilot.will)
            pp_suffix = " *" if pilot.pilot_id in self.pending_pp else ""
            kills_suffix = " *" if pilot.pilot_id in self.pending_kills else ""
            will_suffix = " *" if pilot.pilot_id in self.pending_will else ""
            status = self.pending_status.get(pilot.pilot_id)
            experience = status.experience if status else pilot.experience
            level = min(experience, 49000) // 500 + 1
            status_suffix = " *" if status else ""
            if not self._matches_search(
                query,
                pilot.name,
                pilot.pilot_id,
                f"0x{pilot.pilot_id:02X}",
                kills,
                experience,
                level,
                pp,
                will,
            ):
                continue
            self.pilot_tree.insert(
                "",
                "end",
                iid=str(pilot.pilot_id),
                values=(
                    pilot.name + status_suffix,
                    f"0x{pilot.pilot_id:02X}",
                    f"{kills}{kills_suffix}",
                    f"Lv {level} / {experience}{status_suffix}",
                    f"{will}{will_suffix}",
                    f"{pp}{pp_suffix}",
                ),
            )
            shown += 1
        self._set_search_count(0, shown, len(pilots))

    def _pilot_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.pilot_tree.selection()
        if not selected:
            self.pilot_pp_var.set("")
            self.pilot_kills_var.set("")
            self.pilot_will_var.set("")
            return
        pilot_id = int(selected[0])
        pilot = self.pilots[pilot_id]
        self.pilot_pp_var.set(str(self.pending_pp.get(pilot_id, pilot.pp)))
        self.pilot_kills_var.set(str(self.pending_kills.get(pilot_id, pilot.kills)))
        self.pilot_will_var.set(str(self.pending_will.get(pilot_id, pilot.will)))

    def stage_selected_pp(self) -> None:
        selected = self.pilot_tree.selection()
        if not selected:
            messagebox.showerror("No pilot selected", "Select a pilot first.", parent=self.master)
            return
        try:
            pp = int(self.pilot_pp_var.get())
        except ValueError:
            messagebox.showerror("Invalid PP", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= pp <= MAX_PP:
            messagebox.showerror("Invalid PP", f"Enter a value from 0 through {MAX_PP:,}.", parent=self.master)
            return
        pilot_id = int(selected[0])
        if pp == self.pilots[pilot_id].pp:
            self.pending_pp.pop(pilot_id, None)
        else:
            self.pending_pp[pilot_id] = pp
        self._populate_pilots(tuple(self.pilots.values()))
        self._restore_tree_selection(self.pilot_tree, pilot_id)
        self.status_var.set(
            f"{len(self.pending_pp)} PP, {len(self.pending_kills)} kill-count, and "
            f"{len(self.pending_will)} Will change(s) pending. Nothing has been written yet."
        )

    def stage_selected_kills(self) -> None:
        selected = self.pilot_tree.selection()
        if not selected:
            messagebox.showerror("No pilot selected", "Select a pilot first.", parent=self.master)
            return
        try:
            kills = int(self.pilot_kills_var.get())
        except ValueError:
            messagebox.showerror("Invalid kills", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= kills <= MAX_KILLS:
            messagebox.showerror(
                "Invalid kills", f"Enter a value from 0 through {MAX_KILLS}.", parent=self.master
            )
            return
        pilot_id = int(selected[0])
        if kills == self.pilots[pilot_id].kills:
            self.pending_kills.pop(pilot_id, None)
        else:
            self.pending_kills[pilot_id] = kills
        self._populate_pilots(tuple(self.pilots.values()))
        self._restore_tree_selection(self.pilot_tree, pilot_id)
        self.status_var.set(
            f"{len(self.pending_pp)} PP, {len(self.pending_kills)} kill-count, and "
            f"{len(self.pending_will)} Will change(s) pending. Nothing has been written yet."
        )

    def stage_selected_will(self) -> None:
        selected = self.pilot_tree.selection()
        if not selected:
            messagebox.showerror("No pilot selected", "Select a pilot first.", parent=self.master)
            return
        try:
            will = int(self.pilot_will_var.get())
        except ValueError:
            messagebox.showerror("Invalid Will", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= will <= MAX_WILL:
            messagebox.showerror(
                "Invalid Will", f"Enter a value from 0 through {MAX_WILL}.", parent=self.master
            )
            return
        pilot_id = int(selected[0])
        if will == self.pilots[pilot_id].will:
            self.pending_will.pop(pilot_id, None)
        else:
            self.pending_will[pilot_id] = will
        self._populate_pilots(tuple(self.pilots.values()))
        self._restore_tree_selection(self.pilot_tree, pilot_id)
        self.status_var.set(
            f"{len(self.pending_pp)} PP, {len(self.pending_kills)} kill-count, and "
            f"{len(self.pending_will)} Will change(s) pending. Nothing has been written yet."
        )

    def stage_all_pp(self) -> None:
        if not self.pilots:
            messagebox.showerror("No save loaded", "Read and validate a save first.", parent=self.master)
            return
        self.pending_pp = {
            pilot_id: MAX_PP for pilot_id, pilot in self.pilots.items() if pilot.pp != MAX_PP
        }
        self._populate_pilots(tuple(self.pilots.values()))
        self.status_var.set(
            f"Staged {len(self.pending_pp)} pilots at {MAX_PP:,} PP; "
            f"{len(self.pending_kills)} kill-count and {len(self.pending_will)} Will change(s) remain staged."
        )

    def stage_all_kills(self) -> None:
        if not self.pilots:
            messagebox.showerror("No save loaded", "Read and validate a save first.", parent=self.master)
            return
        self.pending_kills = {
            pilot_id: MAX_KILLS
            for pilot_id, pilot in self.pilots.items()
            if pilot.kills != MAX_KILLS
        }
        self._populate_pilots(tuple(self.pilots.values()))
        self.status_var.set(
            f"Staged {len(self.pending_kills)} pilots at {MAX_KILLS} kills; "
            f"{len(self.pending_pp)} PP and {len(self.pending_will)} Will change(s) remain staged."
        )

    def discard_pending_pilots(self) -> None:
        self.pending_pp.clear()
        self.pending_kills.clear()
        self.pending_will.clear()
        self.pending_status.clear()
        self.pilot_pp_var.set("")
        self.pilot_kills_var.set("")
        self.pilot_will_var.set("")
        self._populate_pilots(tuple(self.pilots.values()))
        self.status_var.set("Discarded pending pilot changes. The save was not modified.")

    def save_pilot_changes(self) -> None:
        if self.current_slot is None or not (self.pending_pp or self.pending_kills or self.pending_will or self.pending_status):
            messagebox.showinfo(
                "No pilot changes", "Stage one or more pilot changes first.", parent=self.master
            )
            return
        try:
            on_disk = load_pilots(self.current_slot)
        except SaveFormatError as exc:
            messagebox.showerror("Save changed on disk", str(exc), parent=self.master)
            return
        actual = {pilot.pilot_id: pilot for pilot in on_disk}
        if actual != self.pilots:
            messagebox.showerror(
                "Save changed on disk",
                "Pilot records changed after the save was loaded. Read the save again before editing.",
                parent=self.master,
            )
            return
        if not messagebox.askyesno(
            "Write pilot changes?",
            f"Update PP for {len(self.pending_pp)}, kill counts for {len(self.pending_kills)}, and "
            f"Will for {len(self.pending_will)}, and status for {len(self.pending_status)} pilot(s)?\n\n"
            + self.status_review() + "\n\n"
            "Exit the game before writing. RPCS3 itself may remain open.\n"
            "A full timestamped backup will be created first.",
            parent=self.master,
        ):
            return
        try:
            result = write_pilot_stats(
                self.current_slot,
                pp_updates=self.pending_pp,
                kill_updates=self.pending_kills,
                will_updates=self.pending_will,
                status_updates=self.pending_status,
                expected_snapshot=self.loaded_snapshot,
            )
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Write failed", str(exc), parent=self.master)
            self.status_var.set(f"Pilot write failed: {exc}")
            return
        self.loaded_snapshot = result.snapshot
        self.pilots = {pilot.pilot_id: pilot for pilot in result.pilots}
        pp_count = len(self.pending_pp)
        kills_count = len(self.pending_kills)
        will_count = len(self.pending_will)
        status_count = len(self.pending_status)
        if status_count:
            self.pilot_status = load_status(self.current_slot)
        self.skill_pilots = {pid: replace(item, pilot=self.pilots[pid])
                             for pid, item in self.skill_pilots.items()}
        self.populate_skills()
        self.skill_selected()
        self.pending_pp.clear()
        self.pending_kills.clear()
        self.pending_will.clear()
        self.pending_status.clear()
        self.pilot_pp_var.set("")
        self.pilot_kills_var.set("")
        self.pilot_will_var.set("")
        self._populate_pilots(result.pilots)
        self.status_var.set(
            f"Saved and verified {pp_count} PP, {kills_count} kill-count, and {will_count} Will and {status_count} status change(s). "
            f"Backup: {result.backup_path}"
        )
        messagebox.showinfo(
            "Pilots updated",
            f"Updated {pp_count} PP, {kills_count} kill-count, and {will_count} Will and {status_count} status record(s).\n\n"
            f"Backup:\n{result.backup_path}",
            parent=self.master,
        )

    def _populate_parts(self, parts: tuple[PartInfo, ...] | list[PartInfo]) -> None:
        for item in self.part_tree.get_children():
            self.part_tree.delete(item)
        query = self.search_var.get().strip().casefold()
        shown = 0
        for part in parts:
            pending = self.pending_parts.get(part.part_id)
            if pending is not None:
                equipped = part.equipped
                available: str | int = pending - equipped
                total: str | int = f"{pending} *"
            elif part.locked:
                available = "—"
                equipped = 0
                total = "Locked"
            else:
                available = part.available if part.available is not None else 0
                equipped = part.equipped
                total = part.total_owned if part.total_owned is not None else 0
            if not self._matches_search(
                query,
                part.name,
                part.part_id,
                f"0x{part.part_id:02X}",
                available,
                equipped,
                total,
                "locked" if part.locked else "",
            ):
                continue
            self.part_tree.insert(
                "",
                "end",
                iid=str(part.part_id),
                values=(part.name, part.part_id, available, equipped, total),
            )
            shown += 1
        self._set_search_count(1, shown, len(parts))

    def _part_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.part_tree.selection()
        if not selected:
            self.part_total_var.set("")
            return
        part_id = int(selected[0])
        part = self.parts[part_id]
        if part_id in self.pending_parts:
            total = self.pending_parts[part_id]
        elif part.locked:
            total = 0
        else:
            total = part.total_owned or 0
        self.part_total_var.set(str(total))

    def stage_selected_part(self) -> None:
        selected = self.part_tree.selection()
        if not selected:
            messagebox.showerror("No part selected", "Select a part first.", parent=self.master)
            return
        try:
            total = int(self.part_total_var.get())
        except ValueError:
            messagebox.showerror("Invalid total", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= total <= MAX_PARTS:
            messagebox.showerror(
                "Invalid total", f"Enter a value from 0 through {MAX_PARTS}.", parent=self.master
            )
            return
        part_id = int(selected[0])
        part = self.parts[part_id]
        if total < part.equipped:
            messagebox.showerror(
                "Total below equipped count",
                f"{part.name} has {part.equipped} equipped. Set its total to at least {part.equipped}.",
                parent=self.master,
            )
            return
        if not part.locked and total == part.total_owned:
            self.pending_parts.pop(part_id, None)
        else:
            self.pending_parts[part_id] = total
        self._populate_parts(tuple(self.parts.values()))
        self._restore_tree_selection(self.part_tree, part_id)
        self.status_var.set(
            f"{len(self.pending_parts)} pending parts change(s). Nothing has been written yet."
        )

    def stage_all_parts(self) -> None:
        if not self.parts:
            messagebox.showerror("No save loaded", "Read and validate a save first.", parent=self.master)
            return
        self.pending_parts = {
            part_id: MAX_PARTS
            for part_id, part in self.parts.items()
            if part.locked or part.total_owned != MAX_PARTS
        }
        self._populate_parts(tuple(self.parts.values()))
        self.status_var.set(
            f"Staged {len(self.pending_parts)} part totals at {MAX_PARTS}. "
            "Equipped counts will be preserved; nothing has been written yet."
        )

    def discard_pending_parts(self) -> None:
        self.pending_parts.clear()
        self.part_total_var.set("")
        self._populate_parts(tuple(self.parts.values()))
        self.status_var.set("Discarded pending parts changes. The save was not modified.")

    def save_parts_changes(self) -> None:
        if self.current_slot is None or not self.pending_parts:
            messagebox.showinfo("No parts changes", "Stage one or more parts changes first.", parent=self.master)
            return
        try:
            on_disk = load_parts(self.current_slot)
        except SaveFormatError as exc:
            messagebox.showerror("Save changed on disk", str(exc), parent=self.master)
            return
        actual = {part.part_id: part for part in on_disk}
        if actual != self.parts:
            messagebox.showerror(
                "Save changed on disk",
                "Parts records changed after the save was loaded. Read the save again before editing.",
                parent=self.master,
            )
            return
        unlocked_count = sum(self.parts[part_id].locked for part_id in self.pending_parts)
        if not messagebox.askyesno(
            "Write parts changes?",
            f"Update {len(self.pending_parts)} parts record(s)?\n"
            f"Locked parts to unlock: {unlocked_count}\n\n"
            "Parts already equipped on units remain accounted for and attached.\n"
            "A full timestamped backup will be created first.",
            parent=self.master,
        ):
            return
        try:
            result = write_parts(self.current_slot, self.pending_parts, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Write failed", str(exc), parent=self.master)
            self.status_var.set(f"Parts write failed: {exc}")
            return
        changed_count = len(self.pending_parts)
        self.loaded_snapshot = result.snapshot
        self.parts = {part.part_id: part for part in result.parts}
        self.pending_parts.clear()
        self.part_total_var.set("")
        self._populate_parts(result.parts)
        self.status_var.set(
            f"Saved and verified {changed_count} parts change(s). Backup: {result.backup_path}"
        )
        messagebox.showinfo(
            "Parts updated",
            f"Updated {changed_count} parts record(s).\n\nBackup:\n{result.backup_path}",
            parent=self.master,
        )

    def _populate_abilities(
        self, abilities: tuple[AbilityInfo, ...] | list[AbilityInfo]
    ) -> None:
        for item in self.ability_tree.get_children():
            self.ability_tree.delete(item)
        query = self.search_var.get().strip().casefold()
        shown = 0
        for ability in abilities:
            if ability.ability_id in self.pending_abilities:
                total_owned = self.pending_abilities[ability.ability_id]
                available: str | int = total_owned - ability.equipped
                total: str | int = f"{total_owned} *"
            else:
                available = "—" if ability.locked else ability.available
                total = "Locked" if ability.locked else ability.total_owned
            if not self._matches_search(
                query,
                ability.name,
                ability.ability_id,
                f"0x{ability.ability_id:02X}",
                available,
                ability.equipped,
                total,
            ):
                continue
            self.ability_tree.insert(
                "",
                "end",
                iid=str(ability.ability_id),
                values=(
                    ability.name,
                    ability.ability_id,
                    available,
                    ability.equipped,
                    total,
                ),
            )
            shown += 1
        self._set_search_count(2, shown, len(abilities))

    def _ability_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.ability_tree.selection()
        if not selected:
            self.ability_total_var.set("")
            return
        ability_id = int(selected[0])
        ability = self.abilities[ability_id]
        total = self.pending_abilities.get(ability_id, ability.total_owned)
        self.ability_total_var.set(str(total))

    def stage_selected_ability(self) -> None:
        selected = self.ability_tree.selection()
        if not selected:
            messagebox.showerror(
                "No ability selected", "Select an ability first.", parent=self.master
            )
            return
        try:
            total_owned = int(self.ability_total_var.get())
        except ValueError:
            messagebox.showerror("Invalid total", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= total_owned <= MAX_ABILITIES:
            messagebox.showerror(
                "Invalid total",
                f"Enter a value from 0 through {MAX_ABILITIES}.",
                parent=self.master,
            )
            return
        ability_id = int(selected[0])
        ability = self.abilities[ability_id]
        if total_owned < ability.equipped:
            messagebox.showerror(
                "Total below equipped count",
                f"{ability.name} has {ability.equipped} equipped. "
                f"Set its total to at least {ability.equipped}.",
                parent=self.master,
            )
            return
        if total_owned == ability.total_owned:
            self.pending_abilities.pop(ability_id, None)
        else:
            self.pending_abilities[ability_id] = total_owned
        self._populate_abilities(tuple(self.abilities.values()))
        self._restore_tree_selection(self.ability_tree, ability_id)
        self.status_var.set(
            f"{len(self.pending_abilities)} pending ability change(s). Nothing has been written yet."
        )

    def stage_all_abilities(self) -> None:
        if not self.abilities:
            messagebox.showerror(
                "No save loaded", "Read and validate a save first.", parent=self.master
            )
            return
        pending: dict[int, int] = {}
        for ability_id, ability in self.abilities.items():
            if ability.available >= ABILITY_STOCK_TARGET:
                continue
            target_total = ability.equipped + ABILITY_STOCK_TARGET
            if target_total > MAX_ABILITIES:
                messagebox.showerror(
                    "Ability counter capacity exceeded",
                    f"{ability.name} cannot reach {ABILITY_STOCK_TARGET} available copies "
                    "without exceeding the save's signed 16-bit total counter.",
                    parent=self.master,
                )
                return
            pending[ability_id] = target_total
        self.pending_abilities = pending
        self._populate_abilities(tuple(self.abilities.values()))
        self.status_var.set(
            f"Staged {len(self.pending_abilities)} ability type(s) with at least "
            f"{ABILITY_STOCK_TARGET} available. Equipped counts will be preserved; "
            "nothing has been written yet."
        )

    def discard_pending_abilities(self) -> None:
        self.pending_abilities.clear()
        self.ability_total_var.set("")
        self._populate_abilities(tuple(self.abilities.values()))
        self.status_var.set("Discarded pending ability changes. The save was not modified.")

    def save_ability_changes(self) -> None:
        if self.current_slot is None or not self.pending_abilities:
            messagebox.showinfo(
                "No ability changes",
                "Stage one or more ability changes first.",
                parent=self.master,
            )
            return
        try:
            on_disk = load_abilities(self.current_slot)
        except SaveFormatError as exc:
            messagebox.showerror("Save changed on disk", str(exc), parent=self.master)
            return
        actual = {ability.ability_id: ability for ability in on_disk}
        if actual != self.abilities:
            messagebox.showerror(
                "Save changed on disk",
                "Ability records changed after the save was loaded. Read the save again before editing.",
                parent=self.master,
            )
            return
        if not messagebox.askyesno(
            "Write ability changes?",
            f"Update {len(self.pending_abilities)} ability inventory record(s)?\n\n"
            "Abilities already equipped remain accounted for and attached.\n"
            "Pilot learned skills, stats, and slots are not changed.\n"
            "A full timestamped backup will be created first.",
            parent=self.master,
        ):
            return
        try:
            result = write_abilities(self.current_slot, self.pending_abilities, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Write failed", str(exc), parent=self.master)
            self.status_var.set(f"Ability write failed: {exc}")
            return
        changed_count = len(self.pending_abilities)
        self.loaded_snapshot = result.snapshot
        self.abilities = {ability.ability_id: ability for ability in result.abilities}
        self.pending_abilities.clear()
        self.ability_total_var.set("")
        self._populate_abilities(result.abilities)
        self.status_var.set(
            f"Saved and verified {changed_count} ability change(s). Backup: {result.backup_path}"
        )
        messagebox.showinfo(
            "Abilities updated",
            f"Updated {changed_count} ability inventory record(s).\n\n"
            f"Backup:\n{result.backup_path}",
            parent=self.master,
        )

    def _populate_weapons(self, weapons: tuple[WeaponInfo, ...] | list[WeaponInfo]) -> None:
        for item in self.weapon_tree.get_children():
            self.weapon_tree.delete(item)
        query = self.search_var.get().strip().casefold()
        shown = 0
        for weapon in weapons:
            if weapon.weapon_id in self.pending_weapons:
                total_owned = self.pending_weapons[weapon.weapon_id]
                available: str | int = weapon.available + total_owned - weapon.total_owned
                total: str | int = f"{total_owned} *"
            else:
                available = weapon.available
                total = weapon.total_owned
            if not self._matches_search(
                query,
                weapon.name,
                weapon.weapon_id,
                f"0x{weapon.weapon_id:02X}",
                available,
                weapon.equipped,
                total,
            ):
                continue
            self.weapon_tree.insert(
                "",
                "end",
                iid=str(weapon.weapon_id),
                values=(weapon.name, weapon.weapon_id, available, weapon.equipped, total),
            )
            shown += 1
        self._set_search_count(3, shown, len(weapons))

    def _weapon_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.weapon_tree.selection()
        if not selected:
            self.weapon_total_var.set("")
            return
        weapon_id = int(selected[0])
        weapon = self.weapons[weapon_id]
        target = self.pending_weapons.get(weapon_id, weapon.total_owned)
        self.weapon_total_var.set(str(target))

    def stage_selected_weapon(self) -> None:
        selected = self.weapon_tree.selection()
        if not selected:
            messagebox.showerror(
                "No weapon selected", "Select an equippable weapon first.", parent=self.master
            )
            return
        try:
            target = int(self.weapon_total_var.get())
        except ValueError:
            messagebox.showerror("Invalid target", "Enter a whole number.", parent=self.master)
            return
        weapon_id = int(selected[0])
        weapon = self.weapons[weapon_id]
        if target == weapon.total_owned:
            self.pending_weapons.pop(weapon_id, None)
        elif target < weapon.total_owned:
            messagebox.showerror(
                "Weapon removal is disabled",
                f"{weapon.name} already has {weapon.total_owned} copies. "
                "This editor only adds copies so equipped and upgraded weapons cannot be damaged.",
                parent=self.master,
            )
            return
        elif target > WEAPON_TARGET_COPIES:
            messagebox.showerror(
                "Unsupported target",
                f"Safe weapon additions are limited to {WEAPON_TARGET_COPIES} copies per type.",
                parent=self.master,
            )
            return
        else:
            self.pending_weapons[weapon_id] = target
        self._populate_weapons(tuple(self.weapons.values()))
        self._restore_tree_selection(self.weapon_tree, weapon_id)
        additions = sum(
            target_total - self.weapons[pending_id].total_owned
            for pending_id, target_total in self.pending_weapons.items()
        )
        self.status_var.set(
            f"Staged {additions} new weapon copy/copies. Nothing has been written yet."
        )

    def stage_all_weapons(self) -> None:
        if not self.weapons:
            messagebox.showerror(
                "No save loaded", "Read and validate a save first.", parent=self.master
            )
            return
        self.pending_weapons = {
            weapon_id: WEAPON_TARGET_COPIES
            for weapon_id, weapon in self.weapons.items()
            if weapon.total_owned < WEAPON_TARGET_COPIES
        }
        self._populate_weapons(tuple(self.weapons.values()))
        additions = sum(
            target - self.weapons[weapon_id].total_owned
            for weapon_id, target in self.pending_weapons.items()
        )
        self.status_var.set(
            f"Staged {additions} new copies across {len(self.pending_weapons)} weapon types. "
            "Existing copies remain untouched; nothing has been written yet."
        )

    def discard_pending_weapons(self) -> None:
        self.pending_weapons.clear()
        self.weapon_total_var.set("")
        self._populate_weapons(tuple(self.weapons.values()))
        self.status_var.set("Discarded pending weapon additions. The save was not modified.")

    def save_weapon_changes(self) -> None:
        if self.current_slot is None or not self.pending_weapons:
            messagebox.showinfo(
                "No weapon additions",
                "Stage one or more weapon additions first.",
                parent=self.master,
            )
            return
        try:
            on_disk = load_weapons(self.current_slot)
        except SaveFormatError as exc:
            messagebox.showerror("Save changed on disk", str(exc), parent=self.master)
            return
        actual = {weapon.weapon_id: weapon for weapon in on_disk}
        if actual != self.weapons:
            messagebox.showerror(
                "Save changed on disk",
                "Weapon records changed after the save was loaded. Read the save again before editing.",
                parent=self.master,
            )
            return
        additions = sum(
            target - self.weapons[weapon_id].total_owned
            for weapon_id, target in self.pending_weapons.items()
        )
        if not messagebox.askyesno(
            "Add weapon copies?",
            f"Add {additions} unequipped, level-0 weapon copy/copies across "
            f"{len(self.pending_weapons)} type(s)?\n\n"
            f"Weapon slots: {sum(w.total_owned for w in self.weapons.values())} → "
            f"{sum(w.total_owned for w in self.weapons.values()) + additions} of "
            f"{WEAPON_SLOT_COUNT}.\n\n"
            "Every existing weapon record, upgrade level, and equipped flag remains untouched.\n"
            "Weapon removal and modification are disabled.\n"
            "A full timestamped backup will be created first.",
            parent=self.master,
        ):
            return
        try:
            result = write_weapon_totals(self.current_slot, self.pending_weapons, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Write failed", str(exc), parent=self.master)
            self.status_var.set(f"Weapon write failed: {exc}")
            return
        changed_types = len(self.pending_weapons)
        self.loaded_snapshot = result.snapshot
        self.weapons = {weapon.weapon_id: weapon for weapon in result.weapons}
        self.pending_weapons.clear()
        self.weapon_total_var.set("")
        self._populate_weapons(result.weapons)
        self.status_var.set(
            f"Added and verified {additions} weapon copy/copies across {changed_types} type(s). "
            f"Backup: {result.backup_path}"
        )
        messagebox.showinfo(
            "Weapons added",
            f"Added {additions} weapon copy/copies.\n\nBackup:\n{result.backup_path}",
            parent=self.master,
        )

    def save_funds(self) -> None:
        if self.current_slot is None:
            messagebox.showerror("No save loaded", "Read and validate a save first.", parent=self.master)
            return
        try:
            funds = int(self.funds_var.get())
        except ValueError:
            messagebox.showerror("Invalid funds", "Enter a whole number.", parent=self.master)
            return
        if not 0 <= funds <= MAX_FUNDS:
            messagebox.showerror(
                "Invalid funds", f"Enter a value from 0 through {MAX_FUNDS:,}.", parent=self.master
            )
            return
        try:
            old = load_save(self.current_slot)
        except SaveFormatError as exc:
            messagebox.showerror("Save changed on disk", str(exc), parent=self.master)
            return
        if funds == old.funds:
            self.status_var.set("No changes to save.")
            return
        if not messagebox.askyesno(
            "Write edited save?",
            f"Change funds from {old.funds:,} to {funds:,}?\n\n"
            f"Funds-earned total: {old.total_funds:,} → {old.total_funds + funds - old.funds:,}\n"
            f"Historical spending remains {old.spent_funds:,}.\n\n"
            "A full timestamped backup will be created first.",
            parent=self.master,
        ):
            return
        try:
            result = write_funds(self.current_slot, funds, expected_snapshot=self.loaded_snapshot)
        except (SaveFormatError, OSError) as exc:
            messagebox.showerror("Write failed", str(exc), parent=self.master)
            self.status_var.set(f"Write failed: {exc}")
            return
        self.loaded_snapshot = result.snapshot
        self.funds_var.set(str(result.save.funds))
        self.total_funds_var.set(f"{result.save.total_funds:,}")
        self.spent_funds_var.set(f"{result.save.spent_funds:,}")
        self.status_var.set(f"Saved and verified. Backup: {result.backup_path}")
        messagebox.showinfo(
            "Save updated",
            f"Funds are now {result.save.funds:,}.\n\nBackup:\n{result.backup_path}",
            parent=self.master,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OG Moon Dwellers RPCS3 scenario-save editor")
    parser.add_argument("slot", nargs="?", help="Optional scenario-save folder to open")
    parser.add_argument("--inspect", action="store_true", help="Print validated save information and exit")
    parser.add_argument('--inspect-weapons', metavar='ARCHIVE', help='Validate weapon definitions read-only and exit')
    parser.add_argument('--weapon-report', metavar='JSON', help='Write the read-only weapon inspection report')
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.inspect_weapons:
        from dataclasses import asdict
        import json
        from weapon_editor.weapon_patch import Session
        session = None
        try:
            session = Session(args.inspect_weapons)
            report = dict(archive=str(session.target), snapshot=session.original,
                count=len(session.weapons), weapons={key:asdict(w) for key,w in session.weapons.items()})
            if args.weapon_report:
                destination = Path(args.weapon_report).resolve()
                if destination.exists():
                    raise ValueError('Choose a new report filename; existing files are never overwritten.')
                with destination.open('x', encoding='utf8') as output:
                    json.dump(report, output, indent=2, ensure_ascii=False)
            if sys.stdout:
                print(f'Validated {len(session.weapons)} weapon definitions.')
            return 0
        except Exception as exc:
            if sys.stderr:
                print(str(exc), file=sys.stderr)
            return 1
        finally:
            if session:
                session.close()
    if args.inspect:
        if not args.slot:
            print("--inspect requires a scenario-save folder", file=sys.stderr)
            return 2
        try:
            info = load_save(args.slot)
            pilots = load_pilots(args.slot)
            parts = load_parts(args.slot)
            abilities = load_abilities(args.slot)
            weapons = load_weapons(args.slot)
            skills = load_pilot_skills(args.slot)
            progress = load_progress(args.slot)
        except SaveFormatError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Folder:   {info.slot_path}")
        print(f"Scenario: {info.subtitle}")
        print(f"Funds:    {info.funds}")
        print(f"Earned:   {info.total_funds}")
        print(f"Spent:    {info.spent_funds}")
        print(f"Pilots:   {len(pilots)} recruited")
        print(f"Skills:   {len(skills)} pilots, six slots each")
        print(f"Completed games: {progress.completed_games}")
        try:
            mechs = load_mechs(args.slot)
            print(f"Mechs:    {len(mechs)} saved forms; three Ability slots and built-in enable switches")
        except SaveFormatError as exc:
            print(f"Mechs:    unavailable ({exc})")
        print(f"Parts:    {sum(not part.locked for part in parts)} unlocked, {sum(part.locked for part in parts)} locked")
        print(f"Abilities: {len(abilities)} inventory records")
        print(f"Weapons:  {sum(weapon.total_owned for weapon in weapons)} copies across {len(weapons)} types")
        return 0

    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    from discovery import discover_saves
    found = [] if args.slot else discover_saves()
    SaveEditor(root, args.slot or (str(found[0].slot_path) if found else ""))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
