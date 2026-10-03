# Complete tool packages

Download **one ZIP per tool** from [Releases](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-10-03). The programs and their data are together. No separate data download, folder merging, or Python installation is needed.

| Tool | Complete download | Open after extracting the entire ZIP |
| --- | --- | --- |
| Script Editor | `OGMD-Script-Editor-3.18-windows-x64.zip` | `Start Script Editor.cmd` |
| Full English Patcher | `OGMD-Full-English-Patcher-1.6.5-windows-x64.zip` | `OGMD-Full-English-Patcher-1.6.5.exe` |

## Script Editor

The package includes the editor, **430 collections and 88,751 rows** of indexed English/Japanese script and game text, bilingual exports, preview resources, runtime support, and the complete Full English Patcher 1.6.5 data used by its built-in patcher buttons.

Right-click the ZIP, choose **Extract All**, then double-click `Start Script Editor.cmd`. Keep these folders together:

```text
OGMD-Script-Editor-3.18/
  Start Script Editor.cmd
  START_HERE.txt
  examples/edited-script/
  Editor/
    OGMD-Script-Editor-3.18.exe
    _internal/
    assets/
    script_export/OGMD_EN_JP_20260908/
  full_patcher/
    data/
```

You can also open `Editor/OGMD-Script-Editor-3.18.exe` directly. It finds its corpus and preview resources automatically. The script-reading guide is `Editor/script_export/OGMD_EN_JP_20260908/START_HERE.md`.

Use the GUI to edit and export corrections. To apply edits, choose your own compatible game archives or ISO. For a full English rebuild with your changes, use **Full English patcher** and **Use current editor edits**. Its release-data folder is already included and selected; the **Embed font / battle text fix** workflow uses the same included data.

The package includes the author's optional edited script example under `examples/edited-script`: 1,995 edited rows across 183 collections. Use **Import scripts → Choose file…**, select `examples/edited-script/edits.json`, review **Preview import**, then import the changes. See the [example guide](../examples/edited-script/README.md) for conflict handling and patching. `patch_edits.json` can also be selected directly in the Full English Patcher's **Editor corrections** field.

If upgrading an existing installation, preserve your `edits` folder; the public package's editing workspace is under `Editor/edits`. The example is imported explicitly, and personal path settings are not included.

## Full English Patcher

Extract its ZIP and open `OGMD-Full-English-Patcher-1.6.5.exe`. Keep `_internal` and `data` beside it. The complete 1.6.5 data includes archive recipes, translation payloads, metadata, fonts, embedded font/battle-text fixes, and the English intro patch. The GUI detects this data automatically.

Choose your own supported **Japanese PS3 BLJS10335 01.00** ISO or complete game folder, then choose a **new output location**. Follow **Build and verify patch** and **Create English output**. A complete game ISO or disc folder is not included.

## Package information

Both packages include `START_HERE.txt`, `PACKAGE_INFO.json`, and `DATA_SHA256SUMS.txt`. The release's `SHA256SUMS.txt` covers the complete ZIPs. Program binaries are retained from the verified GUI builds; `BUILD_INFO.json` records their source revision. `PACKAGE_INFO.json` identifies the packaging recipe and its input hashes. Corpus and patch payload fingerprints are preserved.

Game-derived script, translation, and support resources retain their original ownership and are not relicensed under the GPLv3 license used for the tool source.
