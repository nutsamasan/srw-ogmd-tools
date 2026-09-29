# Dependency licenses and source downloads

The application code is GPLv3. The Windows packages contain unmodified upstream runtime libraries under their respective licenses. See the included `licenses` folder for upstream license texts and notices, and `BUILD_INFO.json` for exact build versions. Qt/PySide use their open-source licensing options; no commercial Qt license is needed for this GPLv3 project.

## Corresponding source

The project's exact source commit is linked in each package's `START_HERE.txt` and recorded in `BUILD_INFO.json`. The release's **Source code** downloads include the application and `tools/build_windows_release.py` build recipe. [Development instructions](DEVELOPMENT.md) describe dependency installation and rebuilding. The release also supplies **Dependency-Sources-2026-09-29.zip**, an unchanged mirror of the source archives below, with original URLs and SHA-256 hashes in `SOURCES.json`.

| Dependency | Version | Original source |
| --- | --- | --- |
| Python | 3.13.7 | [Python source](https://www.python.org/ftp/python/3.13.7/Python-3.13.7.tar.xz) |
| Tcl/Tk | 8.6.15 | [Tcl source](https://www.tcl-lang.org/software/tcltk/download.html) and [CPython's build instructions](https://github.com/python/cpython/blob/v3.13.7/PCbuild/readme.txt) |
| PySide6 and Shiboken6 | 6.11.2 | [Qt for Python source](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz) |
| Qt Core, GUI, Widgets, Network, OpenGL and platform plugins | 6.11.2 | [Qt Base source](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz) |
| Qt SVG | 6.11.2 | [Qt SVG source](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtsvg-everywhere-src-6.11.2.tar.xz) |
| Qt image format plugins | 6.11.2 | [Qt Image Formats source](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtimageformats-everywhere-src-6.11.2.tar.xz) |
| Qt translations | 6.11.2 | [Qt Translations source](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qttranslations-everywhere-src-6.11.2.tar.xz) |
| Pillow | 12.3.0 | [Pillow source distribution](https://pypi.org/project/pillow/12.3.0/#files) |
| PyCryptodome | 3.23.0 | [PyCryptodome source distribution](https://pypi.org/project/pycryptodome/3.23.0/#files) |
| Zopfli | 0.4.3 | [Zopfli source distribution](https://pypi.org/project/zopfli/0.4.3/#files) |
| PyYAML | 6.0.3 | [PyYAML source distribution](https://pypi.org/project/PyYAML/6.0.3/#files) |
| PyInstaller bootloader and build tools | 6.22.2 | [PyInstaller source distribution](https://pypi.org/project/pyinstaller/6.22.2/#files) |

Qt and PySide source archives include their build scripts and third-party source/attribution files. The license collection in this repository preserves upstream notices from those archives. Sources mirrored in the dependency ZIP exclude Python and Tcl/Tk; their source links are listed above.

## Replacing or modifying libraries

The GUI downloads use PyInstaller's **onedir** layout. Shared libraries are ordinary files under `_internal`, with Qt/PySide libraries under `_internal/PySide6`; they are not sealed inside a one-file executable. You may replace them with compatible modified builds under their licenses, or rebuild the application using your modified Python environment. Keep ABI-compatible versions and preserve the package's directory layout. Reverse engineering for debugging modifications to LGPL-covered components is permitted under their licenses.

For the public Qt builds, the build recipe removes the unused PDF image plugin and virtual-keyboard plugin, plus their QtPdf/QML/Quick libraries. The remaining GUI uses Qt Widgets. Windows platform and offscreen plugins remain available.

PyInstaller's bootloader uses its distribution exception; its license is included with the packages. Python, Tcl/Tk, Pillow, PyCryptodome, Zopfli and PyYAML keep their upstream terms. This document does not grant rights to game assets.
