# Local game data

The source repository contains the tools. Matching script and patcher data are available as separate ZIPs on [Releases](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-09-29). See [data download instructions](DATA_DOWNLOADS.md). Users still supply their own compatible game/save inputs; a complete game ISO or disc folder is not included.

## Save, Pilot, and Mech tools

These tools include small display/compatibility catalogs. Choose your own supported save directory or installed `Logic.psarc.sdat` through the application. Local path lists are created or maintained beside the programs and are ignored by Git.

## Script Editor

Download `OGMD-Script-Editor-3.14-data.zip` for the script corpus and preview resources. The corpus contains `SOURCE_MANIFEST.json`, `data/stage_index.json`, the other indexes, per-collection `script.json` files, and English/Japanese/bilingual text exports. Its directory is `script_export/OGMD_EN_JP_20260908`; `--corpus` can select a different location. Historical extraction paths in provenance are informational and do not require the same drive layout.

Native preview resources are `font.bin`, `font_atlas.png`, and `tex_13.png`. The data ZIP places them under `assets` beside the executable when extracted together with the GUI ZIP. The GUI finds this layout automatically. If using separate folders, choose their folder and then your script corpus folder when prompted, or use `--assets <folder> --corpus <folder>`. The selected paths are remembered beside the program. The small battle-speaker map is included in the application.

For source use, copy the resources to `script_editor/assets` or use `--assets`. The data ZIP also includes the matching `assets/runtime` support folder. To regenerate assets, `prepare_assets.py` documents the original conversion process and expects an already extracted font and archives under `work/`. The older local `script_editor/build.ps1` expects these resources; use `tools/build_windows_release.py` to reproduce the public GUI packages.

`tools/export_script_by_stage.py`, `tools/export_editor_fixed_data.py`, `tools/export_editor_expanded_data.py`, and `tools/build_battle_speaker_index.py` contain the extraction/index-building code. These retain the original project's intermediate directory conventions and need PS3 Japanese and PS4 English source data. There is not yet a verified one-command setup from a clean checkout and retail inputs.

## Full English Patcher

Download `OGMD-Full-English-Patcher-1.6.2-data.zip`. Its `data` folder holds `release.json`, archive recipes, translation deltas, SDAT metadata, native font data, an icon, embedded font/battle-text resources, and the English intro patch. These resources are release attachments rather than Git-tracked source files. The data contains game-derived text, graphics and other resources; the tool's GPLv3 license does not relicense that material.

Extract the data ZIP and matching GUI ZIP into the same parent folder so `data` sits beside the EXE. The application also accepts `--data <folder>` and validates all release payload fingerprints. When using the Full English patcher dialog inside the Script Editor, browse to this same data folder. For source use, copy it to `full_patcher/data`. `tools/build_full_patch_package.py` and related scripts document the original production pipeline.

## Integration fixtures and research

Existing integration tests refer to extracted tables under `work/extracted/ps3_logic/Dat/FixedData`, generated corpora under `script_export`, and other historical `work/poc` paths. Personal emulator references in the publication copy use `local_data/rpcs3`; the sample save directory is `BLJS10335_OMI-SCN_EXAMPLE`. Supply isolated fixtures and adapt those developer tests to your own paths.

Do not run an installer or integration script against your only game/save copy. Keep game material and generated reports outside Git. `work`, `local_data`, `script_export`, and local settings are ignored.
