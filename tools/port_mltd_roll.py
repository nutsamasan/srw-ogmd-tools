#!/usr/bin/env python3
"""Port an official MLTD overlay into a native OGMD Roll CSB string pool.

Command 19 stores the displayed text at argument 3 and its MLTD physical
index at argument 13. Use those authored IDs, never the order of Japanese
strings: Roll_20 skips MLTD entry 10. CSB line breaks remain LF.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from port_mltd_stage import parse_mltd, read_cstring, sha256


def parse_csb(data: bytes):
    if data[:8] != b"CSB \xfe\xff\x01\x00":
        raise ValueError("Unsupported CSB header")
    chunks = {}
    position = 0x18
    while position < len(data):
        tag, size, count = struct.unpack_from(">4sII", data, position)
        if size < 12 or position + size > len(data) or tag in chunks:
            raise ValueError("Invalid or duplicate CSB chunk")
        chunks[tag] = (position, size, count)
        position += size
    if position != len(data) or list(chunks) != [b"STRP", b"LNP ", b"LNT "]:
        raise ValueError("Unsupported CSB chunk layout")
    sp, ss, sc = chunks[b"STRP"]
    strings = {}
    position = sp + 12
    for _ in range(sc):
        text = read_cstring(data, position)
        strings[position] = text
        position += len(text.encode("utf-8")) + 1
    # Some shipped Archive CSBs leave up to three uninitialized alignment
    # bytes after the declared strings (including non-UTF8 bytes). These are
    # not strings. Longer reserved space must remain zero-filled.
    if position > sp + ss or (sp + ss - position >= 4 and any(data[position:sp + ss])):
        raise ValueError("STRP count or trailing padding is invalid")
    lp, ls, lc = chunks[b"LNP "]
    tp, ts, tc = chunks[b"LNT "]
    if lc != tc or struct.unpack_from(">I", data, 0x14)[0] != tc or ts != 12 + tc * 4:
        raise ValueError("Inconsistent CSB command counts")
    records = []
    for r in struct.unpack_from(f">{tc}I", data, tp + 12):
        if not lp + 12 <= r <= lp + ls - 8:
            raise ValueError("Command record is outside LNP")
        n, ptr = struct.unpack_from(">II", data, r)
        if ptr != r + 8 or ptr + n * 4 > lp + ls:
            raise ValueError("Invalid command parameter array")
        pointers = list(struct.unpack_from(f">{n}I", data, ptr))
        if any(p not in strings for p in pointers):
            raise ValueError("Command refers outside the STRP string boundaries")
        records.append(dict(offset=r, pointer_array=ptr, pointers=pointers,
                            arguments=[strings[p] for p in pointers]))
    return chunks, strings, records


def port_roll(source: bytes, mltd: bytes, command="19", text_argument=3, id_argument=13):
    chunks, strings, records = parse_csb(source)
    entries, meta = parse_mltd(mltd)
    replacements = {}
    rows = []
    selected_fields = set()
    for record in records:
        args = record["arguments"]
        if not args or args[0] != command:
            continue
        if len(args) <= max(text_argument, id_argument):
            raise ValueError("Unsupported text command argument count")
        index = int(args[id_argument])
        if not 0 <= index < len(entries):
            raise ValueError("Text command MLTD index is out of bounds")
        offset = record["pointers"][text_argument]
        english = entries[index].text
        if replacements.setdefault(offset, english) != english:
            raise ValueError("Shared CSB string has conflicting English variants")
        selected_fields.add(record["pointer_array"] + text_argument * 4)
        rows.append(dict(record_offset=record["offset"], mltd_physical_index=index,
                         old_offset=offset, japanese=strings[offset], english=english))
    if not rows:
        raise ValueError("No localized text commands")
    for record in records:
        for index, offset in enumerate(record["pointers"]):
            if offset in replacements and record["pointer_array"] + index * 4 not in selected_fields:
                raise ValueError("A displayed string also serves as a control argument")

    sp, ss, _ = chunks[b"STRP"]
    start, end = sp + 12, sp + ss
    payload = bytearray()
    new_offsets = {}
    for offset, text in strings.items():
        new_offsets[offset] = start + len(payload)
        payload.extend(replacements.get(offset, text).encode("utf-8") + b"\0")
    if len(payload) > end - start:
        raise ValueError("English STRP does not fit the original pool")
    out = bytearray(source)
    out[start:end] = payload + bytes(end - start - len(payload))
    allowed = bytearray(len(source))
    allowed[start:end] = b"\1" * (end - start)
    for record in records:
        for index, offset in enumerate(record["pointers"]):
            field = record["pointer_array"] + index * 4
            struct.pack_into(">I", out, field, new_offsets[offset])
            allowed[field:field + 4] = b"\1" * 4
    result = bytes(out)
    new_chunks, _, new_records = parse_csb(result)
    assert new_chunks == chunks and len(source) == len(result)
    for old, new in zip(records, new_records):
        expected = list(old["arguments"])
        if expected and expected[0] == command:
            expected[text_argument] = entries[int(expected[id_argument])].text
        assert new["arguments"] == expected, "A CSB command changed unexpectedly"
    assert all(a == b or allowed[i] for i, (a, b) in enumerate(zip(source, result)))
    for row in rows:
        row["new_offset"] = new_offsets[row["old_offset"]]
    report = dict(source_sha256=sha256(source), output_sha256=sha256(result),
                  mltd_sha256=sha256(mltd), source_size=len(source), output_size=len(result),
                  mapping=f"Command {command} argument {id_argument} to MLTD physical index; text argument {text_argument}",
                  line_breaks="Official LF preserved for the native CSB renderer",
                  mapped_commands=len(rows), preserved_commands=len(records) - len(rows),
                  unused_mltd_entries=[dict(index=e.physical_index, text=e.text) for e in entries
                                       if e.physical_index not in {r['mltd_physical_index'] for r in rows}],
                  mltd=meta, rows=rows, command_values_verified=True,
                  structural_bytes_preserved=True)
    return result, report


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("mltd", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--command", default="19")
    parser.add_argument("--text-argument", type=int, default=3)
    parser.add_argument("--id-argument", type=int, default=13)
    args = parser.parse_args()
    result, report = port_roll(args.source.read_bytes(), args.mltd.read_bytes(),
                              args.command, args.text_argument, args.id_argument)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "mltd"}}))


if __name__ == "__main__":
    main()
