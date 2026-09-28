"""Compare OGMD savestate local VRAM without modifying RPCS3 or game data.

The comparison is performed at the 128-byte granularity used by RPCS3's
sparse savestate encoding.  It reports pairwise byte/block differences and
groups consecutive differing blocks so candidate render targets can be found.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from inspect_savestate_vm import State


ROOT = (Path(__file__).resolve().parents[1] / 'work/investigation_title_20260904')
BASE = 0xC0000000
CHUNK = 0x100000
BLOCK = 128


def append_run(runs, mask, first_block, end_block):
    if not mask:
        return
    start = BASE + first_block * BLOCK
    end = BASE + end_block * BLOCK
    if runs and runs[-1]["mask"] == mask and int(runs[-1]["end"], 16) == start:
        runs[-1]["end"] = f"0x{end:08x}"
        runs[-1]["bytes"] += end - start
        runs[-1]["blocks"] += end_block - first_block
    else:
        runs.append({
            "mask": mask,
            "start": f"0x{start:08x}",
            "end": f"0x{end:08x}",
            "bytes": end - start,
            "blocks": end_block - first_block,
        })


def main():
    paths = [ROOT / "savestates" / f"BLJS10335_1_{i}.SAVESTAT.zst" for i in range(3)]
    states = [State(path) for path in paths]
    allocations = [next((size, region) for start, size, region in state.allocations if start == BASE)
                   for state in states]
    sizes = [size for size, _ in allocations]
    if len(set(sizes)) != 1:
        raise ValueError(f"VRAM allocation sizes differ: {sizes}")
    size = sizes[0]

    report = {
        "inputs": [str(path) for path in paths],
        "timestamps": [state.meta["timestamp"] for state in states],
        "base": f"0x{BASE:08x}",
        "size": size,
        "block_size": BLOCK,
        "mask_meaning": {
            "3": "state0 differs; state1 equals state2",
            "5": "state1 differs; state0 equals state2",
            "6": "state2 differs; state0 equals state1",
            "7": "all three differ",
        },
        "chunks": [],
        "runs": [],
    }
    total_masks = Counter()
    pair_byte_totals = [0, 0, 0]
    pair_block_totals = [0, 0, 0]
    digesters = [hashlib.sha256() for _ in states]
    runs = report["runs"]
    open_mask = 0
    open_first = 0

    for offset in range(0, size, CHUNK):
        length = min(CHUNK, size - offset)
        raw = [state.read(BASE + offset, length) for state in states]
        for digest, data in zip(digesters, raw):
            digest.update(data)
        arrays = [np.frombuffer(data, dtype=np.uint8).reshape(-1, BLOCK) for data in raw]
        pair_bytes = [int(np.count_nonzero(arrays[0] != arrays[1])),
                      int(np.count_nonzero(arrays[0] != arrays[2])),
                      int(np.count_nonzero(arrays[1] != arrays[2]))]
        pair_blocks_arr = [np.any(arrays[0] != arrays[1], axis=1),
                           np.any(arrays[0] != arrays[2], axis=1),
                           np.any(arrays[1] != arrays[2], axis=1)]
        pair_blocks = [int(x.sum()) for x in pair_blocks_arr]
        pair_byte_totals = [a + b for a, b in zip(pair_byte_totals, pair_bytes)]
        pair_block_totals = [a + b for a, b in zip(pair_block_totals, pair_blocks)]
        masks = (pair_blocks_arr[0].astype(np.uint8)
                 | (pair_blocks_arr[1].astype(np.uint8) << 1)
                 | (pair_blocks_arr[2].astype(np.uint8) << 2))
        counts = Counter(int(x) for x in masks)
        total_masks.update(counts)
        absolute_first = offset // BLOCK
        for local, mask in enumerate(masks):
            mask = int(mask)
            absolute = absolute_first + local
            if mask != open_mask:
                append_run(runs, open_mask, open_first, absolute)
                open_mask = mask
                open_first = absolute
        stats = []
        for array in arrays:
            stats.append({
                "nonzero_bytes": int(np.count_nonzero(array)),
                "mean": float(array.mean()),
                "stddev": float(array.std()),
            })
        report["chunks"].append({
            "start": f"0x{BASE + offset:08x}",
            "bytes": length,
            "pair_changed_bytes_01_02_12": pair_bytes,
            "pair_changed_blocks_01_02_12": pair_blocks,
            "mask_block_counts": {str(key): value for key, value in sorted(counts.items()) if key},
            "state_stats": stats,
        })
        print(f"{BASE + offset:08x}: blocks {pair_blocks} bytes {pair_bytes}", flush=True)

    append_run(runs, open_mask, open_first, size // BLOCK)
    report["pair_changed_bytes_01_02_12"] = pair_byte_totals
    report["pair_changed_blocks_01_02_12"] = pair_block_totals
    report["mask_block_counts"] = {str(key): value for key, value in sorted(total_masks.items())}
    report["state_vram_sha256"] = [digest.hexdigest() for digest in digesters]
    report["runs_by_mask"] = {str(mask): sum(1 for run in runs if run["mask"] == mask)
                              for mask in sorted(total_masks) if mask}
    report["largest_runs"] = sorted(runs, key=lambda run: run["bytes"], reverse=True)[:100]

    target = ROOT / "savestate_vram_comparison.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {target}")
    print("Pair byte totals 01/02/12:", pair_byte_totals)
    print("Pair block totals 01/02/12:", pair_block_totals)
    print("Mask totals:", dict(sorted(total_masks.items())))
    print("Largest runs:")
    for run in report["largest_runs"][:30]:
        print(run)


if __name__ == "__main__":
    main()
