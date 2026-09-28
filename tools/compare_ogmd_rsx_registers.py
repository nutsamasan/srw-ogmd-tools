"""Compare the serialized RSX method registers in three OGMD savestates."""

import json
import re
import struct
from pathlib import Path


ROOT = (Path(__file__).resolve().parents[1] / 'work/investigation_title_20260904')
ENUMS = ROOT / "source_e6235886" / "gcm_enums.h"


def load_method_names():
    names = {}
    pattern = re.compile(r"^\s*(NV[A-Z0-9_]+)\s*=\s*(0x[0-9a-fA-F]+)\s*>>\s*2")
    for line in ENUMS.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            names.setdefault(int(match.group(2), 16) >> 2, []).append(match.group(1))
    return names


def describe(index, names):
    if index in names:
        return ", ".join(names[index])
    previous = [value for value in names if value <= index]
    if not previous:
        return "unknown"
    base = max(previous)
    return f"{names[base][0]} + 0x{(index - base) * 4:x}"


def main():
    names = load_method_names()
    registers = []
    sources = []
    for index in range(3):
        report = json.loads((ROOT / f"state{index}" / "frame_analysis.json").read_text(encoding="utf-8"))
        offset = report["rsx_register_candidates"][0]["fxo_registers_offset"]
        fxo = (ROOT / f"state{index}" / "fxo_section.bin").read_bytes()
        registers.append(struct.unpack_from("<16384I", fxo, offset))
        sources.append({"state": index, "fxo_registers_offset": offset})

    rows = []
    relation_counts = {"all_equal": 0, "state0_unique": 0, "state1_unique": 0,
                       "state2_unique": 0, "all_different": 0}
    for index, values in enumerate(zip(*registers)):
        if values[0] == values[1] == values[2]:
            relation_counts["all_equal"] += 1
            continue
        if values[1] == values[2]:
            relation = "state0_unique"
        elif values[0] == values[2]:
            relation = "state1_unique"
        elif values[0] == values[1]:
            relation = "state2_unique"
        else:
            relation = "all_different"
        relation_counts[relation] += 1
        rows.append({
            "method_index": index,
            "method_offset": f"0x{index * 4:04x}",
            "name": describe(index, names),
            "relation": relation,
            "values": [f"0x{value:08x}" for value in values],
        })

    result = {"sources": sources, "relation_counts": relation_counts,
              "changed_register_count": len(rows), "registers": rows}
    target = ROOT / "savestate_rsx_register_comparison.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
