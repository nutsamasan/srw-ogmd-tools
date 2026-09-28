"""Verify the S001 asset build against pristine inputs and accepted S000."""
from pathlib import Path
import json
import struct

from port_mltd_stage import (parse_ldbi_table, parse_mltd, port_stage,
                             read_cstring, sha256, has_japanese)
from port_mltd_roll import parse_csb
from verify_ogmd_line_measurement import native_width, measure

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "work/extracted/ps3_logic/Dat/logic/talk/ls001.bin").read_bytes()
    output = (ROOT / "work/poc/stage001_20260906/ls001_en.bin").read_bytes()
    report = json.loads((ROOT / "reports/stage001_dialogue_20260906.json").read_text(encoding="utf-8"))
    count, table, offsets = parse_ldbi_table(source)
    new_count, new_table, new_offsets = parse_ldbi_table(output)
    assert len(source) == len(output) and table == new_table
    assert count == 426 and new_count == 428
    assert sha256(source) == report["source_sha256"] and sha256(output) == report["output_sha256"]
    rows = report["rows"] + report["duplicate_dialogue_aliases"] + report["translated_speaker_names"] + report["supplemental_translations"]
    expected = {row["ldbi_table_index"]: row["ps3_text"] for row in rows}
    allowed = bytearray(len(source))
    allowed[0x0C:0x10] = b"\1" * 4
    allowed[table + count * 4:table + new_count * 4] = b"\1" * ((new_count - count) * 4)
    for index in expected:
        if index < count:
            offset = offsets[index]
            size = len(read_cstring(source, offset).encode("utf-8")) + 1
            allowed[offset:offset + size] = b"\1" * size
            allowed[table + index * 4:table + index * 4 + 4] = b"\1" * 4
    for row in report["split_shared_dialogue"]:
        field = row["record_offset"] + 12
        assert struct.unpack_from(">I", source, field)[0] == row["original_table_index"]
        assert struct.unpack_from(">I", output, field)[0] == row["new_table_index"]
        allowed[field:field + 4] = b"\1" * 4
    assert all(a == b or allowed[i] for i, (a, b) in enumerate(zip(source, output)))
    for index in range(new_count):
        text = read_cstring(output, new_offsets[index])
        if index in expected:
            assert text == expected[index]
        else:
            assert new_offsets[index] == offsets[index]
            assert text == read_cstring(source, offsets[index])
    for row in report["rows"]:
        field = row["record_offset"] + 12
        index = struct.unpack_from(">I", output, field)[0]
        assert index == row["ldbi_table_index"]
        assert read_cstring(output, new_offsets[index]) == row["english"].replace("\r\n", "\n").replace("\r", "\n").replace("\n", "@")
    for row in report["supplemental_translations"]:
        evidence = row["provenance"]
        data = (ROOT / evidence["mltd"]).read_bytes()
        assert sha256(data) == evidence["sha256"]
        entries, _ = parse_mltd(data)
        assert entries[evidence["physical_index"]].text == row["ps3_text"]
    remaining = [i for i in range(220, count) if has_japanese(read_cstring(output, new_offsets[i]))]
    assert not remaining, remaining

    old_build, _ = port_stage(
        (ROOT / "work/extracted/ps3_logic/Dat/logic/talk/ls000.bin").read_bytes(),
        (ROOT / "work/extracted/ps4_lang/Dat/MultiLanguage/@En/Talk/S000_TextData.mltd").read_bytes(),
        speaker_mltd=(ROOT / "work/extracted/ps4_lang/Dat/MultiLanguage/@En/FixedData/PilotNickName.mltd").read_bytes(),
        repack_safe_slots=True)
    assert sha256(old_build) == "80FCEEAD76D24A2B399B862A1F7D775B1A2945FE03BA5F148C6F97D498AA325D"

    dream = (ROOT / "work/poc/stage001_20260906/Roll_20_cnv.csb").read_bytes()
    original_dream = (ROOT / "work/extracted/ps3_logic/Dat/Roll/Csb/Roll_20_cnv.csb").read_bytes()
    original_chunks, _, original_commands = parse_csb(original_dream)
    chunks, strings, commands = parse_csb(dream)
    assert original_chunks == chunks and len(original_dream) == len(dream)
    demo_entries, _ = parse_mltd((ROOT / "work/extracted/ps4_lang/Dat/MultiLanguage/@En/Talk/S001_DEMO_TextData.mltd").read_bytes())
    used = []
    for old, new in zip(original_commands, commands):
        expected_args = list(old["arguments"])
        if expected_args[0] == "19":
            index = int(expected_args[13])
            used.append(index)
            expected_args[3] = demo_entries[index].text
        assert new["arguments"] == expected_args
    assert used == list(range(10)) + list(range(11, 21))
    assert not any(has_japanese(text) for text in strings.values())

    lines = [dict(mltd_index=row["mltd_physical_index"], line=n + 1, text=line,
                  width=native_width(line, 24.0))
             for row in report["rows"] for n, line in enumerate(row["ps3_text"].split("@"))]
    longest = sorted(lines, key=lambda row: row["width"], reverse=True)
    native_checks = []
    for row in longest[:3]:
        for entry in (0xB7F808, 0xB7FC20):
            actual = measure(row["text"], entry, "v2")
            assert actual == row["width"]
            native_checks.append(dict(mltd_index=row["mltd_index"], entry=hex(entry), measured_width=actual))
    validation = dict(dialogue_entries=len(report["rows"]), all_master_entries_verified=new_count,
        translated_master_entries=len(expected), preserved_master_entries=new_count - len(expected),
        allowed_byte_changes_only=True, record_index_variants=report["split_shared_dialogue"],
        remaining_japanese_story_indices=remaining, accepted_s000_regression_sha256=sha256(old_build),
        dream_text_commands=len(used), unused_demo_ids=[10], dream_control_values_preserved=True,
        dialogue_line_count=len(lines), longest_dialogue_lines=longest[:10],
        lines_above_768=[line for line in lines if line["width"] > 768],
        maximum_dialogue_rows=max(len(row["ps3_text"].split("@")) for row in report["rows"]),
        native_measurement_checks=native_checks,
        limitation="Offline asset and native measurement checks; S001 needs user gameplay testing.")
    target = ROOT / "reports/stage001_verification_20260906.json"
    target.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in validation.items() if k not in {"longest_dialogue_lines", "lines_above_768", "record_index_variants"}}))
    print("Lines above 768:", len(validation["lines_above_768"]))


if __name__ == "__main__":
    main()
