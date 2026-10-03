# Author's edited script example

This is nutsamasan's saved Script Editor project, shared as an example on October 4, 2026: **1,995 edited rows, 2,036 edited fields, and 183 collections**. It includes English dialogue, speaker names, battle text, game names, glossary text, and location corrections.

The complete Script Editor 3.18 ZIP includes this folder at `examples/edited-script`. You can also download the files from this repository. The example uses the English/Japanese library bundled with that editor; its source checksums are retained.

## Load the example in Script Editor

1. Extract the complete Script Editor ZIP and open `Start Script Editor.cmd`.
2. Choose **Import scripts**, then **Choose file…** and select `examples/edited-script/edits.json`.
3. Choose **Preview import** and review the changed text. For an existing editing project, **Keep current text** preserves conflicting edits; **Use imported text** selects the example's text for those conflicts.
4. Choose **Import previewed changes**. The editor saves the imported changes in its editing project. **Undo last import** is available in the import window.
5. Close the import window to read, edit, and preview the example. Use **Export edits** to save your own version.

The example is optional and is loaded through Import scripts. It does not need to be copied over your `Editor/edits/project.json` file.

## Build with the example

After importing, open **Full English patcher** and choose **Use current editor edits**. Alternatively, select this folder's `patch_edits.json` in **Editor corrections** in the standalone Full English Patcher 1.6.5. Choose your compatible Japanese PS3 BLJS10335 game copy and a new output location, then follow the patcher's build and verification steps.

`patch_edits.json` is for the patcher; `edits.json` is for Import scripts. `edited-lines.txt` is a readable list of the edited fields with stable row IDs. `example-manifest.json` records the counts, source identity, file checksums, and validation.

Import, save, reload, repeat import, undo, and the patch bundle's release compatibility were verified. This snapshot has not received a fresh RPCS3 boot test.

Game-derived text retains its original ownership and is not relicensed under the tool source's GPLv3 license.
