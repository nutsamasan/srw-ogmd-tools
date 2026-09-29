# OGMD Full English Patcher 1.6.2

**Public download:** get `OGMD-Full-English-Patcher-1.6.2-windows-x64.zip` from [Releases](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-09-29). This single ZIP includes the program and complete 1.6.2 patch data. Extract it and open `OGMD-Full-English-Patcher-1.6.2.exe`. Keep the supplied `data` folder beside the EXE, then select your own supported Japanese game copy. See [package setup](../docs/DATA_DOWNLOADS.md).

Version 1.6.2 includes the battle-dialogue fitting fix confirmed in RPCS3 on
Azuki's “All hands, brace for impact…” line. It applies to the shared battle
caption renderer in both full-size and compact layouts, across all three rows.

Full translation now includes the supplied English startup notice and the
official PS4 English logo animation, converted to PS3 video. The intro retains
all 421 frames, the PS3 timing, original audio packets, and movie archive layout.
Both assets passed offline checks; a fresh RPCS3 startup test is still pending.

Use this standalone patcher or **Script Editor 3.11 → Full English patcher**
for these additions. Release data 1.6 requires Patcher 1.6 or newer; Script
Editor 3.9 and older embed Patcher 1.5 and cannot build it. Patcher 1.6.2 retains
the clearer source-folder guidance. Existing game copies are not changed by
updating the patcher.

The release retains battle subtitle fitting, 117 Hagwane → Hagane location-banner corrections, and support for editor exports containing location labels, Spirit Command names/descriptions, and weapon names. The previously confirmed backlog fix and all 918 accepted edits are retained.

The release uses the confirmed fitting code with diagnostic recording removed. Full-size captions use a 768-unit width at cell size 28; compact captions use 720 at size 20. Both modes and all three rows passed offline PowerPC execution checks. Battle line breaks, speaker names and the existing font correction code are preserved.

The tested proportional-font (VWF) and apostrophe fixes are now embedded in
EBOOT. New outputs need no font-spacing YAML. This release targets RPCS3;
physical PS3 support is not included.

Open **OGMD Full English Patcher.exe** and keep its `data` folder beside it.
The portable package includes its own Python/Qt runtime. RPCS3, your game,
and your saves are not included.

## Create a complete English game

1. Leave **Font / battle text fix only** unchecked. Select the untouched decrypted Japanese
   PS3 ISO or extracted game folder (BLJS10335, version 01.00).
   The folder must contain `PS3_GAME` or be `PS3_GAME` itself, with
   `PARAM.SFO` and `USRDIR/EBOOT.BIN`. Installed `USRDIR/PSARC` data is not a
   full-game source; use the editor's **Patch edits** for text-only changes there.
2. Choose a new output ISO filename or game folder.
3. Optionally select `patch_edits.json` from the editor's **Export edits**.
   Inside the editor, **Use current editor edits** attaches a fresh snapshot.
4. Click **Build and verify patch**, review the results, then create the output.
5. Optionally select your RPCS3 folder and run **Set up RPCS3** with it closed.
   Start RPCS3 fresh and boot the newly created game.

The original 801 accepted edited rows are retained,
including the Ariel/Sleigh corrections and exclusion of the two TEST labels.
Additional editor snapshots include all English edits currently in that
snapshot, including test edits if you have retained them.

## Upgrade an existing English game

Use Script Editor 3.11 **Patch edits** to apply your saved location/name changes to the current installed archives. All three new editor sections also work through exported `patch_edits.json` in full builds.


Check **Font / battle text fix only**. Select your existing ISO or extracted game folder,
choose a new output, then build and create it. This adds the font and battle-caption fixes through EBOOT and
preserves the game copy's current text, menus, archives and other files.
No vanilla-to-English translation is reapplied in this mode.
The new notice and intro are included in full translation builds. Font / battle
text fix only continues to change EBOOT alone.

For the backlog correction on an existing game, use Script Editor 3.11's
**Patch edits → Fix backlog scrollbar overlap** option. It is checked by
default, works for installed archives or a new ISO, and recognizes an already
fixed layout. It also applies saved text edits in the selected language.
Font / battle text fix only continues to preserve archives, so it does not add the backlog
layout correction by itself.

From the script editor, **Patch edits → Embed font / battle text fix…** opens this mode.
For an ISO-booted game, select the ISO used to boot it. Its EBOOT is not in the
installed HDD archive folder. You can continue patching script edits to the
installed data afterward, as before.

## Optional RPCS3 setup

VWF and apostrophe spacing are already in the game output. Setup applies the
existing compatibility settings, registers the new game path, and removes
only our known legacy OGMD font patch entries, preserving other patches.
It keeps rollback backups of changed files. No font YAML is installed for
an embedded-EBOOT build.

A full translation synchronizes existing OGMD installed archives and its
installation icon. Font / battle text fix only leaves installed game data intact, including
later script edits there. Saves under `dev_hdd0/home` are not touched.
Compatibility settings include SPU Cache off, `libvdec.sprx` LLE and Compatible
Savestate Mode; other hardware/controller preferences are preserved.

Close the selected RPCS3 before setup. If setup is interrupted or RPCS3 is
still open, the completed game output remains available. Use **Open build…**
to reopen its `iso_patch.json` or `full_patch.json` and finish setup later.
Use a normal game save after a fresh boot rather than an older savestate.

Old 1.0–1.2 builds still describe their YAML workflow. Reopening one does not
retrofit EBOOT. Upgrade its output with **Font / battle text fix only** to remove the font
YAML dependency.

## Verification and backups

Source checksums lock EBOOT and translation archives to the supported
revision. The compact EBOOT preserves the 12 confirmed font hooks and includes
fitting for the formatted and plain-text battle-caption paths. The wrapper fits the vanilla EBOOT size
exactly. Previously prepared font builds remain readable and can be upgraded.

Full translation checks every reconstructed archive and every SDAT block.
It also verifies the English movie archive against its release checksum.
Only the animated title clip changes in Movie.psarc; its other movies and
archive metadata remain byte-identical. Movie.psarc is used from the output
game and is not copied into the installed HDD data by RPCS3 setup.
ISO output keeps the image size, file extents and ISO9660/Joliet/UDF indexes.
The complete output is hashed and patched files are reread through the disc
indexes. Folder output verifies every copied file. Existing outputs and the
source game are never overwritten. A verification JSON is saved beside the
output. Partial folder copies are retained with a clearly marked name if a
copy fails; failed temporary ISOs are removed.

The earlier font and backlog fixes were confirmed in RPCS3. The reported Azuki
battle line was also confirmed by the user in the test build. The release's
fitting code is identical to that test build; broader layout cases were checked
offline. No full-game playthrough or console test is claimed.

RPCS3 setup and rollback manifests live under `builds/<build>/runtime_setup`.
Keep those folders to use **Restore RPCS3 setup…**. Restore refuses to overwrite
later changes and recovers completed writes if an operation fails.

## Portable copy

Copy the executable, this README and `data`, or extract
**OGMD Full English Patcher 1.6.2.zip**. Keep the sibling `script_editor` and
`full_patcher` folders when using the editor's shortcut.
