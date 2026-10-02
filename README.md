# SRW OG Moon Dwellers Tools

Community editors and patching tools for **Super Robot Wars OG: The Moon Dwellers**, maintained by [nutsamasan](https://github.com/nutsamasan).

The tools target the Japanese PS3 release **BLJS10335**, primarily used with RPCS3 on Windows. They help edit saves, adjust supported gameplay settings, work on dialogue, and build English patches using the downloadable patch data and your own compatible game copy.

## Included tools

| Tool | Source version | Purpose |
| --- | --- | --- |
| [Save Editor](save_editor/README.md) | 1.6 | Save editing, pilot skills and status, mech abilities, and native weapon settings |
| [Pilot Editor](pilot_editor/README.md) | 1.1 | Spirit Commands, Will behavior profiles, and current saved Will |
| [Mech Skill Patcher](mech_skill_patcher/README.md) | 1.0 | Built-in mech skill assignments, original defaults, and backup restoration |
| [Script Editor](script_editor/README.md) | 3.17 | English/Japanese text and stage-title artwork editing, archive/ISO patching |
| [Full English Patcher](full_patcher/README.md) | 1.6.4 | Full translation builds and embedded font/battle-caption fixes |

**New in Script Editor 3.17 / Full English Patcher 1.6.4:** stage title-card preview and PNG editing, plus the native-pixel S084 correction to **VAUGHT AND FAIRY**. Complete downloads include the corrected library and patch data.

The Full English Patcher's application source is `script_editor/full_app.py` and its related modules. It shares code with the Script Editor.

## Windows GUI downloads

Download the ready-to-run **Windows 64-bit GUI ZIPs** from [Releases](https://github.com/nutsamasan/srw-ogmd-tools/releases/latest). Extract the entire ZIP, open its folder, and double-click the editor's `.exe`. Keep the `_internal` folder beside the program. No Python installation is needed.

All five tools have separate downloads: Save Editor, Pilot Editor, Mech Skill Patcher, Script Editor, and Full English Patcher. See [download and launch instructions](docs/WINDOWS_DOWNLOADS.md).

**Each tool is one complete ZIP with its data included.** The Script Editor includes the English/Japanese corpus, preview resources, and data for its built-in Full English Patcher. After extraction, double-click `Start Script Editor.cmd`. The standalone Full English Patcher includes its complete 1.6.4 data beside the EXE. The Save, Pilot, and Mech tools include their support catalogs. See [setup instructions](docs/DATA_DOWNLOADS.md).

Patching still requires your own compatible game copy. Complete Windows packages are release attachments; cloning the source repository alone does not download their data.

See [setup and development](docs/DEVELOPMENT.md), [local data requirements](docs/LOCAL_DATA.md), and [validation scope](docs/VALIDATION.md).

## Quick start from source

Install Python 3.13 on Windows with Tkinter available. In PowerShell, from the repository folder:

```powershell
py -3.13 -m venv script_editor/.venv
./script_editor/.venv/Scripts/python.exe -m pip install -r script_editor/requirements.txt
./script_editor/.venv/Scripts/python.exe save_editor/save_editor.py
```

Launch the other gameplay tools with:

```powershell
./script_editor/.venv/Scripts/python.exe pilot_editor/app.py
./script_editor/.venv/Scripts/python.exe mech_skill_patcher/app.py
```

Choose your own save/archive paths in the application. Use a backup and a disposable copy for your first edit. Exit the game before saving changes, then start the game fresh and use its normal Load menu. See each tool's README for supported fields and restoration options.

Source installation dependencies are listed in `script_editor/requirements.txt`; the smaller `save_editor/requirements.txt` supports the Save Editor's archive editing without the Qt tools.

## Compatibility

PS4 saves and physical PS3 execution/signing are not supported by these releases. Strict format and fingerprint checks are intentional: unsupported game data should be rejected rather than modified speculatively.

## Contributing

Bug reports, documentation improvements, and code changes are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md). Describe the tool version, game revision, expected result, and actual result. Remove personal paths and account details from diagnostic excerpts.

## License and credits

Project source code is released under **GNU GPL version 3**; see [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). The SDAT implementation credits Hykem's `make_npdata`; original credits are retained. Dependencies keep their own licenses.

Game names, character names, trademarks, and other third-party material remain associated with their respective owners. The software license grants no rights to redistribute the game, its official translation, fonts, artwork, movies, or other game assets. This is an unofficial community project.

Pilot Development description clipping is corrected in Script Editor 3.17 and Full English Patcher 1.6.4. All ten stat/terrain descriptions retain both lines; confirmed in RPCS3.
