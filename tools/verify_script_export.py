"""Independently re-read source records, check the exported corpus, then zip it."""
import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script_editor/vendor'))
from psarc import Psarc
from port_mltd_stage import parse_mltd, read_cstring, localization_hash, mltd_lookup


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def verify(folder):
    read_json = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    manifest = read_json(folder / "SOURCE_MANIFEST.json")
    arcs = {key: Psarc(Path(v["path"])) for key,v in manifest["archives"].items()}
    entries = {key: {e.name.lstrip("/"):e for e in arc.entries} for key,arc in arcs.items()}
    blobs = {}
    for item in manifest["entries"]:
        key = item["archive"], item["entry"]
        data = arcs[key[0]]._read_file(entries[key[0]][key[1]])
        assert len(data) == item["size"] and sha(data) == item["sha256"], key
        blobs[key] = data
    print(f"Source hashes: {len(blobs)} archive entries verified.", flush=True)
    mltd = {}
    for key, data in blobs.items():
        if key[1].endswith(".mltd"):
            mltd[key] = parse_mltd(data)[0]
    stages = read_json(folder / "data/stage_index.json")
    deaths = read_json(folder / "04_Shared/Defeat_messages/script.json")["rows"]
    dialogue_checked = 0
    for stage in stages:
        path = folder / stage["folder"]
        obj = read_json(path / "script.json")
        data = blobs["jp_logic", stage["native_entry"]]
        number, table = struct.unpack_from(">I", data, 0x0C)[0], struct.unpack_from(">I", data, 0x14)[0]
        offsets = struct.unpack_from(f">{number}I",data,table)
        strings = [read_cstring(data,o) for o in offsets]
        assert [x["text"] for x in read_json(path / "native_strings.json")] == strings
        n,start = struct.unpack_from(">II",data,0x20)
        expected = {}
        for i in range(n):
            p = start+i*196
            if struct.unpack_from(">I",data,p)[0] != 0:
                continue
            ni, ti = struct.unpack_from(">II",data,p+12)
            if strings[ti]:
                expected[i] = (strings[ni],strings[ti],p,ti)
        observed = {}
        for row in obj["rows"]:
            i=row["command_index"]
            assert i not in observed
            observed[i] = row["speaker_jp"],row["jp_raw"],row["command_offset"],row["jp_string_index"]
            assert observed[i] == expected[i]
            src=row["en_source"]
            assert row["en"] == row["en_raw"] == mltd[src["archive"],src["entry"]][row["en_entry_index"]].text
            assert row["jp"] == row["jp_raw"].replace("@","\n")
            b=obj["blocks"][row["block_index"]]
            assert b["name"]==row["block"] and b["first_command"] <= i < b["first_command"]+b["command_count"]
        for ref in obj["shared_defeat_references"]:
            i=ref["command_index"]
            assert i not in observed
            shared=deaths[int(ref["shared_id"].split(":")[1])]
            assert (shared["speaker_jp"],shared["jp_raw"]) == expected[i][:2]
            observed[i]=expected[i]
        assert observed==expected,stage["script_id"]
        dialogue_checked += len(expected)
    assert dialogue_checked == read_json(folder / "VALIDATION.json")["totals"]["native_story_dialogue_commands"]
    # Confirm an independent source-data join for all stage names/route records.
    from ogmd_text_formats import parse_fixed
    fixed=parse_fixed(blobs["jp_logic","Dat/FixedData/StageData.dat"])
    stage_names=mltd["en_lang","Dat/MultiLanguage/@En/FixedData/StageName.mltd"]
    for st in read_json(folder / "data/stage_metadata.json"):
        physical=fixed.logical_indices[st["scenario_id"]]
        record=fixed.records[physical]
        assert physical==st["stage_data_physical_index"]
        assert st["title_jp"]==fixed.strings[record[3]] and st["title_en"]==stage_names[physical].text
        assert st["stage_data_chapter"]==record[1]
    battle_checked=0
    for bank in read_json(folder / "data/battle_inventory.json"):
        obj=read_json(folder / bank["folder"] / "script.json")
        meta=obj["metadata"]
        j=blobs["jp_battle",meta["native_entry"]];e=blobs["en_lang",meta["english_entry"]]
        g,c,n=struct.unpack_from(">3H",j,2);base=8+g*12+c*20;pool=base+n*20
        assert j[:base]==e[:base] and n==len(obj["rows"])
        for i,row in enumerate(obj["rows"]):
            p=base+i*20
            assert j[p:p+16]==e[p:p+16]==bytes.fromhex(row["record_metadata_hex"])
            for lang,data in [("jp",j),("en",e)]:
                pointer=struct.unpack_from(">I",data,p+16)[0]
                source=None if pointer==0xFFFFFFFF else read_cstring(data,pool+pointer)
                assert row[lang+"_raw"]==source
        battle_checked+=n
    # Check every emitted file against the manifest and ensure text is valid UTF-8.
    output_manifest=read_json(folder / "OUTPUT_MANIFEST.json")
    for item in output_manifest:
        data=(folder/item["path"]).read_bytes()
        assert sha(data)==item["sha256"] and len(data)==item["size"], item["path"]
        content=data.decode("utf-8-sig")
        assert "\ufffd" not in content, item["path"]
    tracked={x["path"] for x in output_manifest}|{"OUTPUT_MANIFEST.json","SOURCE_MANIFEST.json"}
    assert tracked=={p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    links=0
    for p in folder.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)",p.read_text(encoding="utf-8-sig")):
            assert (p.parent/target).is_file(),(p,target)
            links+=1
    result=dict(status="passed",source_entries_checked=len(blobs),story_files_checked=len(stages),
                story_commands_checked=dialogue_checked,battle_records_checked=battle_checked,
                output_files_checked=len(tracked),markdown_links_checked=links)
    print(json.dumps(result,indent=2),flush=True)
    archive=folder.with_suffix(".zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p,arcname=folder.name+"/"+p.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(tracked)
    result["zip"]=dict(path=str(archive),size=archive.stat().st_size,sha256=sha(archive.read_bytes()),full_crc_verification=True)
    report=folder.with_name(folder.name+"_verification.json")
    report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result["zip"],indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder",nargs="?",type=Path,default=ROOT/"script_export/OGMD_EN_JP_20260908")
    verify(p.parse_args().folder.resolve())
