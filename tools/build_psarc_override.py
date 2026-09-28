#!/usr/bin/env python3
"""Rebuild one PSARC while replacing only the explicitly named entries."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import types
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_psarc_module(module_path: Path):
    spec = importlib.util.spec_from_file_location("ogmd_psarc", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load PSARC module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("entry")
    parser.add_argument("replacement", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--psarc-module", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--also-replace", nargs=2, action="append", default=[],
                        metavar=("ENTRY", "FILE"), help="additional entry override in the same rebuild")
    parser.add_argument(
        "--zopfli",
        action="store_true",
        help="use exhaustive zlib-compatible compression for the replacement",
    )
    parser.add_argument(
        "--exact-source-size",
        action="store_true",
        help="pad a smaller rebuild back to the source PSARC size",
    )
    args = parser.parse_args()

    module = load_psarc_module(args.psarc_module)
    archive = module.Psarc(args.source)
    names = {item.name for item in archive.entries}
    if args.entry not in names:
        close = [name for name in sorted(names) if args.entry.lower() in name.lower()]
        raise ValueError(f"entry not found: {args.entry}; similar entries: {close[:10]}")

    replacement = args.replacement.read_bytes()
    overrides = {args.entry: replacement}
    for name, filename in args.also_replace:
        if name not in names or name in overrides:
            raise ValueError(f"Missing or duplicate additional entry: {name}")
        overrides[name] = Path(filename).read_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.zopfli:
        import zopfli.zlib

        def compress_file_zopfli(self, data):
            blocks = []
            maximum_compressed = (1 << (8 * self.bt_width)) - 1
            for position in range(0, len(data), self.block_size):
                chunk = data[position : position + self.block_size]
                compressed = zopfli.zlib.compress(chunk, numiterations=25)
                if len(compressed) < len(chunk) and len(compressed) <= maximum_compressed:
                    blocks.append((len(compressed), compressed))
                elif len(chunk) == self.block_size:
                    blocks.append((0, chunk))
                else:
                    blocks.append((len(chunk), chunk))
            if not blocks:
                blocks.append((0, b""))
            return blocks

        archive._compress_file = types.MethodType(compress_file_zopfli, archive)

    archive.pack(args.output, overrides=overrides)
    if args.exact_source_size:
        padding = args.source.stat().st_size - args.output.stat().st_size
        if padding < 0:
            raise ValueError(
                f"rebuilt PSARC exceeds source by {-padding} bytes even after compression"
            )
        archive.pack(
            args.output,
            overrides=overrides,
            pad_after=(args.entry, padding),
        )

    rebuilt = module.Psarc(args.output)
    entry = next(item for item in rebuilt.entries if item.name == args.entry)
    extracted = rebuilt._read_file(entry)
    if extracted != replacement:
        raise ValueError("rebuilt PSARC does not reproduce the replacement bytes")
    for name, expected in overrides.items():
        item = next(item for item in rebuilt.entries if item.name == name)
        if rebuilt._read_file(item) != expected:
            raise ValueError(f"Re-extraction mismatch: {name}")

    report = {
        "format": "single-entry PSARC override" if len(overrides) == 1 else "multi-entry PSARC override",
        "source": str(args.source.resolve()),
        "source_size": args.source.stat().st_size,
        "source_sha256": sha256(args.source),
        "entry": args.entry,
        "replacement": str(args.replacement.resolve()),
        "replacement_size": len(replacement),
        "replacement_sha256": hashlib.sha256(replacement).hexdigest().upper(),
        "output": str(args.output.resolve()),
        "output_size": args.output.stat().st_size,
        "output_sha256": sha256(args.output),
        "compression": "zopfli" if args.zopfli else "zlib-9",
        "exact_source_size": args.output.stat().st_size == args.source.stat().st_size,
        "roundtrip_verified": True,
        "overrides": [dict(entry=name, size=len(data), sha256=hashlib.sha256(data).hexdigest().upper())
                      for name, data in overrides.items()],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
