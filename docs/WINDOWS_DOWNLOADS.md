# Windows GUI downloads

Open [the latest release](https://github.com/nutsamasan/srw-ogmd-tools/releases/latest) and expand **Assets**. Download the ZIP for the tool you want. The files called **Source code** are for development; choose a file ending in **windows-x64.zip** to run a GUI.

| Download | Included program | Required local input |
| --- | --- | --- |
| `OGMD-Save-Editor-1.6-windows-x64.zip` | Save Editor 1.6 | Your supported RPCS3 save; compatible game archive for native weapon editing |
| `OGMD-Pilot-Editor-1.1-windows-x64.zip` | Pilot Editor 1.1 | Your compatible game archive or supported save |
| `OGMD-Mech-Skill-Patcher-1.0-windows-x64.zip` | Mech Skill Patcher 1.0 | Your compatible game archive |
| `OGMD-Script-Editor-3.14-windows-x64.zip` | Script Editor 3.14 | Matching `OGMD-Script-Editor-3.14-data.zip`; your game files when applying edits |
| `OGMD-Full-English-Patcher-1.6.2-windows-x64.zip` | Full English Patcher 1.6.2 | Matching `OGMD-Full-English-Patcher-1.6.2-data.zip`; your supported Japanese game copy |

1. On 64-bit Windows 10 or 11, right-click the ZIP and choose **Extract All**.
2. Open the extracted folder and double-click its `.exe`.
3. Keep the `_internal` folder beside the program. Python is included; no separate installation is needed.
4. Choose your own files in the GUI. Keep backups and close the game before saving edits.

For the Script Editor and Full English Patcher, download the matching **data ZIP** as well. Extract the GUI and data ZIPs into the **same parent folder** so their identically named application folders merge. The Script Editor then finds its corpus/preview resources, and the Full English Patcher finds its release data. See the [step-by-step data setup guide](DATA_DOWNLOADS.md). You still need your own supported game copy to apply a patch.

Each GUI ZIP includes `START_HERE.txt`, the project license, dependency notices, and `BUILD_INFO.json` identifying its source commit. Each data ZIP includes `DATA_SETUP.txt`, `DATA_PACKAGE.json`, and per-file checksums. SHA-256 hashes for all downloads are listed in `SHA256SUMS.txt` on the release page. The original GUI ZIPs remain unchanged; their note about supplying data is fulfilled by these separate downloads.
