#!/usr/bin/env python3
"""Materialize a PS4 MLTD text overlay into a PS3 LDBI stage file.

Moon Dwellers uses the same big-endian LDBI scenario binaries on PS3 and PS4.
The English PS4 release leaves those binaries unchanged and supplies English
strings in little-endian MLTD tables.  Scenario MLTD strings retain the same
order as the stage's fixed-stride dialogue records, so they can be applied
without fuzzy text alignment.  (The MLTD ID array is a lookup permutation, not
an LDBI string-table index.) Exact duplicate Japanese table entries also
receive the same translation when it is unambiguous. Optional PilotNickName
data supplies the displayed names for the selected story speakers.

By default, every translated string is appended to the output and only its
master-table pointer is changed.  An optional compact mode reuses a Japanese
slot only when the English text fits and no untranslated table entry shares
that slot.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MltdEntry:
    physical_index: int
    text_offset: int
    text: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def localization_hash(text: str) -> int:
    """PS4 0x1F7890: reflected CRC with the game's 0x10215681 polynomial."""
    if not text:
        return 0
    value = 0xFFFFFFFF
    for byte in text.encode('utf-8'):
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x10215681 if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def mltd_lookup(data: bytes) -> dict[int, MltdEntry]:
    """Resolve a hashed lookup key through the key-order permutation.

    Text records remain in authoring order. Sorted keys are interleaved in
    their descriptors, but refer through the separate permutation at 0x30.
    A key at descriptor i therefore selects text at lookup_ids[i].
    """
    entries, metadata = parse_mltd(data)
    base = struct.unpack_from('<I', data, 0x1C)[0]
    keys = [struct.unpack_from('<I', data, base+i*12)[0] for i in range(len(entries))]
    assert keys == sorted(keys)
    result = {}
    for i,key in enumerate(keys):
        entry = entries[metadata['lookup_ids'][i]]
        if key in result:
            assert key == 0 and entry.text == result[key].text == ''
        result[key] = entry
    return result


def read_cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError(f"string offset 0x{offset:X} is outside a {len(data)}-byte file")
    try:
        end = data.index(0, offset)
    except ValueError as exc:
        raise ValueError(f"string at 0x{offset:X} has no NUL terminator") from exc
    return data[offset:end].decode("utf-8", errors="strict")


def parse_mltd(data: bytes) -> tuple[list[MltdEntry], dict]:
    if len(data) < 0x30 or data[:4] != b"MLTD":
        raise ValueError("not an MLTD file")
    if data[4:6] != b"\xFF\xFE":
        raise ValueError(f"unsupported MLTD byte-order marker: {data[4:6].hex()}")

    count = struct.unpack_from("<I", data, 0x08)[0]
    ids_offset = 0x30
    string_data_offset = struct.unpack_from("<I", data, 0x20)[0]
    string_offsets_offset = struct.unpack_from("<I", data, 0x24)[0]
    ids_end = ids_offset + count * 4
    offsets_end = string_offsets_offset + count * 4

    if ids_end > len(data) or offsets_end > len(data):
        raise ValueError("MLTD ID or string-offset table extends past EOF")
    if string_data_offset != ids_end:
        raise ValueError(
            f"unexpected MLTD layout: strings start at 0x{string_data_offset:X}, "
            f"expected 0x{ids_end:X}"
        )
    if not string_data_offset <= string_offsets_offset < len(data):
        raise ValueError("invalid MLTD string section offsets")

    ids = struct.unpack_from(f"<{count}I", data, ids_offset)
    # Descriptions contain several NUL-terminated lines per logical entry.
    # The final 12-byte descriptors give the pointer-array address and line
    # count. Reading just `count` pointers silently shifts every entry after
    # the first multiline description.
    descriptors = struct.unpack_from("<I", data, 0x1C)[0]
    if descriptors + count * 12 != len(data):
        raise ValueError("unexpected MLTD descriptor extent")
    entries = []
    line_counts = []
    expected_pointer = string_offsets_offset
    for index in range(count):
        key, pointers, lines = struct.unpack_from("<III", data, descriptors + index * 12)
        if not lines or pointers != expected_pointer or pointers + lines * 4 > descriptors:
            raise ValueError(f"invalid MLTD line group {index}")
        text_offsets = struct.unpack_from(f"<{lines}I", data, pointers)
        if not all(string_data_offset <= p < string_offsets_offset for p in text_offsets):
            raise ValueError("MLTD text pointer outside string pool")
        entries.append(MltdEntry(index, text_offsets[0], "\n".join(read_cstring(data, p) for p in text_offsets)))
        line_counts.append(lines)
        expected_pointer += lines * 4
    if expected_pointer != descriptors:
        raise ValueError("unclaimed MLTD line pointers")

    duplicate_ids = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate MLTD entry IDs: {duplicate_ids[:12]}")

    return entries, {
        "count": count,
        "ids_offset": ids_offset,
        "string_data_offset": string_data_offset,
        "string_offsets_offset": string_offsets_offset,
        "lookup_ids_are_zero_based_permutation": sorted(ids) == list(range(count)),
        "lookup_ids": list(ids),
        "line_counts": line_counts,
    }


def parse_ldbi_table(data: bytes) -> tuple[int, int, list[int]]:
    if len(data) < 0x18 or data[:4] != b"LDBI":
        raise ValueError("not an LDBI stage file")
    count = struct.unpack_from(">I", data, 0x0C)[0]
    table_offset = struct.unpack_from(">I", data, 0x14)[0]
    table_end = table_offset + count * 4
    if table_end > len(data):
        raise ValueError(
            f"LDBI table 0x{table_offset:X}-0x{table_end:X} extends past EOF"
        )
    offsets = list(struct.unpack_from(f">{count}I", data, table_offset))
    return count, table_offset, offsets


def has_japanese(text: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30FF" or "\u3400" <= char <= "\u9FFF"
        for char in text
    )


def ps3_dialogue_text(text: str) -> str:
    """Translate PS4 MLTD line endings into the native PS3 talk marker.

    Preserve the authored wrapping and indentation; the Japanese PS3 LDBI
    strings use '@' where English MLTD strings use LF. Raw LF is not a
    working line break in the PS3 dialogue renderer.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "@")


def find_dialogue_records(
    data: bytes, source_offsets: list[int], expected_count: int
) -> tuple[list[tuple[int, int, int, str]], dict]:
    """Find the OGMD story-dialogue record grid.

    Records are 0xC4 bytes and hold the LDBI master string-table index at
    +0x0C.  Conversation blocks have gaps between them but remain on one
    global 0xC4 grid.  We group plausible dialogue records by grid residue and
    choose the expected-size window whose string-table indices score highest;
    that rejects occasional late binary words that merely resemble an index.
    """

    stride = 0xC4
    text_index_field = 0x0C
    groups: dict[int, list[tuple[int, int, int, str]]] = {}
    for record_offset in range(0, len(data) - text_index_field - 4):
        table_index = struct.unpack_from(">I", data, record_offset + text_index_field)[0]
        if table_index >= len(source_offsets):
            continue
        old_offset = source_offsets[table_index]
        try:
            old_text = read_cstring(data, old_offset)
        except (UnicodeDecodeError, ValueError):
            continue
        if not old_text.startswith(("「", "（")):
            continue
        groups.setdefault(record_offset % stride, []).append(
            (record_offset, table_index, old_offset, old_text)
        )

    windows = []
    for residue, records in groups.items():
        if len(records) < expected_count:
            continue
        for start in range(len(records) - expected_count + 1):
            window = records[start : start + expected_count]
            score = sum(record[1] for record in window)
            windows.append((score, -window[0][0], residue, window, len(records)))
    if not windows:
        counts = sorted(((len(v), k) for k, v in groups.items()), reverse=True)[:8]
        raise ValueError(
            f"could not find {expected_count} dialogue records on one 0x{stride:X} grid; "
            f"largest residue groups: {counts}"
        )

    _, _, residue, selected, residue_candidate_count = max(windows)
    return selected, {
        "record_stride": stride,
        "text_index_field": text_index_field,
        "grid_residue": residue,
        "residue_candidate_count": residue_candidate_count,
        "first_record_offset": selected[0][0],
        "last_record_offset": selected[-1][0],
    }


def port_stage(
    source: bytes,
    mltd: bytes,
    *,
    reuse_fitting_slots: bool = False,
    repack_safe_slots: bool = False,
    speaker_mltd: bytes | None = None,
    split_shared_dialogue: bool = False,
    reuse_slot_remainders: bool = False,
    supplemental_translations: list[dict] | None = None,
) -> tuple[bytes, dict]:
    if reuse_fitting_slots and repack_safe_slots:
        raise ValueError("compact placement modes are mutually exclusive")
    if reuse_slot_remainders and not repack_safe_slots:
        raise ValueError("Slot remainder reuse requires safe-slot repacking")
    entries, mltd_meta = parse_mltd(mltd)
    table_count, table_offset, source_offsets = parse_ldbi_table(source)
    dialogue_records, record_meta = find_dialogue_records(
        source, source_offsets, len(entries)
    )

    original_source = source
    original_table_count = table_count
    split_rows = []
    if split_shared_dialogue:
        # Different English variants can share one Japanese index. Extend the
        # master table only into verified zero alignment padding before the
        # next header-declared section. Existing indices/sections stay fixed.
        prepared = bytearray(source)
        variants: dict[tuple[int, str], int] = {}
        first_variants: dict[int, str] = {}
        remapped = []
        next_section = struct.unpack_from(">I", source, 0x1C)[0]
        old_table_end = table_offset + table_count * 4
        if not old_table_end <= next_section <= len(source):
            raise ValueError("Invalid next section boundary for table extension")
        if any(source[old_table_end:next_section]):
            raise ValueError("Master-table alignment padding is not all zero")
        for entry, (record_offset, table_index, old_offset, japanese) in zip(entries, dialogue_records):
            english = ps3_dialogue_text(entry.text)
            first = first_variants.setdefault(table_index, english)
            if first == english:
                new_index = table_index
            else:
                key = (table_index, english)
                if key not in variants:
                    new_index = len(source_offsets)
                    if table_offset + (new_index + 1) * 4 > next_section:
                        raise ValueError("Not enough verified padding for English variants")
                    variants[key] = new_index
                    source_offsets.append(old_offset)
                    struct.pack_into(">I", prepared, table_offset + new_index * 4, old_offset)
                new_index = variants[key]
                struct.pack_into(">I", prepared, record_offset + 0x0C, new_index)
                split_rows.append(dict(record_offset=record_offset,
                    original_table_index=table_index, new_table_index=new_index,
                    mltd_physical_index=entry.physical_index, ps3_text=english))
            remapped.append((record_offset, new_index, old_offset, japanese))
        table_count = len(source_offsets)
        struct.pack_into(">I", prepared, 0x0C, table_count)
        source = bytes(prepared)
        dialogue_records = remapped

    # Shared Japanese strings can be referenced by multiple dialogue records.
    # They must receive the same English replacement because the records point
    # to one master-table slot.  Fail loudly if a stage ever violates that.
    replacements: dict[int, str] = {}
    for entry, (_, table_index, _, _) in zip(entries, dialogue_records):
        translated = ps3_dialogue_text(entry.text)
        previous = replacements.setdefault(table_index, translated)
        if previous != translated:
            raise ValueError(
                f"LDBI table index {table_index} maps to conflicting English strings"
            )

    # A second scene record can use a separate master-table entry containing
    # identical Japanese text (S000: index 266 versus translated index 276).
    # Cover exact aliases only when every known translation agrees; never
    # propagate a short/ambiguous line by guessing between English variants.
    original_translations: dict[str, set[str]] = {}
    original_indices: dict[str, list[int]] = {}
    for _, table_index, _, japanese in dialogue_records:
        original_translations.setdefault(japanese, set()).add(replacements[table_index])
        original_indices.setdefault(japanese, []).append(table_index)
    aliases = []
    for table_index, old_offset in enumerate(source_offsets):
        if table_index in replacements:
            continue
        japanese = read_cstring(source, old_offset)
        choices = original_translations.get(japanese)
        if not choices:
            continue
        if len(choices) != 1:
            raise ValueError(f"Ambiguous duplicate dialogue at LDBI index {table_index}")
        english = next(iter(choices))
        replacements[table_index] = english
        aliases.append(dict(ldbi_table_index=table_index, old_offset=old_offset,
                            japanese=japanese, ps3_text=english,
                            matched_dialogue_indices=sorted(set(original_indices[japanese]))))

    speaker_rows = []
    if speaker_mltd is not None:
        speaker_entries, _ = parse_mltd(speaker_mltd)
        seen_speakers: set[int] = set()
        for record_offset, _, _, _ in dialogue_records:
            # +4 is the portrait/character ID; +8 indexes the displayed name.
            character_id, name_index = struct.unpack_from(">II", source, record_offset + 4)
            if name_index >= len(source_offsets):
                raise ValueError("Speaker name index is outside the master table")
            japanese = read_cstring(source, source_offsets[name_index])
            # Preserve the anonymous-speaker marker rather than revealing its ID.
            if not has_japanese(japanese):
                continue
            if character_id >= len(speaker_entries):
                raise ValueError(f"No official nickname for character {character_id}")
            english = speaker_entries[character_id].text
            if not english.strip() or has_japanese(english):
                raise ValueError(f"Unsupported English nickname for character {character_id}")
            previous = replacements.setdefault(name_index, english)
            if previous != english:
                raise ValueError(f"Conflicting speaker names at LDBI index {name_index}")
            if name_index not in seen_speakers:
                speaker_rows.append(dict(ldbi_table_index=name_index,
                    old_offset=source_offsets[name_index], character_id=character_id,
                    japanese=japanese, ps3_text=english))
                seen_speakers.add(name_index)

    supplemental_rows = []
    for item in supplemental_translations or []:
        table_index = item["ldbi_table_index"]
        if not 0 <= table_index < original_table_count:
            raise ValueError("Supplemental index is outside the original table")
        japanese = read_cstring(source, source_offsets[table_index])
        if japanese != item["japanese"]:
            raise ValueError(f"Supplemental source text mismatch at index {table_index}")
        english = item["english"]
        if replacements.setdefault(table_index, english) != english:
            raise ValueError(f"Conflicting supplemental text at index {table_index}")
        supplemental_rows.append(dict(ldbi_table_index=table_index,
            old_offset=source_offsets[table_index], japanese=japanese, ps3_text=english,
            provenance=item.get("provenance")))

    out = bytearray(source)
    tail = bytearray()
    new_offsets: dict[int, int] = {}
    placements: dict[int, str] = {}
    offset_users: dict[int, set[int]] = {}
    for table_index, old_offset in enumerate(source_offsets):
        offset_users.setdefault(old_offset, set()).add(table_index)

    if repack_safe_slots:
        # A table pointer makes string placement independent of its original
        # slot.  Repack unique English strings into any translated-only source
        # slot, smallest-fit first, to retain the exact LDBI file size.
        available_slots = []
        for old_offset in sorted({source_offsets[index] for index in replacements}):
            if not offset_users[old_offset] <= replacements.keys():
                continue
            capacity = len(read_cstring(source, old_offset).encode("utf-8")) + 1
            available_slots.append((capacity, old_offset))
        available_slots.sort()
        if reuse_slot_remainders:
            # Clear only translated-owned source slots. Unused Japanese
            # remnants waste archive space; no live untranslated pointer may
            # reference any of these slots (checked when collecting them).
            for capacity, offset in available_slots:
                out[offset:offset + capacity] = bytes(capacity)

        english_users: dict[str, list[int]] = {}
        for table_index, english in replacements.items():
            english_users.setdefault(english, []).append(table_index)
        requests = sorted(
            (
                len(english.encode("utf-8")) + 1,
                english,
                table_indices,
            )
            for english, table_indices in english_users.items()
        )
        for required, english, table_indices in reversed(requests):
            position = bisect.bisect_left(available_slots, (required, -1))
            if position == len(available_slots):
                raise ValueError(
                    f"no safe Japanese slot can hold {required} bytes for {english!r}"
                )
            capacity, new_offset = available_slots.pop(position)
            encoded = english.encode("utf-8") + b"\x00"
            out[new_offset : new_offset + capacity] = encoded + bytes(
                capacity - len(encoded)
            )
            if reuse_slot_remainders and capacity > len(encoded):
                # Only bytes inside this already-owned translated slot are
                # reusable; keep the new string's NUL terminator intact.
                bisect.insort(available_slots,
                              (capacity - len(encoded), new_offset + len(encoded)))
            for table_index in table_indices:
                struct.pack_into(">I", out, table_offset + table_index * 4, new_offset)
                new_offsets[table_index] = new_offset
                placements[table_index] = "repacked_slot"
    else:
        for table_index, english in replacements.items():
            encoded = english.encode("utf-8") + b"\x00"
            old_offset = source_offsets[table_index]
            old_capacity = len(read_cstring(source, old_offset).encode("utf-8")) + 1
            sharing_indices = offset_users[old_offset]
            sharing_replacements = {
                replacements[index]
                for index in sharing_indices
                if index in replacements
            }
            safe_to_reuse = (
                reuse_fitting_slots
                and len(encoded) <= old_capacity
                and sharing_indices <= replacements.keys()
                and sharing_replacements == {english}
            )
            if safe_to_reuse:
                new_offset = old_offset
                out[old_offset : old_offset + old_capacity] = encoded + bytes(
                    old_capacity - len(encoded)
                )
                placements[table_index] = "in_place"
            else:
                new_offset = len(source) + len(tail)
                tail.extend(encoded)
                placements[table_index] = "appended"
            struct.pack_into(">I", out, table_offset + table_index * 4, new_offset)
            new_offsets[table_index] = new_offset

    rows = []
    for entry, (record_offset, table_index, old_offset, old_text) in zip(
        entries, dialogue_records
    ):
        rows.append(
            {
                "mltd_physical_index": entry.physical_index,
                "record_offset": record_offset,
                "ldbi_table_index": table_index,
                "old_offset": old_offset,
                "new_offset": new_offsets[table_index],
                "placement": placements[table_index],
                "japanese": old_text,
                "english": entry.text,
                "ps3_text": replacements[table_index],
            }
        )

    result = bytes(out) + bytes(tail)

    for row in aliases + speaker_rows + supplemental_rows:
        row["new_offset"] = new_offsets[row["ldbi_table_index"]]
        row["placement"] = placements[row["ldbi_table_index"]]

    # Verify every rewritten pointer and string from the produced bytes.
    for row in rows + aliases + speaker_rows + supplemental_rows:
        actual_offset = struct.unpack_from(
            ">I", result, table_offset + row["ldbi_table_index"] * 4
        )[0]
        if actual_offset != row["new_offset"]:
            raise AssertionError(
                f"pointer verification failed for LDBI index {row['ldbi_table_index']}"
            )
        if read_cstring(result, actual_offset) != row["ps3_text"]:
            raise AssertionError(
                f"text verification failed for LDBI index {row['ldbi_table_index']}"
            )

    # Count coverage from the source, including entries outside the selected
    # MLTD record window. Original Japanese byte remnants are not active text.
    remaining_dialogue = [dict(ldbi_table_index=i, japanese=read_cstring(source, offset))
        for i, offset in enumerate(source_offsets)
        if i not in replacements and has_japanese(read_cstring(source, offset))
        and read_cstring(source, offset).startswith(("「", "（"))]

    report = {
        "format": "OGMD PS4 MLTD to PS3 LDBI proof of concept",
        "source_size": len(source),
        "output_size": len(result),
        "appended_size": len(tail),
        "source_sha256": sha256(source),
        "output_sha256": sha256(result),
        "ldbi_table_count": table_count,
        "original_ldbi_table_count": original_table_count,
        "split_shared_dialogue": split_rows,
        "ldbi_table_offset": table_offset,
        "record_detection": record_meta,
        "mltd": mltd_meta,
        "mapped_entries": len(rows),
        "duplicate_dialogue_aliases": aliases,
        "translated_speaker_names": speaker_rows,
        "supplemental_translations": supplemental_rows,
        "speaker_mltd_sha256": sha256(speaker_mltd) if speaker_mltd is not None else None,
        "remaining_unmapped_japanese_dialogue": remaining_dialogue,
        "line_break_conversion": "PS4 CRLF/CR/LF to PS3 @",
        "entries_with_converted_line_breaks": sum(
            row["english"] != row["ps3_text"] for row in rows
        ),
        "converted_line_breaks": sum(
            row["english"].replace("\r\n", "\n").replace("\r", "\n").count("\n")
            for row in rows
        ),
        "unique_ldbi_table_entries": len(replacements),
        "in_place_table_entries": sum(
            placement == "in_place" for placement in placements.values()
        ),
        "appended_table_entries": sum(
            placement == "appended" for placement in placements.values()
        ),
        "repacked_table_entries": sum(
            placement == "repacked_slot" for placement in placements.values()
        ),
        "mapped_entries_with_japanese_source": sum(has_japanese(row["japanese"]) for row in rows),
        "rows": rows,
    }
    report["source_sha256"] = sha256(original_source)
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Japanese PS3 ls###.bin")
    parser.add_argument("mltd", type=Path, help="English PS4 S###_TextData.mltd")
    parser.add_argument("output", type=Path, help="patched PS3 ls###.bin")
    parser.add_argument("--report", type=Path, help="optional JSON mapping report")
    parser.add_argument("--speaker-names", type=Path,
                        help="official English FixedData/PilotNickName.mltd")
    parser.add_argument("--split-shared-dialogue", action="store_true",
                        help="split conflicting English variants using verified table padding")
    parser.add_argument("--reuse-slot-remainders", action="store_true",
                        help="reuse leftover space within safely repacked string slots")
    parser.add_argument("--supplemental-text", type=Path,
                        help="JSON list of source-checked supplemental translations")
    compact_group = parser.add_mutually_exclusive_group()
    compact_group.add_argument(
        "--reuse-fitting-slots",
        action="store_true",
        help="reuse unshared Japanese slots when the English bytes fit",
    )
    compact_group.add_argument(
        "--repack-safe-slots",
        action="store_true",
        help="repack English into translated-only Japanese slots for exact size",
    )
    args = parser.parse_args()

    source = args.source.read_bytes()
    mltd = args.mltd.read_bytes()
    result, report = port_stage(
        source,
        mltd,
        reuse_fitting_slots=args.reuse_fitting_slots,
        repack_safe_slots=args.repack_safe_slots,
        speaker_mltd=args.speaker_names.read_bytes() if args.speaker_names else None,
        split_shared_dialogue=args.split_shared_dialogue,
        reuse_slot_remainders=args.reuse_slot_remainders,
        supplemental_translations=json.loads(args.supplemental_text.read_text(encoding="utf-8"))
            if args.supplemental_text else None,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"mapped entries: {report['mapped_entries']}")
    print(
        "entries with Japanese source: "
        f"{report['mapped_entries_with_japanese_source']}/{report['mapped_entries']}"
    )
    print(f"size: {report['source_size']} -> {report['output_size']} bytes")
    print(
        "placements: "
        f"{report['in_place_table_entries']} in-place, "
        f"{report['repacked_table_entries']} repacked, "
        f"{report['appended_table_entries']} appended"
    )
    print(f"source SHA-256: {report['source_sha256']}")
    print(f"output SHA-256: {report['output_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
