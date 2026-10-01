# Validation scope

This publication is a source snapshot of the versions listed in the root README. The source copy removes personal path settings, redirects references to an older sibling archive-helper directory to the included vendor modules, and replaces extracted Pilot/Mech effect descriptions with project-authored labels. The working development applications are not changed.

On 2026-09-28, all 212 Python files parsed and all 30 selected synthetic save/text/source-selection tests passed (25 save tests and 5 text/source-selection tests). The selected publication files also passed an inventory scan for excluded files, personal Windows paths, and likely credentials. The original working-source hashes remained unchanged. They do not prove absence of every possible confidential string or third-party material.

The original tool READMEs describe earlier local validation and refer to private `qa` reports. Those reports, original saves, screenshots, emulator logs, and game fixtures are not included. In-game validation statements must be read per feature and version; offline checks are not gameplay acceptance.

The original source snapshot did not include a new RPCS3 boot or rebuilt binary validation. Subsequent release validation is listed below.

## Title cards: Script Editor 3.16 / Full English Patcher 1.6.3

All 107 local Script Editor regression tests passed, including title-card save/import/export, old-library edit preservation, stale-review rejection and a disposable ISO write/readback. Every packaged English/Japanese sheet round-tripped to its verified native DDS hash.

For the bundled S084 correction, the 1.6.2 Common archive was reconstructed from its verified release recipe, then rebuilt with exactly one replacement. All 1,171 other decoded entries and the original 918 saved text edits were preserved. The new recipe reproduced the target archive exactly, with the original archive size and all SDAT blocks verified. Other patch payloads are unchanged.

The title reads VAUGHT AND FAIRY in the offline editor preview, using original letter pixels in all six animation layers. No fresh RPCS3 boot, animation acceptance, full playthrough or physical PS3 validation is claimed for this correction.
