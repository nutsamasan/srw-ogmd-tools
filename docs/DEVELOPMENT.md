# Setup and development

Use Windows and Python 3.13 for the initial source release. The desktop editors use Tkinter or PySide6. The existing build scripts share the virtual environment at `script_editor/.venv`.

From the repository root:

```powershell
py -3.13 -m venv script_editor/.venv
./script_editor/.venv/Scripts/python.exe -m pip install -r script_editor/requirements.txt
```

## Portable tests

These tests construct disposable synthetic data and do not need personal saves or game archives:

```powershell
Push-Location save_editor
../script_editor/.venv/Scripts/python.exe -m unittest -v test_ogmd_save test_safety
Pop-Location
Push-Location script_editor
./.venv/Scripts/python.exe -m unittest -v test_dialogue_capacity test_full_source
Pop-Location
```

The broader `test_*.py`, `qa_*.py`, and `verify_*.py` files preserve the project's existing tests and investigations. Many require local data described in `LOCAL_DATA.md`; full test discovery on a bare checkout is not a supported test command yet. Some integration tests read fixtures at module import time. Do not infer that a missing-data failure is a test pass.

## Entry points

| Application | Command after dependency setup |
| --- | --- |
| Save Editor | `./script_editor/.venv/Scripts/python.exe save_editor/save_editor.py` |
| Pilot Editor | `./script_editor/.venv/Scripts/python.exe pilot_editor/app.py` |
| Mech Skill Patcher | `./script_editor/.venv/Scripts/python.exe mech_skill_patcher/app.py` |
| Script Editor | `./script_editor/.venv/Scripts/python.exe script_editor/app.py --corpus <local-corpus-folder>` |
| Full English Patcher | `./script_editor/.venv/Scripts/python.exe script_editor/full_app.py --data <local-release-data-folder>` |

The last two applications need excluded game-derived resources. See `LOCAL_DATA.md` before running them.

## Building Windows programs

To reproduce the public GUI ZIPs, run this command from a clean checkout after installing the pinned dependencies:

```powershell
./script_editor/.venv/Scripts/python.exe tools/build_windows_release.py
```

Outputs are under `dist/windows`. Use `--tool save`, `pilot`, `mech`, `script`, or `full` to build one program. `--output <folder>` selects a different output directory. The public build recipe uses PyInstaller's folder layout, bundles only listed catalogs, copies license notices, records the source commit, and produces ZIPs and SHA-256 checksums. It does not require native game assets to build.

The individual `build.ps1` scripts retain the older local one-file packaging workflow. In particular, `script_editor/build.ps1` expects private preview and runtime resources; it is not the public release recipe.

Before uploading a binary, build from a recorded source revision, inspect the package for game assets and personal settings, test a clean extraction, and publish its SHA-256 checksum. The Save Editor and the two Qt programs accept `--startup-check <new-report.json>` for a startup-only check. Pilot Editor and Mech Skill Patcher accept `--check <new-report.json>`. These checks do not edit game data. Test local resource selection with `python -m unittest test_local_resources` from `script_editor`.

## Research scripts

`tools/` retains the project's extraction, patch-building, inspection, and verification scripts. These are developer utilities with documented or in-code local staging paths, not a single automated installation pipeline. Several install/repair scripts write to the selected local game or runtime. Inspect their inputs and use isolated copies when experimenting.
