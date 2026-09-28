# OGMD Pilot Editor 1.1

Windows tool for **Super Robot Wars OG: The Moon Dwellers, PS3 BLJS10335 in RPCS3**.
Run **OGMD Pilot Editor v1.1.exe**. Python is not required for the packaged executable.

Version 1.1 keeps review buttons visible when the window is resized or display scaling is increased. **Write archive changes**, **Save current Will**, and **Restore archive backup** say which action they perform. Check **I have exited the game** to enable writing. **Cancel** returns to the editor and keeps staged changes.

The selected Will profile now shows its per-event gains and losses. **Compare profiles…** opens all 12 profiles, event definitions and a short explanation of each. The same information is in [WILL_BEHAVIOR.md](WILL_BEHAVIOR.md).

## Spirit Commands and Will behavior

1. Select the installed `Logic.psarc.sdat` and click **Read archive**. The local RPCS3 installation is offered automatically when available. For an ISO installation, use `dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat`.
2. Search for a pilot. Edit the **five normal Spirit Commands**, the **Twin command**, their **SP costs**, and **unlock levels**.
3. Choose a **Will behavior** profile. The 12 original profiles are labeled with example pilots: selecting the Kyosuke / Ryusei profile gives that pilot their native Will gain/loss response. These are existing game profiles, not custom per-event numerical modifiers. Skills, Ace bonuses and scripted events can further affect Will.
4. Click **Stage selected pilot**, then **Review and write…**. Moving to another pilot also stages valid edits. Review displays each changed command, cost, level and profile.

The catalog includes 218 pilot IDs, including alternate and enemy records, and 42 named commands. Each ID is edited separately; changing an enemy or alternate version does not change another ID with the same name. Twin commands remain subject to the game's Twin-system requirements. Empty slots are supported. Existing additional command-condition bytes are preserved when editing populated slots.

**Selected defaults** and **All original defaults** stage restoration of the original Spirit Commands, costs, levels and Will profiles. Write the staged restoration to apply it. This changes only those pilot fields and preserves English names, mech skills and other archive content.

Each archive write makes a verified backup in `_pilot_settings_backups` beside the archive. **Restore exact backup…** accepts its `patch.json` receipt and restores the complete previous archive only when the current archive still matches that receipt. Use original defaults when you need to preserve newer unrelated archive changes.

## Current Will / Ki

1. Open **Current Will · Save file**, choose the desired `BLJS10335_OMI-SCN…` slot, then **Read save**. The path list is ordered newest first.
2. Select a pilot, set **Current Will / Ki (50–200)**, then **Stage selected pilot**. You can stage several pilots.
3. Click **Review and save…**. Only the selected pilots' current Will bytes are written.

This edits the value stored in the save. It does not attach to RPCS3 or freeze Will. Deployment, a new stage, scripted events or the game's pilot-specific cap may change the number afterward. **Set selected to 100** uses the ordinary base value; it does not reconstruct all deployment bonuses.

Every save write creates a complete slot backup under `_save_editor_backups`. **Restore Will from backup…** selects the matching slot folder inside a backup, then stages only its old Will values, preserving other current save fields. Review and save to apply that restoration. The original full-slot backup is also retained for manual recovery.

## Using the result

**Exit the game before writing; RPCS3 itself may stay open.** After an archive edit, start the game fresh and load the save normally. Avoid an old emulator savestate because it can retain the previous data. For current Will, load the edited scenario slot through the normal Load menu.

This version accepts the verified PS3 archive and save layouts. It does not edit ISO files directly, PS4 saves, physical PS3 save signatures, or live emulator memory. Game reinstalls and translation updates may replace archive changes; apply pilot edits after those updates. A translation editor may reject the modified PilotData fingerprint; restore pilot defaults before using that editor, then reapply the gameplay edits.

## Verification

- 19 automated tests cover all pilot defaults, the last pilot record, empty/Twin slots, unrelated-byte preservation, invalid values, stale files, archive locking, verified backups, rollback, restore, GUI staging, profile explanations and review actions at 100–200% display scaling.
- Version 1.0 passed edit/restore verification on disposable copies of three real archives and ten real save slots. The archive/save write code is unchanged in 1.1. All original files were rechecked against the start of this update and unchanged by this work.
- Native executable getters and the pilot serializer/deserializer establish the field mapping. Details are in `FORMAT_NOTES.md` and `qa/native_evidence.json`.
- The standalone executable and ZIP are checked separately in `qa/release_verification_v1.1.json`.

**In-game validation remains pending.** The file and package checks do not prove the resulting command effects, Will persistence or rendered menus. First test a disposable copied save with a fresh game boot.

The source reuses the existing local mech patcher's PSARC/SDAT transactions and save editor's guarded save writer. Build from this workspace with `build.ps1`.
