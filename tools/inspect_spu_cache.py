"""Read-only inspection of RPCS3's spu-*-v1-tane.dat record format.

Format and CRC behavior follow SPUCommonRecompiler.cpp at e6235886,
spu_cache::get/add. Structural validity does not prove JIT correctness.
The source cache is never changed; an optional JSON output must not exist.
"""
import argparse
import binascii
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct


def inspect(data):
    pos = 0
    records = []
    error = None
    exact = Counter()
    variants = defaultdict(set)
    while pos < len(data):
        offset = pos
        if len(data) - pos < 8:
            error = {"offset": pos, "reason": "truncated record header"}
            break
        crc, words, address = struct.unpack_from(">HHI", data, pos)
        pos += 8
        size = words * 4
        if address + size > 0x40000:
            error = {"offset": offset, "reason": "record exceeds SPU local store"}
            break
        if pos + size > len(data):
            error = {"offset": offset, "reason": "truncated instruction data"}
            break
        payload = data[pos:pos + size]
        pos += size
        calculated = max(binascii.crc_hqx(payload, 0xFFFF), 1)
        skip_old = not words or payload[:4] == bytes(4)
        accepted = not skip_old and (not crc or crc == calculated)
        digest = hashlib.sha256(payload).hexdigest()
        if accepted:
            exact[(address, digest)] += 1
            variants[address].add(digest)
        records.append({
            "offset": offset, "address": f"0x{address:05x}",
            "words": words, "crc": f"0x{crc:04x}",
            "calculated_crc": f"0x{calculated:04x}",
            "old_format_crc_absent": crc == 0,
            "old_giga_or_empty_skipped": skip_old,
            "accepted_by_cache_reader": accepted, "sha256": digest,
        })
    return {
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "parsed_bytes": pos, "structure_error": error,
        "record_count": len(records),
        "accepted_count": sum(r["accepted_by_cache_reader"] for r in records),
        "crc_mismatch_count": sum(
            not r["old_format_crc_absent"]
            and r["crc"] != r["calculated_crc"] for r in records),
        "old_format_crc_absent_count": sum(r["old_format_crc_absent"] for r in records),
        "old_giga_or_empty_skipped_count": sum(r["old_giga_or_empty_skipped"] for r in records),
        "exact_duplicate_accepted_records": sum(n - 1 for n in exact.values()),
        "entry_addresses_with_multiple_code_variants": sum(len(v) > 1 for v in variants.values()),
        "caveat": "Valid records do not establish that precompiling them is behaviorally correct; multiple code variants at one address are not inherently corrupt.",
        "records": records,
    }


def self_test():
    assert binascii.crc_hqx(b"123456789", 0xFFFF) == 0x29B1
    code = bytes.fromhex("402000007f000001")
    crc = max(binascii.crc_hqx(code, 0xFFFF), 1)
    valid = struct.pack(">HHI", crc, 2, 0x100) + code
    good = inspect(valid)
    assert good["accepted_count"] == 1 and good["structure_error"] is None
    damaged = inspect(valid[:-1] + bytes([valid[-1] ^ 1]))
    assert damaged["accepted_count"] == 0 and damaged["crc_mismatch_count"] == 1
    assert inspect(valid[:-1])["structure_error"]["reason"] == "truncated instruction data"
    assert inspect(valid + b"x")["structure_error"]["reason"] == "truncated record header"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    self_test()
    report = {"path": str(args.cache), **inspect(args.cache.read_bytes())}
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)


if __name__ == "__main__":
    main()
