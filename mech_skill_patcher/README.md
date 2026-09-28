# OGMD Mech Skill Patcher 1.0

Edit the five built-in skill assignments for 216 Moon Dwellers mechs/forms. Choose from 47 native skills, including HP/EN Regen, barriers, Jammer and Mirage. Empty removes a skill from that slot. The executable runs without Python.

## Use

1. Stop the game. RPCS3 may stay open.
2. Open **OGMD Mech Skill Patcher.exe**. Choose the game archive and click **Read archive**. For an installed ISO game, select `dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat` under your RPCS3 folder. You can also enter an extracted game folder or its Logic archive. The loaded path is shown in the status line.
3. Search/select a mech and choose its five built-in skills. Choices are staged automatically. Each form and unit ID is separate; changes apply to every occurrence of that unit ID, including enemies. Check similarly named variants before editing.
4. Click **Review and write…**, inspect the exact changes and target, confirm the game is stopped, and write. The patcher creates and verifies a backup before replacing the archive.
5. Start the game fresh and load normally. Do not use an old emulator savestate to test the change.

Only the selected archive is patched. Use the installed archive for the RPCS3 instance you actually run. If you also maintain an extracted game copy, select and patch that archive separately; an install/reinstall or full English patch can replace gameplay customizations. This tool does not directly edit an ISO.

## Restore whenever needed

- **Restore selected defaults** stages the original five skills for the selected mech.
- **Restore all defaults** stages the original five skills for every mech. It includes mechs hidden by the current search filter.
- Finish either operation with **Review and write…**. Original defaults are bundled, so they remain available after reopening the patcher and even if old backups were moved. Only the skill bytes change; current English text is preserved.
- **Discard changes** abandons staged choices without writing anything.
- **Restore exact backup…** opens a backup's `patch.json` and restores the entire preceding archive byte for byte. The current archive must still match that patch; a stale backup cannot overwrite newer changes. Restoring also creates a backup of the current archive. For a later translation update, use the skill-default controls instead.

Every write keeps a backup and a change log under `_mech_skill_backups/<timestamp>/` beside the archive. Keep that folder for full recovery. If a power loss interrupts an operation, stop the game and preserve the current archive separately, then copy the verified backup's `Logic.psarc.sdat` to the original path shown in `patch.json`, preserving its timestamp. If a lock file remains after a crash, close all patcher windows before removing that `.mech-skills.lock` file.

## Scope and behavior

Supported: PS3 Japanese BLJS10335 Moon Dwellers unit tables, including the current English patch, used with RPCS3. PS4, other titles/regions and unit-stat mods with a different structural fingerprint are rejected. Hardware PS3 authentication has not been validated.

This patches skill assignments, not skill effects, mech stats, pilot skills or equipped Ability inventory. The five native slots are preserved. Duplicate skills, dummy ID 48 and the separate Transform/Repair/Resupply/Shield capability labels are excluded. Specialized skills still depend on their native conditions, pilot abilities, form links and story rules; adding Mahakara alone does not create a Neo Granzon transformation link. Tentative abilities are labeled as they are in the native table.

The save's per-slot enable switches still apply. The newest inspected normal save had all five switches enabled for all 122 saved mechs/forms; that does not establish every possible save. A switch disabled in a save remains disabled. The separate Save Editor 1.2 displays the original bundled built-in skill names, so its names/empty-slot display will not reflect these custom assignments. Its equipped Ability editing is a separate feature. This patcher does not modify saves.

The rebuild preserves archive size and timestamp and verifies unchanged entries, all encrypted data blocks, backup checksums and the installed file. Stale reads and concurrent patcher writes are rejected. Normal write failures attempt a verified rollback. Source game files are never used as development test targets: all write tests use disposable copies.

Offline validation covers native skill byte boundaries, selected/all defaults, text preservation, exact backup restoration, stale/corrupt backups, interrupted writes and GUI staging. Actual in-game skill effects and persistence still need a fresh user-started boot and normal Load test. See `qa/archive_verification.json` for the real-archive copy checks.

## Development

Run `python -m unittest -v test_mech_patch` with the workspace's `script_editor/.venv` Python. `verify_archives.py` tests disposable copies of the locally configured Japanese and English archives. `build.ps1` creates the standalone executable. `--check <report.json> --target <archive>` performs a read-only packaged-runtime check.

The local PSARC/SDAT and FIXH helpers are copied from the existing Script Editor; the PSARC reader adds truncated/empty-block detection. `build_catalog.py` records original table hashes, verified non-skill structure fingerprints, original assignments and display labels. The native UnitData getter reads record +0x46 through +0x4A; save enable flags are a separate mechanism documented in the Save Editor format notes.
