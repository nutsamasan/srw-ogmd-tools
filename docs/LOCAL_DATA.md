# Local game data

The source repository intentionally excludes the original game and extracted game resources. Users must supply their own compatible inputs. No download of a game or official translation is supplied here.

## Save, Pilot, and Mech tools

These tools include small display/compatibility catalogs. Choose your own supported save directory or installed `Logic.psarc.sdat` through the application. Local path lists are created or maintained beside the programs and are ignored by Git.

## Script Editor

The editor requires a generated script corpus containing `SOURCE_MANIFEST.json`, `data/stage_index.json`, the other corpus indexes, and the per-collection `script.json` files. The historical default directory is `script_export/OGMD_EN_JP_20260908`; `--corpus` can select a different location.

Native preview resources are `font.bin`, `font_atlas.png`, and `tex_13.png`. The public GUI asks you to select their folder and then your script corpus folder. You can also use `--assets <folder> --corpus <folder>`. The selected paths are remembered beside the program. The small battle-speaker map is included separately in the application.

For source use, resources may live under `script_editor/assets`; for the portable GUI, an `assets` folder beside the executable is also recognized. Native resources are absent from public downloads. `prepare_assets.py` documents the existing local conversion process; it expects an already extracted font and archives under `work/`. Optional RPCS3 compatibility setup additionally needs the matching `runtime` subfolder. The older local `script_editor/build.ps1` expects these private resources; use `tools/build_windows_release.py` to reproduce the public packages.

`tools/export_script_by_stage.py`, `tools/export_editor_fixed_data.py`, `tools/export_editor_expanded_data.py`, and `tools/build_battle_speaker_index.py` contain the extraction/index-building code. These retain the original project's intermediate directory conventions and need PS3 Japanese and PS4 English source data. There is not yet a verified one-command setup from a clean checkout and retail inputs.

## Full English Patcher

`full_patcher/data` normally holds `release.json`, archive recipes, translation deltas, SDAT metadata, native font data, an icon, and other release resources. None is included in this repository. A delta extension does not establish that a file is free of copied game content: the local release carries official English text/graphics and an English intro.

The application accepts `--data` for a locally prepared compatible folder and validates that folder. `tools/build_full_patch_package.py` and related package/upgrade scripts document the current local production pipeline. This source release is not a standalone English-patch download.

## Integration fixtures and research

Existing integration tests refer to extracted tables under `work/extracted/ps3_logic/Dat/FixedData`, generated corpora under `script_export`, and other historical `work/poc` paths. Personal emulator references in the publication copy use `local_data/rpcs3`; the sample save directory is `BLJS10335_OMI-SCN_EXAMPLE`. Supply isolated fixtures and adapt those developer tests to your own paths.

Do not run an installer or integration script against your only game/save copy. Keep game material and generated reports outside Git. `work`, `local_data`, `script_export`, and local settings are ignored.
