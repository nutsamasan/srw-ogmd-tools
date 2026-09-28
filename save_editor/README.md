# Moon Dwellers RPCS3 Save Editor 1.6

Open **OGMD Save Editor.exe**. The source version also runs with `python save_editor.py` or `launch_save_editor.cmd` (Python 3.10+ with Tkinter). Save editing uses the standard library; source users need `pip install -r requirements.txt` for native weapon archive editing. The executable includes these dependencies.

The editor opens the newest scenario save found in the configured RPCS3 location. Check the displayed folder and scenario. Use **Find saves…** to choose another slot, or **Browse…** to select a folder directly. You can edit the search locations in `locations.json`.

## Editing

1. Exit/stop the game before writing. RPCS3 itself may stay open.
2. Read the normal scenario save you want to edit.
3. Enter funds and press **Save funds**, or stage changes in an inventory/pilot tab and press that tab's **Save … changes** button. An asterisk marks staged edits. Each tab saves separately.
4. Review the displayed confirmation, then save. A complete timestamped slot backup is created automatically.
5. Start the game and use its normal **Load** menu to load the edited slot. An emulator savestate or a different Continue/system slot can retain the old values.

Search current tab filters names, IDs and displayed values. Filtering preserves staged changes. **Read save** reloads the slot and clears staged edits.

Pilot names include your current script-editor corrections, such as Irm, Eun, Duvan, Raj, Lune and Almara.

| Feature | Behavior |
| --- | --- |
| Funds | 0–99,999,999; shifts total earned by the same delta, preserving historical spending |
| Pilots | PP, kills, Will, level/EXP, six combat stats and four terrain ratings; scans all 256 records |
| Pilot skills | Edit all six slots, remove skills, add learned levels, and drag rows to change the in-game display order; searchable by pilot or skill name |
| Completed games | 0–99 completed games in the selected scenario save; 0 means never completed |
| Mech skills | Edit three equipped Ability slots; enable/disable each form's existing built-in abilities |
| Parts | 43 types; totals up to 99, including unlocking previously unavailable parts |
| Abilities | 21 types; totals up to 32,767; bulk button ensures 99 available |
| Replacement weapons | 53 types including the four Moon Dwellers additions; adds up to four copies per type |
| Weapon stats | Base attack, minimum/maximum range, EN cost and maximum ammo for 855 built-in/equippable weapon definitions; edits the game archive |

Inventory-total edits preserve equipped part/ability counts. The Mech skills tab explicitly changes equipped Abilities and adjusts available stock without changing total ownership. New weapon copies are unequipped with zero upgrades. Existing weapon copies, upgrades and equipped flags are preserved. Pilot recruitment, mech upgrades, scenario-clear flags and system saves are preserved. EXP and personal stats change only when staged in Edit status.

In **Pilot skills**, select a pilot, choose the skills, then **Apply to selected pilot** and **Save skill changes**. You can also drag the **↕** handle beside a skill up or down to rearrange the order exactly as it will appear in the game's **Acquired Special Skills** list. A drag is staged automatically; it does not touch the save until **Save skill changes** is pressed. Alt+↑ / Alt+↓ on the focused handle provides the same reorder action from the keyboard.

**Training +** is the number of learned levels added to natural progression. The adjacent label shows the natural level now and the allowed training bonus. For example, Calvina's natural Potential 6 accepts +3 for level 9. Reordering preserves the pilot's effective skill levels and future natural growth. If a natural skill has already finished growing, the editor can freeze that completed level into training at the new slot. If moving a still-growing natural skill would change its future progression, the move is blocked instead of silently altering the pilot. A newly inserted leveled skill needs at least 1. Skills without levels retain a 0/1 storage value; their ID enables the skill. Duplicate skills and placeholder IDs cannot be added.

In **Completed games**, enter how many games have been completed and press **Save completed-game count**. On an ordinary scenario save, count 2 corresponds to the third playthrough. This changes the scenario-save counter; it does not finish a mission, create clear data, modify system-wide unlock flags, or recalculate existing carryover rewards. Existing recognized lap text in PARAM.SFO is synchronized. If that label is absent (as in the current English patch), PARAM.SFO is preserved.

In **Mech skills**, select a saved mech/form, choose its three equipped Abilities and check/uncheck its existing built-in skills. Press **Apply to selected mech**, then **Save mech changes**. Repeated equipped Abilities are allowed. Equipping consumes available stock; removing one returns it. If you need more stock, save an increased total in **Abilities inventory** first. You can stage transfers between mechs before saving the batch. Linked forms shown under **Shared equipment** are updated together and count as one equipment set; pilot equipment is preserved. Built-in switches apply only to the selected form.

**Built-in skill IDs and effects are fixed in UnitData.** The save contains their enable switches, so this tab can enable/disable existing regeneration, barriers and other built-ins, but cannot add or replace them. Empty built-in slots are disabled. Names follow the bundled native tables; custom UnitData mods may use different names/assignments. Replacing a built-in skill requires a separate game-data patch. Some saved forms are inactive/reserved in the current story; listing them does not recruit or unlock them.



## Version 1.6: weapon stats

1. Open **Weapons inventory → Edit weapon stats…**. A loaded save is not required.
2. Select the installed `Logic.psarc.sdat` and press **Read weapon data**. The editor suggests the archive in your configured RPCS3 installation. An extracted `Logic.psarc` also works; ISO files and PS4 archives do not.
3. Search by weapon or mech name. Choose the exact mech and slot when a name appears more than once. Double-click a row or press **Edit selected…**.
4. Enter base attack, minimum/maximum range, EN cost and maximum ammo, then **Stage these stats**. Staging does not write the archive.
5. Press **Review and write weapon stats…**, inspect the target and before/after values, exit the game, check the confirmation box and press **Write weapon stats**. RPCS3 itself may remain open.
6. Restart the game and use a normal Load. The definitions apply to every save using that archive. Existing remaining ammo is not refilled by this operation; resupply or a new stage may be needed.

| Field | Editable storage range |
| --- | --- |
| Base attack | 0–65,535 |
| Minimum / maximum range | 1–255; minimum must not exceed maximum |
| EN cost | 0–255; 0 means no EN cost |
| Maximum ammo | 0–255; 0 means no ammo cost |

These are native storage limits, not a promise that all extreme values display or behave correctly in-game. Upgrades, skills and other bonuses still apply. Some combination attacks calculate attack from other weapons; a stored base attack of zero can be intentional. MAP targeting shapes and weapon prerequisites are separate properties and remain unchanged.

**Selected defaults** and **All original defaults** stage the original Japanese-game values for review, preserving installed text and other gameplay modifications. Each write creates a verified complete backup under `_weapon_settings_backups` next to the archive. **Restore archive backup…** uses that backup's `patch.json` receipt and restores the exact earlier archive only if it still matches the receipt's recorded patched state.

The archive writer changes only the selected weapon fields, verifies every unrelated archive entry, preserves file size and modification time, detects stale reads, and rolls back ordinary installation failures. Other tools that require stock WeaponData fingerprints may reject edited weapon stats; restore weapon defaults before using such a tool, then reapply your stats.

Validation: **88 automated tests passed**. Disposable copies of three real SDAT archives passed edits, field restoration, exact backup restoration and checks of all unrelated entries. Original archives remained unchanged. Dialog layout and write guards passed at 100%, 150% and 200% scaling. **Fresh in-game verification is still pending.**

Read-only executable check: `"OGMD Save Editor.exe" --inspect-weapons "path\Logic.psarc.sdat" --weapon-report "new-report.json"`. Report files are never overwritten.

## Version 1.5: editable pilot status

In **Pilot stats**, select a pilot and click **Edit status…**, or double-click the pilot. Edit the values, click **Apply**, then use **Save pilot changes**. An asterisk marks staged status changes. Search preserves them; **Discard pending** and **Read save** clear them. Cancel closes the status window without staging its edits.

- **Level / EXP:** level 1–99 and EXP 0–65,535. Changing level sets EXP to the start of that level; entering EXP updates the level. Every 500 EXP advances one level, with level capped at 99.
- **Combat stats:** Melee, Ranged, Skill, Defense, Evade and Hit. Enter the desired personal total, from the shown natural value to 400. The editor writes the corresponding training bonus. Level changes keep training and recalculate natural growth; they do not freeze the total. Skill, Ace, Twin, equipment and battle effects may change the values displayed in-game.
- **Terrain:** Air, Land, Water and Space. Choose any rating from the pilot's natural rating through S. The save stores positive training, so it cannot lower a rating below the pilot's game-data default.
- **Combat totals to 400**, **Terrain to S**, and **Reset training** affect the selected pilot's open form. Reset training removes combat and terrain training while keeping the selected EXP. These buttons do not spend/refund PP; PP remains separately editable.

Base stats and growth use the bundled BLJS10335 PilotData and native growth curves. The local Pilot Editor's Spirit/Will changes do not affect these profiles. Separate mods to base stats/growth/terrain are not reflected in this preview. Natural skills and Spirit unlocks follow the new level; existing learned skills and their saved growth flags are preserved.

Status writes share one verified full-slot backup and atomic PARMDAT transaction with PP, kills and Will. Unknown pilot-save versions disable the new status controls without preventing unrelated edits. All 256 records are supported, including the last record. Existing saves with unusual capped training are preserved when those values are left unchanged.

Validation for 1.5: **74 automated tests passed**; native serialization/deserialization and **129,492 growth results** checked; edits/restoration verified on disposable copies of **11 real save slots**, with original hashes unchanged. The source UI was visually inspected and the executable checked separately. **A fresh in-game normal Load remains unverified.** Exit the game before writing and test a copied slot first.

## Version 1.4: pilot Will + Seishin testing

- **Pilot Will** is now shown on the Pilot stats tab and can be staged/saved per recruited pilot. The saved byte is pilot record `+0x2F`; writes use the same full-slot backup, stale-save guard, atomic replacement, and post-write readback checks as PP/kills. The editor exposes the full byte range `0–255`; ordinary OGMD gameplay normally uses a much narrower range.
- **Seishin / Spirit Commands** are different: the six command IDs are game pilot data, not per-pilot fields in `PARMDAT.SAV`. A new **Seishin patch** tab therefore generates an RPCS3 EBOOT override for testing rather than pretending to write them into the save. The verified public override points affect the corresponding Spirit slot for **all pilots** while enabled.
- The Seishin patch tab accepts raw hexadecimal Spirit IDs (`00–FF`) for Spirit 1–5 and Twin Spirit, and can also generate the known `SP cost 0` and `unlock regardless of level` helpers. Disable the generated patch to restore the original command set.
- A true persistent **per-pilot** Seishin editor requires mapping/editing OGMD's `PilotData`/EBOOT data rather than the scenario save.

## Version 1.3.1 hotfix

Some valid Moon Dwellers saves set the final bit in the 256-bit replacement-weapon occupancy mask even though this editor only has confirmed records for slots 0 through 254. Version 1.3 treated that reserved bit as a fatal format error and therefore blocked the entire save from loading. Version 1.3.1 now ignores and preserves that bit while reading, so pilot skills and the other unrelated editors remain available. As a safety measure, replacement-weapon *writing* is disabled for a save while that reserved bit is set.

## Version 1.3

- Added drag-and-drop ordering for the six pilot skill slots so the saved order matches the in-game **Acquired Special Skills** list.
- Reorders are staged automatically and can be discarded before saving.
- Preserves learned levels and natural-growth behavior; unsafe moves are blocked.
- Added keyboard Alt+↑ / Alt+↓ reordering and regression tests for saved skill-order flags.

## Backups and recovery

Backups are beside the original slot under `_save_editor_backups/<timestamp>/<original-slot-name>/`. The success message gives the full path. Backups contain every original file and are verified before any write.

To restore: exit the game, copy the complete backed-up slot back to its original savedata location using the same slot name, then load that slot normally. Preserve the current slot separately if you may want it later.

The editor fingerprints every save file and rejects writes if the slot changed since loading or during backup. File replacement is atomic and checked byte for byte. Ordinary write failures trigger restoration of affected original files. Multi-file writes cannot be atomic across a power loss; retain the complete backup for recovery.

## Supported format and validation

Supported: decrypted **BLJS10335_OMI-SCN…** PS3 Japanese/English-patched Moon Dwellers scenario saves produced by RPCS3. Unsupported: `OMI-SYS` system/Continue saves, PS4 saves, other regions/layouts, and encrypted physical-console saves. No console signing is performed.

74 automated tests passed, including backup identity, two-file rollback, stale-save rejection, pilot-skill drag/reorder behavior, natural-growth preservation and replacement flags, skill growth and level limits, completed-game metadata, the final pilot/mech records, shared-form equipment accounting and GUI search/staging. The original seven edit categories and both new mech features passed byte-level checks on disposable copies of nine local save folders (six distinct slots); original save hashes remained unchanged during those checks. Mech writes were reversed to produce byte-identical copies of the originals. **A save edited with these new features still needs an in-game normal-Load test.**

Developer checks: `python -m unittest -v`. `python verify_real_saves.py` and `python verify_mech_saves.py` inspect known local saves and edit temporary copies only. See `qa/mech_skills_verification.json`, `qa/skills_progress_verification.json`, `qa/real_save_verification.json` and `FORMAT_NOTES.md` for evidence. The editor is a separate tool; it does not install game patches or change RPCS3 settings.
