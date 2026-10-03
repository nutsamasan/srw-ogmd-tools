# Data included with the tools

The [complete Windows downloads](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-10-03) include their required data. See [package setup](DATA_DOWNLOADS.md). The Git source repository contains the tools and small catalogs; large game-derived resources remain in the release packages. Users supply their own supported game/save inputs.

## Save, Pilot, and Mech tools

These tools include small display/compatibility catalogs. Choose your own supported save directory or installed `Logic.psarc.sdat` through the application. Personal path lists and settings are not included in the downloads.

## Script Editor

The complete package includes `Editor/script_export/OGMD_EN_JP_20260908`, containing `SOURCE_MANIFEST.json`, corpus indexes, per-collection `script.json` files, and English/Japanese/bilingual text exports. Historical extraction paths in provenance are informational and do not require the same drive layout.

Native preview files `font.bin`, `font_atlas.png`, and `tex_13.png` are under `Editor/assets`, together with provenance and the matching `runtime` support folder. The GUI finds these resources automatically. Full-English release data used by the editor's patcher dialogs is included at `full_patcher/data`, beside the `Editor` folder.

For source use, select the included corpus and preview resources with `--corpus <folder> --assets <folder>`, or copy them into the source checkout's `script_export` and `script_editor/assets` directories. Copy the included `full_patcher/data` directory to the equivalent source path for the embedded patcher dialogs.

Copy `Editor/_internal/assets/title_cards.zip` from the complete Script Editor package into `script_editor/assets` for source use and Windows builds. This verified library contains 115 English/Japanese title and chapter-number sheets. S084's English sheet is corrected to **VAUGHT AND FAIRY** in all six animation layers; `tools/build_title_card_assets.py` reproduces the library and `title_card_correction.py` reproduces the correction from native donor pixels. Game-derived artwork is kept in release attachments, outside the source repository.

`prepare_assets.py`, `tools/export_script_by_stage.py`, `tools/export_editor_fixed_data.py`, `tools/export_editor_expanded_data.py`, and `tools/build_battle_speaker_index.py` document the original extraction/index-building pipeline. They retain historical staging conventions and need PS3 Japanese and PS4 English source data.

## Full English Patcher

Its complete package includes a `data` folder beside the EXE: `release.json`, archive recipes, translation deltas, SDAT metadata, native fonts, an icon, embedded font/battle-text resources, and the English intro patch. The GUI detects this folder automatically and checks the release fingerprints.

For source use, copy the folder to `full_patcher/data` or pass `--data <folder>`. `tools/build_full_patch_package.py` and related scripts document the original production pipeline. These resources include game-derived material and retain their original ownership; the tool's GPLv3 license does not relicense them.

## Integration fixtures and research

Existing integration tests refer to extracted tables under `work/extracted/ps3_logic/Dat/FixedData`, generated corpora under `script_export`, and historical `work/poc` paths. Personal emulator references in the source publication use `local_data/rpcs3`; the sample save directory is `BLJS10335_OMI-SCN_EXAMPLE`. Supply isolated fixtures and adapt developer tests to your own paths.

Keep game material, settings, and generated reports outside Git. `work`, `local_data`, `script_export`, and local settings are ignored. A complete game ISO or disc folder is not included with the tools.
