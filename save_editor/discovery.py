"""Small, read-only search of known RPCS3 save roots."""
from pathlib import Path
import json
import sys
from ogmd_save import load_save, SaveFormatError, SCENARIO_PREFIX


def discover_saves():
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    settings = here / "locations.json"
    roots = json.loads(settings.read_text(encoding="utf8")) if settings.is_file() else []
    repo = here.parent
    roots += [str(repo / "native_eboot_test/runtime/dev_hdd0/home/00000001/savedata"),
              str(repo / "work/rpcs3_runtime_stage000_english_test/dev_hdd0/home/00000001/savedata")]
    found = []
    seen = set()
    for priority, root in enumerate(roots):
        for path in Path(root).glob(SCENARIO_PREFIX + "*"):
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                save = load_save(path)
                modified = (path / "SYSDATA.SAV").stat().st_mtime_ns
                suffix = path.name[len(SCENARIO_PREFIX):]
                slot_order = -int(suffix) if suffix.isdigit() else 0
                found.append((priority, -modified, slot_order, save))
            except (OSError, ValueError, SaveFormatError):
                continue
    return [record[-1] for record in sorted(found, key=lambda r: (r[0], r[1], r[2]))]
