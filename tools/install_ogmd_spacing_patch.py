"""Install/roll back the verified spacing experiment in the isolated runtime.

This changes files for the next RPCS3 launch. It never controls the emulator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from build_ogmd_spacing_patch import ROOT, OUT, PPU_HASH, PATCH_NAME, PATCH_FILE, GAME_NAME
import yaml

RUNTIME = ROOT / "work/rpcs3_runtime_stage000_english_test"
BACKUP = ROOT / "work/backups/text_layout_20260905/spacing_v2"
MANIFEST = ROOT / "reports/ogmd_spacing_v2_install_20260905.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".ogmd-spacing.tmp")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    assert path.read_bytes() == data


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            assert digest(Path(item["path"]).read_bytes()) == item["after_sha256"], "Configuration changed; do not overwrite later edits"
            assert digest(Path(item["backup"]).read_bytes()) == item["before_sha256"]
        for item in manifest["files"]:
            atomic_write(Path(item["path"]), Path(item["backup"]).read_bytes())
        print("Previous spacing build restored. The working line-break fix remains installed. Restart RPCS3 manually.")
        return

    verification = json.loads((OUT / "verification_report.json").read_text(encoding="utf-8"))
    assert verification["hooks"] == 12 and verification["hook_executions"] == 2424
    line_verification = json.loads((OUT / "line_measurement_report.json").read_text(encoding="utf-8"))
    assert line_verification["full_routine_executions"] == 34
    source = (OUT / PATCH_FILE).read_text(encoding="utf-8")
    patch = yaml.safe_load(source)
    assert patch[PPU_HASH][PATCH_NAME]["Games"][GAME_NAME]["BLJS10335"] == ["01.00"]
    patch_path = RUNTIME / "patches/imported_patch.yml"
    config_path = RUNTIME / "config/patch_config.yml"
    config_entry = {PPU_HASH: {PATCH_NAME: {GAME_NAME: {"BLJS10335": {"01.00": {"Enabled": True}}}}}}
    old_name = "OGMD English dialogue native spacing v1"
    old_patch = yaml.safe_load((OUT.parent / "spacing_v1/ogmd_native_spacing_v1.yml").read_text(encoding="utf-8"))
    old_config = {PPU_HASH: {old_name: {GAME_NAME: {"BLJS10335": {"01.00": {"Enabled": True}}}}}}
    additions = [source[source.index(PPU_HASH + ":"):], yaml.safe_dump(config_entry, sort_keys=False)]
    changes = []
    for path, addition in zip([patch_path, config_path], additions):
        before = path.read_bytes()
        text = before.decode("utf-8-sig")
        previous = yaml.safe_load(text)
        old_section = (old_patch if path == patch_path else old_config)[PPU_HASH]
        assert previous.get(PPU_HASH) == old_section, f"Expected enabled v1 configuration in {path}"
        start = before.index((PPU_HASH + ":").encode("utf-8"))
        assert yaml.safe_load(before[start:]) == {PPU_HASH: old_section}, "Unexpected trailing configuration"
        after = before[:start] + addition.encode("utf-8")
        parsed = yaml.safe_load(after.decode("utf-8-sig"))
        added = parsed.pop(PPU_HASH)
        previous.pop(PPU_HASH)
        assert parsed == previous, "Existing patches changed"
        assert added == (patch if path == patch_path else config_entry)[PPU_HASH]
        changes.append((path, before, after))

    BACKUP.mkdir(parents=True, exist_ok=True)
    records = []
    for path, before, after in changes:
        backup = BACKUP / (path.name + ".before")
        if backup.exists():
            assert backup.read_bytes() == before
        else:
            backup.write_bytes(before)
        records.append(dict(path=str(path), backup=str(backup), before_sha256=digest(before), after_sha256=digest(after)))
    for path, before, _ in changes:
        assert path.read_bytes() == before, "Configuration changed during preparation"
    applied = []
    try:
        for path, before, after in changes:
            atomic_write(path, after)
            applied.append((path, before))
    except Exception:
        for path, before in reversed(applied):
            atomic_write(path, before)
        raise
    manifest = dict(installed_utc=datetime.now(timezone.utc).isoformat(), patch_name=PATCH_NAME,
                    ppu_hash=PPU_HASH, game_version="01.00", files=records,
                    patch_sha256=digest(source.encode("utf-8")),
                    verification=verification, line_verification=line_verification,
                    status="v2 installed and enabled for next RPCS3 launch; v1 replaced; user visual test pending")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
