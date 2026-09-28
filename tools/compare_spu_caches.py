"""Compare two RPCS3 SPU cache files without modifying either file."""

import argparse
from collections import Counter
from pathlib import Path

from inspect_spu_cache import inspect


def identities(records):
    return [(r["address"], r["words"], r["sha256"]) for r in records
            if r["accepted_by_cache_reader"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("older", type=Path)
    parser.add_argument("newer", type=Path)
    args = parser.parse_args()

    old = inspect(args.older.read_bytes())
    new = inspect(args.newer.read_bytes())
    old_ids = identities(old["records"])
    new_ids = identities(new["records"])
    old_set = set(old_ids)
    new_set = set(new_ids)
    common_prefix = 0
    for left, right in zip(old_ids, new_ids):
        if left != right:
            break
        common_prefix += 1

    print(f"older: {len(old_ids)} records, {old['sha256']}")
    print(f"newer: {len(new_ids)} records, {new['sha256']}")
    print(f"shared exact records: {len(old_set & new_set)}")
    print(f"only older: {len(old_set - new_set)}")
    print(f"only newer: {len(new_set - old_set)}")
    print(f"same-position common prefix: {common_prefix}")
    print(f"newer duplicate identities: {sum(v - 1 for v in Counter(new_ids).values())}")


if __name__ == "__main__":
    main()
