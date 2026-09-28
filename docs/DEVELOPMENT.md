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

The Save, Pilot, and Mech folders each contain `build.ps1`. Run the relevant script with PowerShell after preparing the shared environment. The Script Editor's build also needs its preview resources and `assets/runtime` files. The full-patcher packaging scripts are under `tools/` and retain local staging requirements.

This initial publication verifies source portability with the portable suite; it does not rebuild or certify every Windows package. Before uploading a binary, rebuild from a recorded source revision, supply dependency notices, inspect the package for game assets and personal paths, test a clean extraction, and publish a SHA-256 checksum beside it.

## Research scripts

`tools/` retains the project's extraction, patch-building, inspection, and verification scripts. These are developer utilities with documented or in-code local staging paths, not a single automated installation pipeline. Several install/repair scripts write to the selected local game or runtime. Inspect their inputs and use isolated copies when experimenting.
