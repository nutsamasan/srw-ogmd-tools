# Windows GUI downloads

Open [the latest release](https://github.com/nutsamasan/srw-ogmd-tools/releases/latest) and expand **Assets**. Download the ZIP for the tool you want. The files called **Source code** are for development; choose a file ending in **windows-x64.zip** to run a GUI.

| Download | Included program | Required local input |
| --- | --- | --- |
| `OGMD-Save-Editor-1.6-windows-x64.zip` | Save Editor 1.6 | Your supported RPCS3 save; compatible game archive for native weapon editing |
| `OGMD-Pilot-Editor-1.1-windows-x64.zip` | Pilot Editor 1.1 | Your compatible game archive or supported save |
| `OGMD-Mech-Skill-Patcher-1.0-windows-x64.zip` | Mech Skill Patcher 1.0 | Your compatible game archive |
| `OGMD-Script-Editor-3.14-windows-x64.zip` | Script Editor 3.14 | Your generated script corpus and native preview resources |
| `OGMD-Full-English-Patcher-1.6.2-windows-x64.zip` | Full English Patcher 1.6.2 | Your compatible, locally prepared full-English release-data folder |

1. On 64-bit Windows 10 or 11, right-click the ZIP and choose **Extract All**.
2. Open the extracted folder and double-click its `.exe`.
3. Keep the `_internal` folder beside the program. Python is included; no separate installation is needed.
4. Choose your own files in the GUI. Keep backups and close the game before saving edits.

The Script Editor asks for local preview resources if it cannot find them, then asks for the script corpus. The Full English Patcher opens its GUI and lets you choose a release-data folder. Neither package includes game files or an English translation payload. See [local data requirements](LOCAL_DATA.md) for the expected files and preparation scripts.

Each ZIP includes `START_HERE.txt`, the project license, dependency notices, and `BUILD_INFO.json` identifying its source commit. SHA-256 hashes are listed in `SHA256SUMS.txt` on the release page.
