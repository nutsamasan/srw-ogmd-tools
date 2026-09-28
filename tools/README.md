# Developer and research utilities

These scripts preserve the project's localization, archive, executable-patching, and debugging work. They expect local data/intermediate products; see `../docs/LOCAL_DATA.md`.

Read each script before running it. Names beginning with `install_`, `repair_`, `stage_`, or `package_` may write to game/runtime/staging folders. They are not automatic startup actions. Several inspection tools need saved RPCS3 captures; live process capture is explicitly selected by the operator.

Optional research dependencies are in `requirements-research.txt`. The core desktop tools use the requirements documented at the repository root.
