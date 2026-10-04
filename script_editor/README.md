# OGMD Script Editor v3.19

Version 3.19 corrects scenario 21 to **GILLIAM'S UNDERTAKING** in the library, title-card labels, and native menu/save title. Full English Patcher 1.6.6 includes it in new builds. Existing saved text and artwork edits retain their source fingerprints and folder keys. The stage-start artwork already has the correct spelling.

Version 3.18 includes the scenario 40 **HAGANE'S CRISIS** correction in the
built-in Full English Patcher 1.6.5. English **Patch edits** builds also correct
both stage-menu title fields when the source already contains the English
title. Japanese tables remain in their selected language.

Click **Seishin names / descriptions…** above the script library to edit each
command's text. The duplicate **Spirit Commands** library section is removed;
global search results open the dedicated Seishin editor directly. Edit each
command's name and description together. Search by command ID, English or
Japanese text. Use the English and Japanese tabs, then **Save command**.
Switching commands or closing saves valid changes. **Restore source for this
language** restores both fields in the selected tab. Reserved entries 0–1 are
available through **Show reserved entries**.

These edits use the same `edits/project.json` as the regular editor. Use
**Patch saved edits…**, or **Export edits** and pass `patch_edits.json` to the
Full English Patcher. The built-in patcher can use **Use current editor edits**.
Only names and descriptions change; Seishin effects, SP costs and pilot
command assignments remain as configured. The native font preview is a
reference; verify the final appearance after a fresh game boot.

Version 3.17 corrects all ten Pilot Development stat and terrain descriptions. Both lines now display completely, with line lengths fitted to the menu box. The fix was confirmed in RPCS3. The built-in Full English Patcher 1.6.5 includes it in new full translation builds.

**Public download:** get `OGMD-Script-Editor-3.19-windows-x64.zip` from [Releases](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-10-05). This single ZIP includes the editor, English/Japanese corpus, preview resources, and Full English Patcher data. Extract the entire ZIP and double-click `Start Script Editor.cmd`. Keep its `Editor` and `full_patcher` folders together. See [package setup](../docs/DATA_DOWNLOADS.md).

Double-click **OGMD Script Editor.exe** (updated to v3.19) or **OGMD Script Editor v3.19.exe**. Save and close the older editor first; your existing `edits/project.json` is reused automatically. Earlier versioned executables are retained.

Version 3.18 fixes `Fixed game records differ: WeaponData_name:0366` on installed data customized with the Save Editor's weapon tool. Weapon name edits preserve base attack, minimum/maximum range, EN cost and ammo. Only these six bytes per supported weapon are exempt from the stock fingerprint; invalid ranges, changed owners/slots, other weapon properties and dummy-record edits are still rejected. Pilot settings and mech-skill compatibility remain included. You do not need to restore weapon defaults before building a text patch.

Version 3.13 fixes `Fixed game records differ: PilotData_short_name:0010` when building text edits on installed data customized with the OGMD Pilot Editor. Name edits preserve all six Spirit Command slots, SP costs, unlock levels, condition bytes and Will profiles. Validation accepts only the supported BLJS10335 table and setting values; pilot stats, skills, mappings, reserved bytes and the dummy record remain guarded. You do not need to restore pilot defaults before building a text patch.

Version 3.12 fixes `Fixed game records differ: UnitData_name:0140` when building text edits on installed data customized with the OGMD Mech Skill Patcher. Text patches preserve all five built-in skill slots on every mech. Validation still checks the unit mapping, stats and other record fields, and rejects unsupported skill IDs. Existing projects and exported edit bundles remain compatible; no source-corpus conversion is needed.

Version 3.11 introduced **Full English Patcher 1.6.5** and the battle-dialogue fitting fix confirmed in RPCS3 on Azuki's “All hands, brace for impact…” line. These remain included in v3.18, along with the supplied English notice and PS4 English intro. **Use current editor edits** still attaches your current English corrections. Editor 3.9 and older contain Patcher 1.5 and reject this release with “Choose the data folder from a verified full-English release.” Updating files does not update an already running editor; reopen v3.18.

For **Full English patcher**, select the original Japanese ISO or complete extracted disc folder containing `PS3_GAME`. An installed `dev_hdd0/game/BLJS10335/USRDIR/PSARC` folder cannot supply the boot executable and intro. The patcher now identifies that selection before starting a build. To apply only saved text corrections to installed archives, use **Patch edits**. For a full rebuild, select **Use current editor edits** to carry your corrections into the new output.

Version 3.9 adds **Location banners**, **Spirit Commands**, and **Weapon names** near the top of the library. Location banners includes 764 story and map label fields, including the top location strip. Spirit Commands contains 44 names and descriptions; Weapon names contains 856 entries with unit and slot labels to distinguish repeated names. All three support English/Japanese editing, Find / replace all, import/export, and native folder/ISO patching. Names and banners use one line. Gameplay stats and event behavior are preserved.

The 117 location occurrences of **Hagwane** are corrected to **Hagane** in Full English Patcher 1.5. Your existing editor edits are retained; the same location corrections have been added to the saved project with a backup. Use **Patch edits** to apply them to your current installed game data.

For the battle overflow fix, use **Patch edits → Embed font / battle text fix…** or the full patcher's **Font / battle text fix only** mode. Select the ISO or game folder you boot, then create a new output. The EBOOT update fits all three rows in the shared battle-caption renderer, including full-size and compact dialogue, and restores the font limits afterward. Speaker names and authored line breaks are retained. The normal battle preview now uses cell size 28 / width 768; compact captions use 20 / 720 and story previews use 24 / 768. The reported Azuki line was confirmed in-game; both battle sizes and all three rows passed offline PowerPC checks. The release contains the same confirmed fitting code with diagnostic recording removed. Start a newly patched output with a fresh RPCS3 boot. This EBOOT update preserves current archives; use Patch edits separately for location/name changes in an existing game.

Version 3.8 adds **Fix backlog scrollbar overlap**, checked by default in **Patch edits**. It reserves space before the Triangle backlog scrollbar using the layout confirmed in game. It works for folder and ISO patches, including builds without text edits. Review shows the backlog correction separately. Already fixed layouts are recognized and skipped. Uncheck this option to apply only text edits. Full English Patcher 1.4 includes the same fix in complete English builds.

To correct an existing English game, use **Patch edits** with this option enabled. Choose the installed game data for an ISO-booted RPCS3 game, or choose ISO mode for a new image. The option also applies any saved edits in the selected language. It changes only the backlog text width limits; dialogue wording, authored line breaks, font dimensions and the main dialogue window are preserved. **Font fix only** continues to replace only EBOOT; use the backlog option for this separate layout correction.

Version 3.7 fixes **battle line breaks**. The preview interprets battle `/` markers as line breaks, including width, compression and the three-line limit. The edit field keeps the authored markers; pressing Enter also works and becomes `/` when patched. **Wrap preview language** preserves existing battle boundaries and writes any additional breaks as `/`. Story dialogue retains its separate `@` convention. Original scripts and saved edits are not automatically rewritten.

**Full English Patcher 1.3** now includes the user-tested VWF and apostrophe code inside EBOOT. New full translations need no spacing YAML. From **Patch edits → Embed font fix…**, or **Full English patcher → Font fix only**, you can upgrade an existing English ISO/game folder while preserving its current text. Choose a new output and build/verify it before creating the copy. An ISO-booted game must receive the fix in its boot ISO; selecting installed HDD archives alone cannot replace that EBOOT.

The optional RPCS3 setup applies compatibility settings and removes our known legacy font patch entries with rollback backups. Font fix only preserves installed game data; full translation synchronizes it as before. The regular text patcher's **RPCS3 compatibility** button changes compatibility settings only. Keep the sibling `full_patcher/data` folder to use the embedded-font workflow. This EBOOT is for RPCS3; physical PS3 support is not included. The original font code is preserved. Version 3.11 extends the earlier fitting hooks to the plain-text battle-caption path used by the reported scene.

Version 3.6 adds **battle speaker mapping** in English and Japanese. Each line uses its own character ID, so guest lines in another pilot's bank receive the correct label. All 263 banks are indexed; 58 contain multiple speakers.

- Open **Battle messages** in the library. Bank titles show the most frequent speaker and how many others appear; hover to see every contributing speaker and row count.
- Use **Battle speaker** to filter the selected bank. Search within the bank by either language's name or by text. Use the library search to find all banks containing a pilot, including guest appearances.
- The **Speaker / entry** column shows both names. The name fields and preview follow the selected line and preview language. Battle attribution is read-only; edit the **Pilot names → Short name** fields to update the corresponding labels throughout the editor.
- Unresolved entries show **Unknown speaker (ID …)**. IDs 138 and 140 use the official English **Bioroid Pilot** fallback and explicitly show that a Japanese name is unavailable. Hover over a speaker field or row for the mapping source.

Speaker labels are display information. Browsing and filtering do not create edits, and battle exports retain their existing row IDs and native metadata. Global Find / replace all continues to operate on editable text. The game needs no new patch to use this editor feature; build a script patch as usual when you change actual text. The preview remains a dialogue reference frame, not a reproduction of the battle HUD.

The bundled `assets/battle_speakers.json` records native logical-ID mappings, fallback names and source checksums. `tools/build_battle_speaker_index.py` rebuilds that asset from the verified local sources; it does not rewrite the script corpus. `test_battle_speakers.py` verifies full-corpus ID coverage, bilingual name changes, mixed-bank filters, search navigation, unknown labels, and preservation of native speaker metadata during text patching.

Version 3.5 adds **Pilot names**, **Mech names**, and **Glossary** at the top of the library. These contain 219 pilot records (short, given, and family names), 217 mech records, and 198 glossary records (term and two definition fields, including reserved/dummy entries). Select a row and edit English or Japanese. The row filter searches the entry name as well as the selected field; all three sections participate in global search/replace, import, export, folder patching, and ISO patching.

Pilot previews show the short and combined full name. Mech previews show the unit name. Glossary previews scroll through both definitions, using the native font and clickable teal underlined terms. Click a linked term in dialogue or glossary text to read its definition and jump to its editor row. A missing/ambiguous match is reported instead of opening an unrelated definition. Layouts are reconstructed references; final appearance and link behavior require a fresh game test.

To rename a glossary term, select its **Term** row and use **Rename term and linked text…**. Review the before/after changes, then apply. This updates the title and matching marked references across the selected language, including links split across lines. Directly typing a term changes only that field. Renaming can lengthen dialogue; check affected lines in the preview. Names and glossary terms must remain a single line without control markers. Numeric game IDs, stats, sort ranks, and other record fields are preserved. Renaming does not recalculate alphabetical sort order.

The original script library identity and existing rows remain unchanged. The new immutable extension is `06_Game_data` plus `data/fixed_index.json` in the existing export folder; keep those files with the corpus. English fields start from the accepted English patch baseline; Japanese fields use the original native records.

The full English release 1.2 includes the current accepted corrections, with the two TEST speaker labels excluded. `imports/menu_glossary_corrections_20260910.json` contains five additional menu/glossary fields for the saved Ariel/Sleigh corrections; use **Import scripts**, preview, and import to add those to your current editor project. The running project's saved text has not been replaced.

**Export edits** also writes `patch_edits.json`. Select that file in the standalone Full English Patcher 1.2's **Editor corrections** field to include later English changes in a vanilla-to-English ISO or folder build. Inside **Full English patcher**, click **Use current editor edits** to attach a snapshot of all current English edits; leave that field empty to use only the bundled release. Attached snapshots include your current test edits too, if any remain. The build reviews the actual text changes and validates native records before writing a separate output.

Version 3.4 adds **Use installed game data**. Select your RPCS3 folder and click this button to target only its installed OGMD archives; the second copy is cleared and your ISO is kept intact. The selection is saved. Old development/test game folders are no longer supplied as defaults.

Version 3.3 fixes RPCS3 spacing patch discovery by installing `patches/BLJS10335_patch.yml`. Setup now checks the actual files each time, can repair a missing or disabled patch without rebuilding the ISO, and preserves preferences from modern RPCS3's `config/config.yml`.

Version 3.2 updates the preview to the confirmed apostrophe spacing, adds a complete vanilla-to-English patcher, and offers **Set up confirmed spacing** after a script patch is installed or an ISO is written. Choose the RPCS3 folder you use; setup is backed up and preserves other games. The **Full English patcher** button opens the patcher embedded in the editor executable and reads release data from the sibling `full_patcher` folder.

Version 3.1 fixes the small dialogue-pool overflow encountered with the Irm/Irmgard edits on the original Japanese ISO. When necessary, complete UTF-8 text endings share storage; the text itself, every string-table index, command offsets, and file sizes stay intact. Build errors also identify the archive and script file.

The executable includes Python and Qt; no separate installation is needed on this Windows PC. Keep it in this folder so it can find the exported scripts and your edits.

- Select a stage on the left, then a line in the center.
- Edit English or Japanese text and speaker names on the right. Focusing a text field switches the preview language.
- Search the library by stage name, route, or script ID. Search the selected script in either language or by speaker.
- **Wrap preview language** calculates breaks using the native font's character widths. Choice delimiters and color controls require manual wrapping.
- **Ctrl+Z** undoes text edits within the current field. **Restore source** restores the preview language for the selected row.
- Edits autosave after 1.5 seconds; **Ctrl+S** saves immediately. **Ctrl+Enter** selects the next line.
- **Export edits** writes changed script collections as JSON, English, Japanese, and paired text into a new folder under `exports`.
- **Find / replace all** (**Ctrl+H** or **Ctrl+Shift+F**) searches all 430 collections, including current edits. Select English, Japanese, or both, with optional speaker names, case matching, and whole words. Multiline searches work; replacement text is literal. Review the full before/after results, then click **Replace all**. Double-click a result to open that script line. **Undo last Replace all** is available during the editor session and refuses to overwrite later edits to the same fields. Saved versions also remain in `edits/backups`.

Edits are stored in `edits/project.json`, with previous saved versions under `edits/backups`. Editing, importing, bulk replacement, exporting, and building a patch leave original extracted scripts and installed game archives unchanged. Installed game files change only through **Back up and install** or **Restore previous game files**. ISO mode creates a separate output image.

## Import scripts

1. Click **Import scripts**, then **Choose file** or **Choose folder**.
2. Select an edited `script.json`, editor `edits.json` / `project.json`, or an `EN.txt`, `JP.txt`, or `Bilingual.txt` export. For folders, choose which format you edited; only that format is read recursively. This prevents a stale JSON copy from overriding an edited TXT copy (or the reverse). A folder containing only `edits.json` / `project.json` can also be imported with the JSON option.
3. Keep the `[row IDs]`, collection folders, and native metadata intact. Renamed text files can use the **Untagged TXT language** selection. Bilingual `[row ID] EN speaker` / `[row ID] JP speaker` headers identify each language. Multiline text, empty text, and speaker names are supported. Exported block headings and explanatory notes are ignored. Use JSON when you need text that could be confused with a row header or exact control strings.
4. Click **Preview import**. Every input file is validated before any change is saved. Unknown IDs, mismatched source hashes, changed native metadata, conflicting duplicate records, NUL characters, or edits to null battle subtitles stop the import.
5. Review current/imported text. **Keep current text** skips conflicts with your existing edits; **Use imported text** replaces those conflicts. By default, values equal to the original source do not erase local edits. Enable **Also import source-equal values** if the supplied files should reset those fields too. Fields and rows omitted from the import remain as they are.
6. Click **Import … text fields**, then close the dialog to see the updated text and dialogue preview. **Undo last import** is available for the current session and refuses to overwrite later changes to imported fields. Saved backups remain available after restarting.

Import adds changes to the active edit project. It does not replace the corpus, and it does not write to the game until you use the patcher.

## Patch directly to an ISO

1. Save your edits and choose **Patch game → Patch destination: ISO image**.
2. Select a **decrypted OGMD PS3 BLJS10335 ISO**, and choose a new output `.iso` filename. The source stays intact; existing output files are never overwritten.
3. Select English or Japanese and click **Build patch preview**. The app reads affected archives directly from the ISO, compiles your edited fields, and verifies the rebuilt native archives. Review the actual source-ISO text and the text to write.
4. Click **Create patched ISO**. The output preserves the original image size, ISO9660/Joliet/UDF indexes, UDF metadata mirror, and all bytes outside the patched archive extents. Split files such as the battle archive are supported. The complete output is read back and hash checked, followed by archive checks through the verified filesystem indexes.
5. The source and output SHA-256 values are saved next to the result as `<name>.iso.verification.json`. The build, edit snapshot, and text review remain under `patches/patch_.../iso_patch.json` and `native/`.

**Edited fields and the selected backlog fix are applied.** Unedited text, fonts, executable code, and other assets come from the selected ISO. Selecting an original Japanese ISO does not install the complete English translation or embed RPCS3's external spacing patch. Select an already translated ISO if you want to retain that translation while editing it. Encrypted images, inconsistent indexes, sparse/indirect UDF allocations, and unsupported disc layouts are rejected with an explanation.

Allow one full ISO's size on the output drive (about 11 GB for this disc), plus temporary space for affected archives on the editor's drive (up to about 11 GB when Logic, Common, and Battle are all changed). A failed write removes its temporary partial image; the source and existing output files stay intact. Offline verification checks the file structure and bytes; boot and visual validation must still be done in the game.

## Patch the game

1. Make and save your edits, then choose **Patch script edits**.
2. For a game booted from ISO, choose your **RPCS3 folder** and click **Use installed game data**. This selects its installed OGMD archives as the only target and keeps the ISO unchanged. RPCS3's configured virtual HDD location is respected. For an extracted game, you may instead select its archive folder and an optional second copy. Two selected copies must already have matching contents and dates; an older test folder must not be paired with a newer installation. The pristine extraction source is protected.
3. Choose **English** or **Japanese**. The patch writes only edited fields from that language into the PS3 native text slots. It does not switch the entire game language or install a complete English translation onto a new game. Unedited text stays as currently installed.
4. Click **Build patch preview**. The app compiles native scripts, rebuilds affected Logic/Common/Battle archives and General2d for the backlog fix, and checks every changed/unchanged archive entry and every encrypted SDAT block. No game files change during this step. Shared defeat-message edits are applied to their native copies in all referencing scenarios.
5. Review **Current text** versus **Patched text**. Known unsupported accented letters/symbols use supported equivalents when the corresponding option is checked; changes are visible in the preview. Other unsupported characters, lost numeric insertion tokens, or text that exceeds a native pool stop the build with an explanation.
6. Close RPCS3, then click **Back up and install**. The app rechecks checksums, creates verified backups, and replaces the selected copies while retaining the original archive sizes and modification times. Start the game fresh and use a normal save to read the new text.
7. To undo a game patch, choose **Restore previous game files**, select that patch's `patch.json`, and review the target folders. Restore the newest installed patch first if you have installed several. Restoration also handles an interrupted installation using its journal. Your editor text edits remain saved.

This patcher targets OGMD **PS3 BLJS10335** and supports story dialogue/speakers, shared defeat messages, map text, battle subtitles, opening/dream narration, previous-game recaps, pilot names, mech names, and keyword glossary terms/definitions. EBOOT, accepted spacing patches, fonts, other archive entries, and saves are preserved. It does not patch PS4 packages or other menu/encyclopedia text outside this library.

Each build is stored in `patches/patch_...`, with `patch.json`, an edit snapshot, rebuilt archives, and (after installation) `backups` plus `installation.json`. Keep these files to restore that game revision. Checksums stop an old patch or backup from overwriting a newer game revision.

The preview uses the original PS3 FTTF font atlas and the confirmed spacing-v3 apostrophe-width rule. The border is reconstructed. The default 24-unit cell / 768-unit width follows the existing offline audit; it is not a verified live-game pixel measurement. Both values are adjustable. Portraits, animation, backgrounds, and color effects are omitted. Narration, battle subtitles, and map menus may use other in-game layouts. Final results should be checked in the game.

If the exported corpus has moved, rename `settings.json` and choose its new folder on next launch. The editor checks source hashes and refuses to reuse edits against changed source scripts. Only one instance can use an edits workspace at a time.

Developer entry point: `script_editor/.venv/Scripts/python.exe script_editor/app.py`.

Checks: `script_editor/.venv/Scripts/python.exe -m unittest discover -s script_editor -p "test_*.py" -v`.

Rebuild from PowerShell inside this folder: `./build.ps1`. This uses a restricted build search path so unrelated tools' DLLs cannot be bundled. Run `& '.\OGMD Script Editor v3.18.exe' --self-check qa/bundle_v314_check.json` to check the packaged program with a temporary edits workspace and the sibling full-patcher release; the JSON report and screenshots are written under `qa`. Add `--check-unit-data path/to/UnitData.dat`, `--check-pilot-data path/to/PilotData.dat` and/or `--check-weapon-data path/to/WeaponData.dat` to verify that the packaged name compiler preserves custom mech skills, pilot settings and weapon stats on those extracted tables without modifying them.

`test_import_iso.py` covers all 430 collections in all four import formats, EN/JP and speaker round trips, conflict handling, undo, stale previews, invalid inputs, ISO multi-extent writing, source/output protection, UDF CRC rejection, and GUI refresh. `qa_iso_build.py <new QA folder>` runs a separate real-ISO integration check for Logic/Common/Battle using imported QA text, without changing the user's edits or installing anything. QA ISOs contain test text and are not the user's finished patch.

Disc parsing uses the ISO9660/ECMA-167 field layouts, with UDF metadata-partition details cross-checked against the [7-Zip UDF reader](https://github.com/ip7z/7zip/blob/main/CPP/7zip/Archive/Udf/UdfIn.cpp). No external archiver is required at runtime.

Retail archives can already be tightly compressed. When an edit needs extra space, the bundled [Zopfli compressor](https://github.com/fonttools/py-zopfli) optimizes text streams using the same zlib format before larger assets are considered. All optimized streams are decoded and checked against their original bytes. Edits must still fit the native text pools and the archive's fixed total size.

## Stage title cards (3.18)

Open **Stage title cards** to preview, export, import and patch English or Japanese artwork. The library includes 66 title sheets and 49 chapter-number sheets, with all six animation layers and transparency preserved. Menu stage-name text is edited separately.

The bundled S084 English card now reads **VAUGHT AND FAIRY**, reconstructed from original game glyph pixels without resampling. Full English Patcher 1.6.5 includes this correction automatically in new full translation builds.

For an existing game, select **st_084** and **English artwork**, click **Stage bundled artwork**, then **Patch saved edits** to build, review and apply the replacement through the existing backup workflow. **Remove saved card edit** removes the staged replacement; it does not undo an installed patch. Use patch restoration to undo an installed change.

Custom PNGs must preserve the exported full-sheet dimensions and transparency. **Save card edit** stores artwork separately from text edits. Export edits includes artwork for the standalone patcher; existing saved artwork from 3.15 is preserved. Native archive, export/import and offline checks pass; the corrected animation still needs a fresh in-game check.
