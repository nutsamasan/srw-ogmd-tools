"""Build and audit the native OGMD story corpus using official PS4 overlays."""
from __future__ import annotations

import json
import re
import struct
from collections import defaultdict
from pathlib import Path

from port_mltd_stage import (parse_mltd, parse_ldbi_table, read_cstring,
                             ps3_dialogue_text, find_dialogue_records, has_japanese, sha256)
from ogmd_text_formats import parse_fixed, dialogue_grid, rebuild_ldbi_pool

ROOT = Path(__file__).resolve().parents[1]
LANG = ROOT / "work/extracted/ps4_lang/Dat/MultiLanguage/@En"
SOURCE = ROOT / "work/extracted/ps3_logic"
OUT = ROOT / "work/poc/full_english_20260906"


def english_table(name):
    return parse_mltd((LANG / (name + ".mltd")).read_bytes())[0]


def speaker_dictionary():
    fixed = parse_fixed((SOURCE / "Dat/FixedData/PilotData.dat").read_bytes())
    english = english_table("FixedData/PilotNickName")
    candidates = defaultdict(set)
    for logical, physical in enumerate(fixed.logical_indices):
        if physical == 0xFFFFFFFF:
            continue
        string_index = struct.unpack_from(">H", fixed.records[physical], 2)[0]
        jp, en = fixed.strings[string_index], english[logical].text
        if has_japanese(jp) and en.strip():
            candidates[jp].add(en)
    names = {jp: next(iter(choices)) for jp, choices in candidates.items() if len(choices) == 1}
    special = {"ガンエデン": 67, "カナフ": 68, "保安兵": 132,
               "アナウンス": 148, "所属不明兵": 138,
               "市民": 144, "クリフォード": 108, "アイン": 131, "親衛隊兵": 146}
    talk = english_table("Talk/TalkCharaNameText")
    for jp, index in special.items():
        names[jp] = talk[index].text
    return names


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "story").mkdir(exist_ok=True)
    (OUT / "story_reports").mkdir(exist_ok=True)
    names = speaker_dictionary()
    common_source = (SOURCE / "Dat/logic/talk/ls001.bin").read_bytes()
    dead_records = dialogue_grid(common_source)[:82]
    dead_english = english_table("Talk/DeadMessage_TextData")
    assert len(dead_records) == len(dead_english) == 82
    common = {}
    for record, entry in zip(dead_records, dead_english):
        en = ps3_dialogue_text(entry.text)
        common.setdefault(record[3], en)
    locations_path = OUT / "location_dictionary.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8")) if locations_path.exists() else {}
    summaries, remaining_global = [], defaultdict(list)
    for f in sorted((LANG / "Talk").glob("S[0-9]*_TextData.mltd")):
        if not re.fullmatch(r"S\d+_TextData", f.stem):
            continue
        stem = f.stem[:4].lower().replace("s", "ls", 1)
        source = SOURCE / "Dat/logic/talk" / (stem + ".bin")
        entries, _ = parse_mltd(f.read_bytes())
        summary = dict(stage=stem, english_entries=len(entries))
        if not source.exists():
            summary.update(status="no_native_asset", nonempty_entries=[e.physical_index for e in entries if e.text.strip()])
            summaries.append(summary)
            continue
        try:
            data = source.read_bytes()
            count, _, offsets = parse_ldbi_table(data)
            original = [read_cstring(data, o) for o in offsets]
            grid = dialogue_grid(data)
            common_record_text = {}
            if [r[3] for r in grid[:82]] == [r[3] for r in dead_records]:
                common_record_text = {r[0]: ps3_dialogue_text(e.text)
                                      for r, e in zip(grid[:82], dead_english)}
            # Every native file has exactly its own English dialogue count,
            # optionally preceded by the 82 shared commands and, in S000/S096,
            # a separate copy of the 20-command prologue. No scored windows.
            prefix = len(grid) - len(entries)
            assert prefix in (0, 82, 102), (stem, prefix)
            if prefix:
                assert len(common_record_text) == 82, "Common prefix differs from its verified source"
            prologue_records = []
            if prefix == 102:
                prologue = english_table("Talk/Prologue_TextData")
                reference = dialogue_grid((SOURCE / "Dat/logic/talk/ls000.bin").read_bytes())[82:102]
                assert [r[3] for r in grid[82:102]] == [r[3] for r in reference]
                prologue_records = list(zip(grid[82:102], prologue))
            selected = grid[prefix:]
            meta = dict(method="opcode-0 dialogues after verified common/prologue prefixes", native_dialogues=len(grid),
                        first=selected[0][0], last=selected[-1][0])
            replacements, variants, rows = {}, [], []
            english_by_jp = defaultdict(set)
            for record, entry in zip(selected, entries):
                r, index, _, jp = record
                en = ps3_dialogue_text(entry.text)
                replacements.setdefault(index, en)
                variants.append((r, index, en))
                english_by_jp[jp].add(en)
                rows.append(dict(record=r, table_index=index, mltd_index=entry.physical_index, japanese=jp, english=en))
            for record, entry in prologue_records:
                r, index, _, jp = record
                en = ps3_dialogue_text(entry.text)
                replacements.setdefault(index, en)
                variants.append((r, index, en))
            common_count = 0
            name_indices = set()
            missing_names = []
            for r, index, _, jp in grid:
                if jp in common and r not in {row["record"] for row in rows}:
                    en = common_record_text.get(r, common[jp])
                    replacements.setdefault(index, en)
                    variants.append((r, index, en))
                    common_count += 1
                ni = struct.unpack_from(">I", data, r + 8)[0]
                assert ni < count
                label = original[ni]
                if not has_japanese(label):
                    continue
                base = re.sub(r"^\[ＤＭ\]-", "", label)
                if base not in names:
                    missing_names.append(label)
                    continue
                replacements[ni] = names[base]
                name_indices.add(ni)
            aliases = []
            for index, jp in enumerate(original):
                if index in replacements:
                    continue
                options = english_by_jp.get(jp, set())
                if len(options) == 1:
                    replacements[index] = next(iter(options))
                    aliases.append(index)
                elif jp in common:
                    replacements[index] = common[jp]
                elif jp in names:
                    replacements[index] = names[jp]
                elif jp in locations:
                    replacements[index] = locations[jp]["english"]
            result, allocation = rebuild_ldbi_pool(data, replacements, variants)
            _, _, actual_offsets = parse_ldbi_table(result)
            for row in rows:
                index = struct.unpack_from(">I", result, row["record"] + 12)[0]
                assert read_cstring(result, actual_offsets[index]) == row["english"]
            for r, index, en in variants:
                actual_index = struct.unpack_from(">I", result, r + 12)[0]
                assert read_cstring(result, actual_offsets[actual_index]) == en
            remaining = []
            for index, jp in enumerate(original):
                if index not in replacements and has_japanese(jp):
                    remaining.append(dict(index=index, japanese=jp))
                    remaining_global[jp].append(dict(stage=stem, index=index))
            report = dict(source_sha256=sha256(data), mltd_sha256=sha256(f.read_bytes()),
                          output_sha256=sha256(result), source_size=len(data), output_size=len(result),
                          allocation=allocation, detection=meta, rows=rows, common_dialogue=common_count,
                          prologue_dialogue=len(prologue_records),
                          translated_names=len(name_indices), missing_names=sorted(set(missing_names)),
                          aliases=aliases, remaining_japanese=remaining,
                          replacements=[dict(index=i,japanese=original[i],english=en) for i,en in sorted(replacements.items())])
            (OUT / "story" / source.name).write_bytes(result)
            (OUT / "story_reports" / (stem + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.update(status="converted", mapped=len(rows), common=common_count,
                           missing_names=report["missing_names"], remaining=len(remaining),
                           pool_free=allocation["free_pool_bytes"])
        except Exception as exc:
            import traceback
            summary.update(status="needs_work", error=str(exc), traceback=traceback.format_exc())
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=True), flush=True)
    (OUT / "story_inventory.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "story_remaining.json").write_text(json.dumps(dict(remaining_global), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    build()
