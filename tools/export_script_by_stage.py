"""Read pristine OGMD archives and export the JP/official EN script by stage.

No installed or patched game assets are used or modified. Run from any directory.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import difflib
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor/vendor'))
from psarc import Psarc
from ogmd_text_formats import parse_fixed, dialogue_grid
from port_mltd_stage import parse_mltd, mltd_lookup, localization_hash, parse_ldbi_table, read_cstring, has_japanese
from port_mltd_roll import parse_csb
from probe_map_scripts import parse_logo
from port_battle_corpus import parse_bmd
from story_location_map import MAPPING as LOCATION_MAPPING


def digest(data):
    return hashlib.sha256(data).hexdigest().upper()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8-sig")


def slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")[:68] or "Unnamed"


class Sources:
    def __init__(self):
        self.paths = {
            "jp_logic": ROOT / "work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc",
            "jp_common": ROOT / "work/ps3_disc/PS3_GAME/USRDIR/PSARC/Common.psarc",
            "jp_battle": ROOT / "work/ps3_disc/PS3_GAME/USRDIR/PSARC/Battle.psarc",
            "en_lang": ROOT / "work/ps4_base/CUSA04713/archive/lang.psarc",
            "en_patch": ROOT / "work/ps4_update/CUSA04713-patch/PATCH/Patch0101.psarc",
            "ps4_logic": ROOT / "work/ps4_base/CUSA04713/archive/logic.psarc",
        }
        self.archives = {k: Psarc(v) for k, v in self.paths.items()}
        self.entries = {k: {e.name.lstrip("/"): e for e in a.entries} for k, a in self.archives.items()}
        self.used = {}
        self.mltds = {}

    def read(self, archive, entry):
        entry = entry.lstrip("/")
        data = self.archives[archive]._read_file(self.entries[archive][entry])
        self.used[archive, entry] = dict(archive=archive, entry=entry, size=len(data), sha256=digest(data))
        return data

    def english(self, table):
        if table not in self.mltds:
            entry = "Dat/MultiLanguage/@En/" + table + ".mltd"
            archive = "en_patch" if entry in self.entries["en_patch"] else "en_lang"
            data = self.read(archive, entry)
            es, meta = parse_mltd(data)
            assert meta["lookup_ids_are_zero_based_permutation"]
            self.mltds[table] = (es, dict(archive=archive, entry=entry, sha256=digest(data)), data)
        return self.mltds[table]


def stage_metadata(s):
    f = parse_fixed(s.read("jp_logic", "Dat/FixedData/StageData.dat"))
    en, en_source, _ = s.english("FixedData/StageName")
    roots, roots_source, _ = s.english("FixedData/RootName")
    assert len(en) == len(roots) == len(f.records)
    charts, membership = {}, collections.defaultdict(dict)
    for mode, stem in [("normal", "ScenarioChart"), ("beginner", "ScenarioChartBeginners")]:
        entry = f"Dat/Option/ScenarioChart/{stem}.csb"
        _, _, rs = parse_csb(s.read("jp_common", entry))
        charts[mode] = dict(source=entry, commands=[r["arguments"] for r in rs])
        for r in rs[2:]:
            args = r["arguments"]
            row = int(args[0])
            for column, cell in enumerate(args[1:]):
                if cell.isdecimal():
                    sid = int(cell)
                    assert mode not in membership[sid]
                    membership[sid][mode] = dict(row=row, column=column, sequence_chapter=row // 2 + (mode == "beginner"))
    result = {}
    for sid, physical in enumerate(f.logical_indices):
        if physical == 0xFFFFFFFF:
            continue
        rec = f.records[physical]
        assert rec[0] == sid
        jp_route = f.strings[rec[6]]
        # Native chart reunites at S034; its official RootName entry still says
        # To the Moon. Preserve that source value, but classify by native route.
        category_route = "Common" if jp_route == "共通" else roots[physical].text.strip()
        result[sid] = dict(
            scenario_id=sid, script_id=f"S{sid:03}", stage_data_physical_index=physical,
            stage_data_chapter=rec[1], title_jp=f.strings[rec[3]], title_en=en[physical].text,
            route_jp=jp_route, route_en=roots[physical].text, classification_route=category_route,
            chart_membership=membership.get(sid, {}), stage_record_hex=rec.hex(),
            stage_title_source=en_source, route_title_source=roots_source,
        )
        if jp_route == "共通" and category_route != roots[physical].text.strip():
            result[sid]["route_note"] = "Official English RootName differs from native Common route; both source values retained. Both scenario charts show this stage after route convergence."
    return result, charts


def speaker_names(s):
    f = parse_fixed(s.read("jp_logic", "Dat/FixedData/PilotData.dat"))
    en, _, _ = s.english("FixedData/PilotNickName")
    candidates = collections.defaultdict(set)
    for logical, physical in enumerate(f.logical_indices):
        if physical != 0xFFFFFFFF:
            jp = f.strings[int.from_bytes(f.records[physical][2:4], "big")]
            if en[logical].text.strip():
                candidates[jp].add(en[logical].text)
    names = {jp: next(iter(es)) for jp, es in candidates.items() if len(es) == 1}
    talk, _, _ = s.english("Talk/TalkCharaNameText")
    for jp, i in {"ガンエデン": 67, "カナフ": 68, "保安兵": 132, "アナウンス": 148,
                  "所属不明兵": 138, "市民": 144, "クリフォード": 108, "アイン": 131, "親衛隊兵": 146}.items():
        names[jp] = talk[i].text
    names["？？？"] = "???"
    # Only the displayed label is normalized. The exact source label is retained.
    names["ＸＮ‐Ｌ"] = "XN-L"
    return names


def native_story(data):
    count, _, offsets = parse_ldbi_table(data)
    strings = [read_cstring(data, o) for o in offsets]
    n, start = struct.unpack_from(">II", data, 0x20)
    block_count, block_start = struct.unpack_from(">II", data, 0x28)
    assert start + n * 196 <= block_start
    blocks = []
    cumulative = 0
    for i in range(block_count):
        name_index, size, first = struct.unpack_from(">3I", data, block_start + i * 12)
        assert name_index < count and first == cumulative and first + size <= n
        blocks.append(dict(index=i, name=strings[name_index], first_command=first, command_count=size))
        cumulative += size
    assert cumulative == n
    starts = [b["first_command"] for b in blocks]
    rows = []
    for p, idx, off, text in dialogue_grid(data):
        command = (p - 4 - start) // 196
        assert start + command * 196 + 4 == p
        b = blocks[bisect.bisect_right(starts, command) - 1]
        ni = struct.unpack_from(">I", data, p + 8)[0]
        rows.append(dict(command_index=command, command_offset=p - 4, jp_string_index=idx,
                         jp_text_offset=off, speaker_jp=strings[ni], speaker_string_index=ni,
                         jp_raw=text, jp=text.replace("@", "\n"), block_index=b["index"], block=b["name"],
                         command_metadata_hex=data[p + 16:p + 192].hex()))
    # A valid opcode-0 command with empty text is retained in the native pool,
    # and counted explicitly, never silently mistaken for nonempty dialogue.
    empty = []
    for i in range(n):
        p = start + i * 196
        if struct.unpack_from(">I", data, p)[0] == 0:
            ni, ti = struct.unpack_from(">II", data, p + 12)
            assert ni < count and ti < count
            if not strings[ti]:
                empty.append(i)
    assert len(rows) + len(empty) == sum(struct.unpack_from(">I", data, start+i*196)[0] == 0 for i in range(n))
    return rows, blocks, strings, empty


def pair_rows(rows, entries, source, names):
    assert len(rows) == len(entries), (len(rows), len(entries), source)
    result = []
    for row, e in zip(rows, entries):
        label = row["speaker_jp"]
        assert label in names or not has_japanese(label), label
        result.append(dict(row, en=e.text, en_raw=e.text,
                           en_source=source, en_entry_index=e.physical_index,
                           speaker_en=names.get(label, label),
                           official_en_has_japanese=has_japanese(e.text)))
    return result


def render_rows(meta, rows, language):
    text = [meta.get("title_en", "") + " / " + meta.get("title_jp", ""),
            meta.get("description", ""), ""]
    if meta.get("script_id"):
        text += [f"Script: {meta['script_id']} | Native: {meta.get('native_entry', '')}",
                 f"StageData chapter: {meta.get('stage_data_chapter', 'n/a')} | Route: {meta.get('classification_route', 'n/a')}"]
    if meta.get("chart_membership"):
        text.append("Chart chapter: " + "; ".join(f"{mode} {c['sequence_chapter']}" for mode,c in meta["chart_membership"].items()))
    text += ["Source order; conditional and alternate event branches are included.",
             "JP display text: @ is shown as a line break. Exact source strings are in script.json.", ""]
    if meta.get("shared_death_commands"):
        text += [f"{meta['shared_death_commands']} shared defeat messages are indexed in 04_Shared/Defeat_messages; they are not repeated here.", ""]
    previous = None
    for i, row in enumerate(rows):
        block = row.get("block", "Text")
        if block != previous:
            text += ["=" * 72, "BLOCK: " + block, "=" * 72, ""]
            if row.get("block_title_en"):
                text += [row["block_title_en"] + " / " + row["block_title_jp"], ""]
            previous = block
        ident = row.get("id", str(i + 1))
        for lang in (["en", "jp"] if language == "bilingual" else [language]):
            speaker = row.get("speaker_" + lang, "")
            label = f"[{ident}]" + (f" {lang.upper()}" if language == "bilingual" else "")
            if speaker:
                label += " " + speaker
            text += [label, row.get(lang) if row.get(lang) is not None else "[No official counterpart located]", ""]
        if row.get("official_en_has_japanese") and language != "jp":
            text += ["[The official English table contains Japanese here; preserved as shipped.]", ""]
    return "\n".join(text) + "\n"


def save_collection(out, relative, meta, rows, extra=None):
    folder = out / relative
    for i, row in enumerate(rows):
        row.setdefault("id", f"{meta.get('script_id', folder.name)}:{i:04d}")
    document = dict(metadata=meta, rows=rows)
    if extra:
        document.update(extra)
    write_json(folder / "script.json", document)
    for filename, lang in [("EN.txt", "en"), ("JP.txt", "jp"), ("Bilingual.txt", "bilingual")]:
        write_text(folder / filename, render_rows(meta, rows, lang))
    return dict(folder=relative, rows=len(rows), **meta)


def collection_path(meta):
    sid = meta["scenario_id"]
    suffix = f"{meta['script_id']}_{slug(meta['title_en'])}"
    if sid == 0:
        return "01_Stages/Stage_00_Prologue_" + suffix
    if 1 <= sid <= 47 or 71 <= sid <= 86:
        return f"01_Stages/Stage_{meta['stage_data_chapter']:02d}_{slug(meta['classification_route'])}_{suffix}"
    if sid in (96, 97):
        return "02_Alternate_versions/" + suffix
    if 100 <= sid <= 104:
        return f"03_Interludes/Stage_{meta['stage_data_chapter']:02d}_" + suffix
    if sid in (200, 800, 999):
        return "05_Extras/" + suffix
    return "06_Developer_and_unassigned/" + suffix


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    s = Sources()
    stages, charts = stage_metadata(s)
    names = speaker_names(s)
    location_labels = {}
    for line in LOCATION_MAPPING.strip().splitlines():
        key, japanese = line.split("|", 1)
        table, physical = key.split(":")
        es, source, _ = s.english("Talk/" + table)
        location_labels[japanese] = dict(jp=japanese, en=es[int(physical)].text,
                                        en_source=source, en_entry_index=int(physical))
    end_fixed = parse_fixed(s.read("jp_logic", "Dat/FixedData/PlayEndMessageData.dat"))
    end_en, end_source, _ = s.english("FixedData/EndMessageTitleName")
    end_titles = {}
    for logical, physical in enumerate(end_fixed.logical_indices):
        if physical != 0xFFFFFFFF:
            rec = end_fixed.records[physical]
            end_titles[end_fixed.strings[rec[2]]] = dict(jp=end_fixed.strings[rec[3]],
                en=end_en[logical].text, en_source=end_source, en_entry_index=logical)
    write_json(out / "data/suspend_message_titles.json", end_titles)
    write_json(out / "data/stage_metadata.json", list(stages.values()))
    write_json(out / "data/scenario_charts.json", charts)
    write_json(out / "data/speaker_names.json", names)
    collections_index, stage_index, story_inventory, unpaired, source_comparisons = [], [], [], [], []
    death_jp = native_story(s.read("jp_logic", "Dat/logic/talk/ls001.bin"))[0][:82]
    death_en, death_source, _ = s.english("Talk/DeadMessage_TextData")
    death = pair_rows(death_jp, death_en, death_source, names)
    collections_index.append(save_collection(out, "04_Shared/Defeat_messages",
        dict(title_en="Shared defeat messages", title_jp="共通・撃墜時メッセージ", script_id="DEAD",
             description="82 shared dialogue commands. Indexed once; each scenario JSON records its own native references."), death))
    prologue_jp = native_story(s.read("jp_logic", "Dat/logic/talk/ls000.bin"))[0][82:102]
    prologue_en, prologue_source, _ = s.english("Talk/Prologue_TextData")
    story_entries = sorted(e for e in s.entries["jp_logic"] if re.fullmatch(r"Dat/logic/talk/ls\d+\.bin", e))
    used_story_tables = set()
    special = {
        800: ("Suspend / end-session conversations", "中断メッセージ", "Bonus conversations grouped by their native EM block IDs; not assigned to a single stage."),
        900: ("Developer map selection", "開発用・マップ選択", "Developer menu dialogue; not a numbered story stage."),
        990: ("Developer pilot and unit settings", "開発用・パイロット設定", "The official English localization still contains Japanese prompts in this script."),
        991: ("Developer sortie settings", "開発用・出撃設定", "Developer menu dialogue; not a numbered story stage."),
        999: ("Unassigned special scene", "ステージ未割当の特殊会話", "Shipped scene featuring Selena and Elma. No StageData entry or normal/Beginner chart membership; exact runtime placement is not established."),
    }
    for entry in story_entries:
        sid = int(Path(entry).stem[2:])
        script_id = f"S{sid:03d}"
        table = f"Talk/{script_id}_TextData"
        data = s.read("jp_logic", entry)
        ps4_data = s.read("ps4_logic", entry)
        assert data == ps4_data, entry
        source_comparisons.append(dict(entry=entry, jp_ps3_equals_ps4_base=True, sha256=digest(data)))
        rows, blocks, strings, empty = native_story(data)
        english, en_source, _ = s.english(table)
        used_story_tables.add(table)
        prefix = len(rows) - len(english)
        assert prefix in (0, 82, 102), (entry, prefix)
        if prefix:
            assert [(r["speaker_jp"],r["jp_raw"]) for r in rows[:82]] == [(r["speaker_jp"],r["jp_raw"]) for r in death_jp]
        selected = []
        if prefix == 102:
            assert [(r["speaker_jp"],r["jp_raw"]) for r in rows[82:102]] == [(r["speaker_jp"],r["jp_raw"]) for r in prologue_jp]
            selected.extend(pair_rows(rows[82:102], prologue_en, prologue_source, names))
        selected.extend(pair_rows(rows[prefix:], english, en_source, names))
        if sid == 800:
            for row in selected:
                if row["block"] in end_titles:
                    title = end_titles[row["block"]]
                    row.update(block_title_jp=title["jp"], block_title_en=title["en"],
                               block_title_source=title["en_source"], block_title_en_entry_index=title["en_entry_index"])
        meta = dict(stages.get(sid, dict(scenario_id=sid, script_id=script_id)))
        if sid in special:
            meta["title_en"], meta["title_jp"], meta["description"] = special[sid]
        if sid == 96:
            meta["description"] = "Alternate prologue asset. Not listed on either scenario chart; exact runtime selection is not established."
        if sid == 97:
            meta["description"] = "Beginner chart's first stage. StageData retains chapter 2; both values are preserved."
        if 100 <= sid <= 103:
            meta["description"] = "Shared interlude/route-selection script. Associated chapter comes from StageData; not a separate numbered chapter on the scenario chart."
        meta.update(native_entry=entry, native_archive="jp_logic", native_sha256=digest(data),
                    en_source=en_source, native_dialogue_commands=len(rows),
                    stage_table_entries=len(english), shared_death_commands=82 if prefix else 0,
                    prologue_table_commands=20 if prefix == 102 else 0,
                    empty_dialogue_commands=empty, source_order="native command order; all conditional branches retained")
        # Record exact native command references to external Roll scripts.
        cmd_count, cmd_start = struct.unpack_from(">II", data, 0x20)
        roll_refs = []
        for i in range(cmd_count):
            p = cmd_start + i*196
            opcode, index = struct.unpack_from(">2I", data, p)
            if opcode in (9, 32) and index < len(strings) and strings[index].endswith(".csb"):
                roll_refs.append(dict(command_index=i, opcode=opcode, filename=strings[index]))
        meta["external_script_references"] = roll_refs
        relative = collection_path(meta)
        extra = dict(blocks=blocks, shared_defeat_references=[dict(command_index=r["command_index"],
            command_offset=r["command_offset"], shared_id=f"DEAD:{i:04d}") for i,r in enumerate(rows[:82])] if prefix else [])
        item = save_collection(out, relative, meta, selected, extra)
        write_json(out / relative / "native_strings.json", [dict(index=i,text=t) for i,t in enumerate(strings)])
        scene_labels = [dict(location_labels[t], native_string_index=i) for i,t in enumerate(strings) if t in location_labels]
        write_json(out / relative / "scene_labels.json", scene_labels)
        write_text(out / relative / "Scene_labels_Bilingual.txt", "Location and scene labels present in this script's native string pool.\nPool order; this list does not imply runtime display order.\n\n" +
                   "\n\n".join(f"[{x['native_string_index']}] EN: {x['en']}\nJP: {x['jp']}" for x in scene_labels) + "\n")
        collections_index.append(item)
        stage_index.append(item)
        story_inventory.append(dict(script_id=script_id, native_commands=len(rows), exported_rows=len(selected),
                                    shared_references=82 if prefix else 0, english_entries=len(english),
                                    shared_prologue=20 if prefix == 102 else 0, empty_commands=len(empty), folder=relative))
    print(f"Story: {len(stage_index)} native scripts parsed and matched to English.", flush=True)

    # Every stage MLTD is accounted for, including shipped placeholders.
    empty_tables = []
    for entry in sorted(s.entries["en_lang"]):
        if not re.fullmatch(r"Dat/MultiLanguage/@En/Talk/S\d+_TextData\.mltd", entry):
            continue
        table = entry.split("@En/",1)[1][:-5]
        if table in used_story_tables:
            continue
        es, provenance, _ = s.english(table)
        nonempty = [dict(index=e.physical_index,english=e.text) for e in es if e.text]
        assert not nonempty, (table, nonempty)
        empty_tables.append(dict(table=table, entries=len(es), nonempty=0, status="Empty localization placeholder; no native story script", source=provenance))
    write_json(out / "data/empty_localization_tables.json", empty_tables)

    # Map text is associated by native scenario filename ID; each displayed
    # string is matched with the actual runtime localization hash.
    lookup = collections.defaultdict(list)
    for entry in sorted(s.entries["en_lang"]):
        if entry.startswith("Dat/MultiLanguage/@En/MapLogic/") and entry.endswith(".mltd"):
            table = entry.split("@En/",1)[1][:-5]
            es, source, data = s.english(table)
            for key, e in mltd_lookup(data).items():
                lookup[key].append((e, source))
    map_inventory = []
    native_map_without_localization = []
    used_map_keys = set()
    for entry in sorted(s.entries["jp_logic"]):
        if not re.fullmatch(r"Dat/logic/scr\d+\.bin", entry):
            continue
        sid = int(Path(entry).stem[3:])
        data = s.read("jp_logic", entry)
        _, tables = parse_logo(data)
        rows = []
        for i, jp in enumerate(tables[1]["strings"]):
            choices = lookup.get(localization_hash(jp), [])
            if not choices:
                if has_japanese(jp):
                    native_map_without_localization.append(dict(source=entry, index=i, japanese=jp,
                        classification="Native string without MapLogic localization; may be a control/event identifier or a native-only message. Full table preserved."))
                # The only source-language objective variant identified by the
                # existing native map-script work. Other unmapped pool strings
                # are preserved as metadata, not claimed to be visible text.
                if jp != "１．　ヒリュウ改、またはハガネの撃墜。":
                    continue
            assert len({e.text for e, _ in choices}) <= 1
            if choices:
                en, provenance = choices[0]
                used_map_keys.update((p["entry"], localization_hash(jp)) for _,p in choices)
                english, sources, ei = en.text, [p for _,p in choices], en.physical_index
            else:
                english, sources, ei = None, [], None
                unpaired.append(dict(category="map_text", source=entry, index=i, japanese=jp,
                                     reason="No official English entry for this exact native string hash"))
            rows.append(dict(id=f"SCR{sid:05}:{i:04}", block="Objectives, route choices and event messages",
                             jp_raw=jp, jp=jp.replace("@", "\n"), en=english, en_raw=english,
                             native_string_index=i, en_sources=sources, en_entry_index=ei))
        found = next((x for x in stage_index if x["scenario_id"] == sid), None)
        relative = found["folder"] + "/Map_text" if found else f"06_Developer_and_unassigned/SCR{sid:05}_Map_text"
        meta = dict(title_en=f"Map event text — S{sid:03}", title_jp="マップイベントテキスト",
                    native_entry=entry, scenario_id=sid, script_id=f"SCR{sid:05}",
                    description="String-table order, not runtime event order. Objectives and route-choice strings may be referenced more than once.")
        item = save_collection(out, relative, meta, rows)
        write_json(out / relative / "native_string_tables.json", tables)
        map_inventory.append(dict(source=entry, scenario_id=sid, rows=len(rows), folder=relative))
        if found:
            found["map_text_folder"] = relative
            found["map_text_rows"] = len(rows)
    assert used_map_keys == {(p["entry"],key) for key, choices in lookup.items() for e,p in choices}
    write_json(out / "data/map_inventory.json", map_inventory)
    write_json(out / "data/native_map_strings_without_localization.json", native_map_without_localization)

    # Narration in external Roll CSBs uses authored MLTD IDs, not string order.
    roll_sources = [("Roll_01_cnv", "PreStory", "Opening historical narration", "オープニング・前史", "05_Extras/Opening_narration"),
                    ("Roll_20_cnv", "S001_DEMO", "Touya's dream narration", "トーヤの夢", "05_Extras/Toya_dream_narration")]
    roll_inventory = []
    for stem, table, title, jp_title, relative in roll_sources:
        entry = f"Dat/Roll/Csb/{stem}.csb"
        data = s.read("jp_logic", entry)
        _, _, rs = parse_csb(data)
        es, provenance, _ = s.english("Talk/" + table + "_TextData")
        rows, used = [], set()
        for i, r in enumerate(rs):
            a = r["arguments"]
            if (stem == "Roll_01_cnv" and a[0] == "0") or (stem == "Roll_20_cnv" and a[0] == "19"):
                text_arg, id_arg = (1,13) if stem == "Roll_01_cnv" else (3,13)
                ei = int(a[id_arg]); used.add(ei)
                rows.append(dict(id=f"{stem}:{i:04}", block="Narration", command_index=i,
                                 jp_raw=a[text_arg], jp=a[text_arg], en=es[ei].text, en_raw=es[ei].text,
                                 en_source=provenance, en_entry_index=ei))
        unused = [dict(index=e.physical_index, en=e.text) for e in es if e.physical_index not in used]
        references = [dict(script_id=x["script_id"], commands=x["external_script_references"]) for x in stage_index
                      if any(r["filename"] == stem + ".csb" for r in x["external_script_references"])]
        item = save_collection(out, relative, dict(title_en=title, title_jp=jp_title, native_entry=entry,
            script_id=stem, referenced_by=references, description="Narration paired by the text command's authored localization entry ID."), rows,
            dict(unused_official_entries=unused))
        collections_index.append(item)
        roll_inventory.append(dict(source=entry, rows=len(rows), unused_english_entries=unused, referenced_by=references))
        for x in stage_index:
            if any(r["filename"] == stem + ".csb" for r in x["external_script_references"]):
                write_text(out / x["folder"] / "External_narration.txt", f"This script references {stem}.csb.\nRead the additional EN / JP / Bilingual narration in:\n{relative}\n")
    write_json(out / "data/roll_inventory.json", roll_inventory)

    # Earlier-game recap pages shipped with OGMD, separated from OGMD stages.
    recap_inventory = []
    for name in ["Archive_OG1", "Archive_OG2", "Archive_OGg", "Archive_2OG", "Archive_OGDP"]:
        entry = f"Dat/Archive/Csb/{name}.csb"
        native = s.read("jp_common", entry); donor = s.read("en_patch", entry)
        _, _, nr = parse_csb(native); _, _, er = parse_csb(donor)
        pairs = []
        for tag,i,j,k,l in difflib.SequenceMatcher(a=[r["arguments"][0] for r in nr],b=[r["arguments"][0] for r in er],autojunk=False).get_opcodes():
            if tag == "equal":
                pairs.extend(zip(range(i,j),range(k,l)))
            else:
                assert name == "Archive_OG1" and tag == "delete"
                assert [r["arguments"] for r in nr[i:j]] in ([["2","100","100"]], [["30","60","43"],["10","60"]])
        rows=[]
        for i,k in pairs:
            na,ea=nr[i]["arguments"],er[k]["arguments"]
            if na[0] == "42" and len(na) >= 4:
                assert na[:3] + na[4:] == ea[:3] + ea[4:len(na)]
                rows.append(dict(id=f"{name}:{i:04}", block="Recap", command_index=i, en_command_index=k,
                                 jp=na[3], jp_raw=na[3], en=ea[3], en_raw=ea[3]))
        assert len(rows) == sum(r["arguments"][0] == "42" and len(r["arguments"]) >= 4 for r in nr) == sum(r["arguments"][0] == "42" and len(r["arguments"]) >= 4 for r in er)
        item=save_collection(out, "05_Extras/Recaps/" + name, dict(title_en=name, title_jp="過去作品のあらすじ",
            script_id=name, native_entry=entry, en_archive="en_patch", description="Earlier-game archive recap pages; not OGMD stage dialogue."), rows)
        collections_index.append(item);recap_inventory.append(dict(file=name, rows=len(rows)))
    write_json(out / "data/recap_inventory.json", recap_inventory)
    print("Map scripts, narration, and archive recaps extracted.", flush=True)

    # Battle voice/subtitle messages are reusable across stages. Their complete
    # metadata must match before pairing records by index.
    battle_inventory = []
    jp_bmds = {e for e in s.entries["jp_battle"] if e.startswith("Dat/Battle/Message/@Ja/") and e.endswith(".bmd")}
    for entry in sorted(s.entries["en_lang"]):
        if not (entry.startswith("Dat/Battle/Message/@En/") and entry.endswith(".bmd")):
            continue
        filename = Path(entry).name
        jp_entry = "Dat/Battle/Message/@Ja/" + filename.replace("_en", "_ja")
        native=s.read("jp_battle", jp_entry); english=s.read("en_lang", entry)
        jn,js,jp,jt=parse_bmd(native);en,es,ep,et=parse_bmd(english)
        assert (jn,js,jp)==(en,es,ep) and native[:js]==english[:es]
        assert [t is None for t in jt]==[t is None for t in et]
        rows=[]
        for i,(j,e) in enumerate(zip(jt,et)):
            metadata=native[js+i*20:js+i*20+16]
            assert metadata==english[es+i*20:es+i*20+16]
            rows.append(dict(id=f"{filename[:4]}:{i:04d}", block="Reusable battle messages", message_index=i,
                             jp_raw=j, jp=j.replace("@", "\n") if j is not None else "[No subtitle text in this record]",
                             en_raw=e, en=e.replace("@", "\n") if e is not None else "[No subtitle text in this record]",
                             null_text=j is None, record_metadata_hex=metadata.hex()))
        relative="04_Shared/Battle_messages/" + filename[:4]
        item=save_collection(out, relative, dict(title_en="Battle message bank " + filename[:4], title_jp="戦闘メッセージ",
            native_entry=jp_entry, english_entry=entry, script_id="BMD"+filename[:4],
            description="Shared battle message bank. File ID is preserved; exclusive stage ownership is not inferred.",
            group_count=jn[0],condition_count=jn[1],group_condition_data_hex=native[8:js].hex()), rows)
        battle_inventory.append(dict(file=filename, jp_entry=jp_entry, records=len(rows), text_records=sum(j is not None for j in jt), folder=relative))
    assert jp_bmds == {r["jp_entry"] for r in battle_inventory}
    write_json(out / "data/battle_inventory.json", battle_inventory)
    write_text(out / "04_Shared/Battle_messages/INDEX.md", "# Shared battle messages\n\nThese banks are reusable across stages. Each folder contains EN.txt, JP.txt, Bilingual.txt and script.json.\n\n| Bank | Records | Paired script |\n|---|---:|---|\n" + "".join(f"| {Path(r['folder']).name} | {r['records']} | [Read]({Path(r['folder']).name}/Bilingual.txt) |\n" for r in battle_inventory))
    print(f"Battle: {len(battle_inventory)} banks; {sum(x['records'] for x in battle_inventory):,} records.", flush=True)

    # Verify the source files against earlier hash-checked extraction reports,
    # where available, without relying on their text or mappings.
    old_report=ROOT / "work/poc/full_english_20260906/story_reports"
    for item in story_inventory:
        previous=old_report / (item["script_id"].lower().replace("s","ls",1)+".json")
        if previous.exists():
            old=json.loads(previous.read_text(encoding="utf-8"))
            entry="Dat/logic/talk/"+previous.stem+".bin"
            assert old["source_sha256"]==s.used["jp_logic",entry]["sha256"], entry
    totals = dict(native_story_files=len(story_inventory), native_story_dialogue_commands=sum(x["native_commands"] for x in story_inventory),
                  exported_story_rows=sum(x["exported_rows"] for x in story_inventory),
                  shared_defeat_rows=len(death), shared_defeat_references=sum(x["shared_references"] for x in story_inventory),
                  map_files=len(map_inventory), map_text_rows=sum(x["rows"] for x in map_inventory),
                  narration_rows=sum(x["rows"] for x in roll_inventory), recap_pages=sum(x["rows"] for x in recap_inventory),
                  battle_banks=len(battle_inventory), battle_records=sum(x["records"] for x in battle_inventory),
                  empty_stage_localization_tables=len(empty_tables), unmatched_official_map_text=len(unpaired),
                  native_map_strings_without_localization=len(native_map_without_localization))
    assert totals["native_story_dialogue_commands"]==totals["exported_story_rows"]+totals["shared_defeat_references"]
    untranslated=[dict(script_id=x["script_id"], en_entry_index=e.physical_index, text=e.text)
                  for x in stage_index for e in s.english(f"Talk/{x['script_id']}_TextData")[0] if has_japanese(e.text)]
    write_json(out / "data/source_comparisons.json", source_comparisons)
    write_json(out / "data/story_inventory.json", story_inventory)
    write_json(out / "data/stage_index.json", stage_index)
    write_json(out / "data/unpaired_native_map_text.json", unpaired)
    write_json(out / "data/official_english_contains_japanese.json", untranslated)
    write_json(out / "data/collection_index.json", collections_index)
    write_json(out / "VALIDATION.json", dict(status="passed", totals=totals,
        checks=["All native story files paired to official English tables", "All PS3 story source bytes equal PS4 base source bytes",
                "Every dialogue command accounted for", "Every native block covers a validated contiguous command range",
                "Every stage localization table accounted for, including empty placeholders", "All MapLogic localization entries used",
                "All Japanese battle banks have English counterparts with identical event, voice and condition metadata",
                "Narration paired using authored localization IDs", "All native and English recap text commands paired"],
        limitations=dict(official_english_japanese_rows=len(untranslated),unmatched_native_map_text=unpaired,
                         source_order_is_not_a_single_playthrough=True,
                         special_s096_and_s999_runtime_placement_not_established=True)))
    write_index(out, stage_index, totals, empty_tables, untranslated, unpaired)
    manifest=[]
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in ("OUTPUT_MANIFEST.json", "SOURCE_MANIFEST.json"):
            data=p.read_bytes(); manifest.append(dict(path=p.relative_to(out).as_posix(),size=len(data),sha256=digest(data)))
    write_json(out / "OUTPUT_MANIFEST.json",manifest)
    write_json(out / "SOURCE_MANIFEST.json",dict(archives={k:dict(path=str(p),size=p.stat().st_size) for k,p in s.paths.items()},
        entries=list(s.used.values()), description="SHA-256 is recorded for every consumed decompressed archive entry. Archives were opened read-only."))
    print(json.dumps(totals,ensure_ascii=True,indent=2),flush=True)


def write_index(out, stages, totals, empty_tables, untranslated, unpaired):
    def link(folder, name):
        return f"[{name}]({folder}/{name}.txt)"
    lines=["# Super Robot Wars OG: The Moon Dwellers — English / Japanese script", "",
           "Extracted from pristine Japanese PS3 archives and the official English PS4 localization (including relevant v1.01 recap text).", "",
           "Each script folder contains **EN.txt**, **JP.txt**, **Bilingual.txt**, and **script.json**. Start with the paired text or choose a language below.", "",
           "Stages are categorized using the game's StageData records and both scenario charts. Native scenario IDs are not chapter numbers: S071 is Stage 1 Space, for example.", "",
           "Beginner chart chapter numbers are shown separately. S097 is its first stage, even though StageData retains chapter 2. The shared stages following it are consequently one chapter earlier in that chart.", "",
           "Text is in native authoring/command order, with scene-block IDs retained. Every conditional branch is included, so it is not a transcript of one playthrough. Dialogue displayed during map events is included with the stage's story. Reusable battle subtitles are indexed separately.", "",
           "## Stages and alternate versions", "",
           "| Normal chapter | Beginner chart | Route | Script | English stage name | Japanese stage name | Lines | Files |",
           "|---:|---:|---|---|---|---|---:|---|"]
    for x in sorted([x for x in stages if x["scenario_id"] <100],key=lambda x:(x.get("stage_data_chapter",0),x["scenario_id"])):
        normal=x.get("chart_membership",{}).get("normal",{}).get("sequence_chapter","—")
        beginner=x.get("chart_membership",{}).get("beginner",{}).get("sequence_chapter","—")
        files=" · ".join(link(x["folder"],name) for name in ["EN","JP","Bilingual"])
        lines.append(f"| {normal} | {beginner} | {x.get('classification_route','—')} | {x['script_id']} | {x['title_en'].strip()} | {x['title_jp']} | {x['rows']} | {files} |")
    lines += ["", "## Interludes, bonus and developer scripts", "",
              "| Associated StageData chapter | Script | Description | Lines | Files |", "|---:|---|---|---:|---|"]
    for x in [x for x in stages if x["scenario_id"]>=100]:
        files=" · ".join(link(x["folder"],name) for name in ["EN","JP","Bilingual"])
        lines.append(f"| {x.get('stage_data_chapter','—')} | {x['script_id']} | {x['title_en'].strip()} | {x['rows']} | {files} |")
    lines += ["", "## Additional scripts", "",
              "- [Shared defeat messages](04_Shared/Defeat_messages/Bilingual.txt): 82 lines indexed once; each stage JSON retains the native references.",
              "- [Reusable battle dialogue](04_Shared/Battle_messages/INDEX.md): all 263 Japanese/English message banks. Their file IDs are preserved; they are not assigned an exclusive stage.",
              "- [Opening historical narration](05_Extras/Opening_narration/Bilingual.txt).",
              "- [Touya's dream narration](05_Extras/Toya_dream_narration/Bilingual.txt): referenced by S001 and S097. Its 20 native text commands map to 20 of 21 English entries; unused entry 10 remains in script.json.",
              "- [OG1 recap](05_Extras/Recaps/Archive_OG1/Bilingual.txt), [OG2 recap](05_Extras/Recaps/Archive_OG2/Bilingual.txt), [OG Gaiden recap](05_Extras/Recaps/Archive_OGg/Bilingual.txt), [2nd OG recap](05_Extras/Recaps/Archive_2OG/Bilingual.txt), [OG Dark Prison recap](05_Extras/Recaps/Archive_OGDP/Bilingual.txt).",
              "- Each stage's **Map_text** subfolder contains objectives, route choices, and other map-event messages. Full original native string tables are also supplied.",
              "", "## Source fidelity and exceptions", "",
              "Official spelling, terminology, punctuation and line breaks are retained; the current PS3 fan-patch wording is not substituted. Japanese @ line-break markers are converted only in the readable text; exact strings and offsets remain in JSON. Speaker labels ??? and XN-L use readable Latin forms alongside their exact Japanese labels.", "",
              f"The official English S990 table contains {len(untranslated)} Japanese developer prompts. They remain visible and explicitly marked. {len(unpaired)} native map strings have no official exact-hash counterpart; their Japanese text is preserved and the English field is marked missing. See [exception data](data/unpaired_native_map_text.json).", "",
              "Native map pools also contain event/control identifiers such as Japanese Game Over and DM block names. All strings without a MapLogic localization entry remain in [native map metadata](data/native_map_strings_without_localization.json) and the full per-file tables; they are not counted as missing translated dialogue.", "",
              "S034 is Common in the native data and both route charts; its official English route label says To the Moon. The export classifies it as Common and retains that English source discrepancy in metadata.", "",
              "S096 is an alternate prologue absent from both charts. S999 is a special scene without a StageData record. Their precise runtime placement is not established; neither is assigned an invented numbered stage.", "",
              f"{len(empty_tables)} English stage tables contain only empty placeholder entries and have no native script. These are recorded in [empty localization tables](data/empty_localization_tables.json). Other unused/development string-pool entries are preserved in each native_strings.json.", "",
              "This export covers scenario dialogue, map-event text, narration, suspend conversations, shared battle dialogue, and the five prior-game recaps. Menus, unit/pilot encyclopedias, tutorial image text, staff-roll movie imagery and other non-script UI assets are outside this script collection.", "",
              "## Verification", "", "| Item | Count |", "|---|---:|"]
    lines += [f"| {k.replace('_',' ')} | {v:,} |" for k,v in totals.items()]
    lines += ["", "All source archives were read-only. [Validation report](VALIDATION.json), [source manifest](SOURCE_MANIFEST.json), [output checksums](OUTPUT_MANIFEST.json), and [machine-readable stage index](data/stage_index.json).", "",
              "To recreate: run `python tools/export_script_by_stage.py --output <new-output-directory>` from the workspace. The exporter requires the existing archive reader in the adjacent 2nd SRW OG workspace.", ""]
    write_text(out / "START_HERE.md", "\n".join(lines))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT / "script_export/OGMD_EN_JP_20260908")
    args=parser.parse_args()
    build(args.output.resolve())
