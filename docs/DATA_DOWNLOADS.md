# Script and patcher data downloads

Both data bundles are available on the [Windows GUI release page](https://github.com/nutsamasan/srw-ogmd-tools/releases/tag/gui-2026-09-29), under **Assets**.

| To use | Download both files |
| --- | --- |
| Script Editor | `OGMD-Script-Editor-3.14-windows-x64.zip` and `OGMD-Script-Editor-3.14-data.zip` |
| Full English Patcher | `OGMD-Full-English-Patcher-1.6.2-windows-x64.zip` and `OGMD-Full-English-Patcher-1.6.2-data.zip` |

## Extract the matching pair together

1. Right-click the GUI ZIP and choose **Extract All**. Choose a parent folder such as `Documents/OGMD Tools`.
2. Extract its data ZIP into that **same parent folder**. Both ZIPs contain the same application-folder name, so the folders merge.
3. Open the application folder and double-click its `.exe`.

The resulting layout should be:

```text
OGMD Tools/
  OGMD-Script-Editor-3.14/
    OGMD-Script-Editor-3.14.exe
    _internal/
    assets/
    script_export/OGMD_EN_JP_20260908/
    DATA_SETUP.txt
  OGMD-Full-English-Patcher-1.6.2/
    OGMD-Full-English-Patcher-1.6.2.exe
    _internal/
    data/
    DATA_SETUP.txt
```

If you already extracted the ZIPs into different folders, copy `assets` and `script_export` from the Script Editor data folder into the folder containing its EXE. For the Full English Patcher, copy `data` beside its EXE. The data downloads contain no `edits/project.json` or personal settings, so they do not replace your saved editing project.

## Edit the script

The Script Editor data includes **430 collections and 88,751 rows** of indexed script and game text, with English, Japanese, bilingual text exports, and editable `script.json` files. The corpus reading guide is `script_export/OGMD_EN_JP_20260908/START_HERE.md`. Native fonts, preview textures, and runtime support are included.

On a fresh installation the GUI finds `assets` and `script_export/OGMD_EN_JP_20260908` beside the program. If it asks for folders, choose those locations. Use the editor to make and export corrections. The baseline corpus is preserved; the data bundle does not include a pre-existing private editing project.

To apply edits, choose your own compatible game archives or ISO. For a full English rebuild with your changes, use **Full English patcher**, browse to the Full English Patcher's `data` folder, and select **Use current editor edits**. The separate patcher can also load the `patch_edits.json` exported by the editor.

## Build an English game copy

The Full English Patcher data contains the complete **1.6.2 patch-data package**, including archive recipes, translation payloads, fonts, the embedded font/battle-text fix, and the English intro patch. Open the matching GUI and check that **Release data folder** points to the supplied `data` folder and displays `OGMD Full English 1.6.2`.

Choose your own supported **Japanese PS3 BLJS10335 01.00** ISO or complete game folder, then choose a **new output location**. Follow **Build and verify patch** and **Create English output**. A complete game ISO or disc folder is not included in the download.

## Contents and checksums

Each data ZIP includes `DATA_SETUP.txt`, `DATA_PACKAGE.json`, and `DATA_SHA256SUMS.txt`. The release's `SHA256SUMS.txt` also covers both ZIP downloads. Corpus fingerprints and patch payload hashes are preserved. Historical extraction paths in corpus provenance do not require matching folders on your computer.

These are separate game-derived data resources, including original Japanese text and official English localization material. They retain their original ownership and are not relicensed under the GPLv3 license used for the tool source.
