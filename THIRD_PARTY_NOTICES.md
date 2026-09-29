# Third-party notices and provenance

## SDAT support

The `vendor/sdat.py` implementations in the Script Editor, Pilot Editor, Mech Skill Patcher, and Save Editor weapon module describe themselves as Python ports of the algorithm in **make_npdata by Hykem**, cross-checked against RPCS3's `rpcs3/Crypto/unedat.cpp`.

The published make_npdata source carries GPLv3:

- https://github.com/aniruddh22/make_npdata
- https://github.com/aniruddh22/make_npdata/blob/master/LICENSE
- https://github.com/ErikPshat/make_npdata-hykem

Upstream credits also name JuanNadie for the original EDAT algorithm implementation and research; flat_z for rap2rifkey; and Snowydew, KDSBest, and qoobz for EDAT tools and source.

These Python modules are modified implementations, not unmodified upstream files. Their OGMD adaptations and source-publication preparation were made by this project in 2026. They preserve the original module-level attribution. The project uses GPLv3 for these ports and compatible project code.

RPCS3 is a verification reference named by the existing modules. RPCS3 generally uses GPL-2.0-only with exceptions for individual files. This repository does not bundle the RPCS3 source checkout or binary, and this notice does not relicense RPCS3 code. Any future copied RPCS3 implementation must have its own license compatibility reviewed.

## Python dependencies

Dependencies are installed separately for source use. The Windows GUI ZIPs include the runtime components needed by their applications and a `licenses` folder. Runtime and packaging dependencies include Python/Tkinter, PySide6/Qt, Pillow, PyCryptodome, Zopfli, PyYAML, and PyInstaller. Some research scripts additionally use NumPy, Zstandard, PyAV, Capstone, Keystone, and Unicorn; see `tools/requirements-research.txt`.

The public Windows packages are rebuilt from the published source with `tools/build_windows_release.py`. Their `BUILD_INFO.json` records versions and the source commit. See [dependency sources](docs/DEPENDENCY_SOURCES.md) for upstream source downloads and license details. Qt/PySide libraries use their open-source licensing options; Qt's commercial-license text, if present in wheel metadata, is an upstream alternative and is not the licensing option used for these downloads.

## Game metadata

Small catalogs describe native identifiers, names, numeric defaults, growth tables, and compatibility hashes. They support format identification and editing; they are not game archives. Extracted prose effect descriptions in the Pilot and Mech catalogs have been replaced with short project-authored notices in this public source copy. Original numerical defaults and structural fingerprints are retained.

The source license applies to project code and original documentation, not to third-party game content or trademarks. Complete Windows packages include the English/Japanese corpus, native preview resources, and translation/support payloads required by their tools. These game-derived resources retain their original ownership and are not relicensed as GPLv3. They remain outside the source repository. A complete game ISO or disc folder is not distributed with these tools.
