"""Strict readers/writers for the native OGMD text containers."""
from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass

from port_mltd_stage import read_cstring, parse_ldbi_table


def align(value, alignment=128):
    return (value + alignment - 1) // alignment * alignment


def rebuild_ldbi_pool(source, replacements, record_variants=()):
    count, table, offsets = parse_ldbi_table(source)
    boundary = struct.unpack_from(">I", source, 0x1C)[0]
    start = min(offsets)
    assert start == 0x80 and table % 128 == 0
    assert table + count * 4 <= boundary <= len(source)
    texts = [read_cstring(source, offset) for offset in offsets]
    assert all(start <= offset < table for offset in offsets)
    assert all(offset + len(text.encode("utf-8")) + 1 <= table for offset, text in zip(offsets, texts))
    for index, text in replacements.items():
        assert 0 <= index < count
        texts[index] = text
    out = bytearray(source)
    variant_indices = {}
    changes = []
    for record, original_index, english in record_variants:
        assert struct.unpack_from(">I", source, record + 12)[0] == original_index
        if texts[original_index] == english:
            continue
        key = (original_index, english)
        if key not in variant_indices:
            variant_indices[key] = len(texts)
            texts.append(english)
        index = variant_indices[key]
        struct.pack_into(">I", out, record + 12, index)
        changes.append(dict(record_offset=record, original_index=original_index, new_index=index))
    payload = bytearray()
    new_offsets = []
    seen = {}
    for text in texts:
        if text not in seen:
            seen[text] = start + len(payload)
            payload.extend(text.encode("utf-8") + b"\0")
        new_offsets.append(seen[text])
    new_table = align(start + len(payload))
    required_end = new_table + len(new_offsets) * 4
    if required_end > boundary:
        raise ValueError(f"LDBI pool needs {required_end - boundary} more bytes before the next section")
    out[start:boundary] = bytes(boundary - start)
    out[start:start + len(payload)] = payload
    struct.pack_into(">I", out, 0x0C, len(new_offsets))
    struct.pack_into(">I", out, 0x14, new_table)
    struct.pack_into(f">{len(new_offsets)}I", out, new_table, *new_offsets)
    result = bytes(out)
    n, t, o = parse_ldbi_table(result)
    assert n == len(texts) and t == new_table and len(result) == len(source)
    assert [read_cstring(result, p) for p in o] == texts
    allowed = bytearray(len(source))
    for a, b in [(start, boundary), (0x0C, 0x10), (0x14, 0x18)]:
        allowed[a:b] = b"\1" * (b - a)
    for change in changes:
        p = change["record_offset"] + 12
        allowed[p:p + 4] = b"\1" * 4
    assert all(a == b or allowed[i] for i, (a, b) in enumerate(zip(source, result)))
    return result, dict(original_count=count, output_count=n, original_table=table,
                        output_table=t, pool_end=boundary, free_pool_bytes=boundary - required_end,
                        split_records=changes, all_pointers_verified=True,
                        structural_bytes_preserved=True)


def dialogue_grid(data):
    count, _, offsets = parse_ldbi_table(data)
    number, start = struct.unpack_from(">II", data, 0x20)
    assert start + number * 196 <= len(data)
    records = []
    for k in range(number):
        p = start + 4 + k * 196
        # Each 0xC4 command begins four bytes before its payload. Opcode 0
        # is dialogue. A color-setting command can coincidentally contain a
        # valid string index (S030: RGB value 255); never scan its parameters
        # as text. Developer dialogues can legitimately omit quote brackets.
        if struct.unpack_from(">I", data, p - 4)[0] != 0:
            continue
        index = struct.unpack_from(">I", data, p + 12)[0]
        name_index = struct.unpack_from(">I", data, p + 8)[0]
        if index >= count or name_index >= count:
            continue
        text = read_cstring(data, offsets[index])
        if text:
            records.append((p, index, offsets[index], text))
    return records


@dataclass
class FixedData:
    source: bytes
    chunks: dict
    logical_indices: list
    records: list
    strings: list
    string_headers: list


def parse_fixed(data):
    chunks = {}
    p = 0
    while p < len(data):
        tag, size = struct.unpack_from(">4sI", data, p)
        if tag not in {b"FIXH", b"DOFS", b"DATA", b"SOFS", b"STRI"} or tag in chunks:
            raise ValueError(f"Unsupported FIXH chunk at {p:x}: {tag!r}")
        extra = 4 if tag in {b"DATA", b"STRI"} else 0
        end = p + 8 + extra + size
        if end > len(data):
            raise ValueError("Fixed-data chunk past EOF")
        chunks[tag] = (p, size)
        p = end
    assert list(chunks) in ([b"FIXH", b"DOFS", b"DATA", b"SOFS", b"STRI"],
                            [b"FIXH", b"DATA", b"SOFS", b"STRI"])
    rp, rs = chunks[b"DATA"]
    record_count = struct.unpack_from(">I", data, rp + 8)[0]
    if b"DOFS" in chunks:
        dp, ds = chunks[b"DOFS"]
        logical = list(struct.unpack_from(f">{ds // 4}I", data, dp + 8))
    else:
        logical = list(range(record_count))
    assert record_count and rs % record_count == 0
    stride = rs // record_count
    records = [data[rp + 12 + k * stride:rp + 12 + (k + 1) * stride] for k in range(record_count)]
    assert all(i == 0xFFFFFFFF or i < record_count for i in logical)
    sp, ss = chunks[b"SOFS"]
    tp, ts = chunks[b"STRI"]
    offsets = struct.unpack_from(f">{ss // 4}I", data, sp + 8)
    assert len(offsets) == struct.unpack_from(">I", data, tp + 8)[0]
    strings, headers = [], []
    for relative in offsets:
        record = tp + 12 + relative
        lines = struct.unpack_from(">H", data, record)[0]
        text_base = record + 2 + lines * 4
        values = []
        for line in range(lines):
            chars, offset = struct.unpack_from(">HH", data, record + 2 + line * 4)
            text = read_cstring(data, text_base + offset)
            assert text_base + offset + len(text.encode("utf-8")) + 1 <= tp + 12 + ts
            assert chars == len(text), (chars, len(text))
            values.append(text)
        strings.append("\n".join(values))
        headers.append(data[record:text_base])
    return FixedData(data, chunks, logical, records, strings, headers)


def rebuild_fixed(fixed, replacements, field_variants=()):
    sp, ss = fixed.chunks[b"SOFS"]
    tp, ts = fixed.chunks[b"STRI"]
    texts = [replacements.get(i, text) for i, text in enumerate(fixed.strings)]
    records = [bytearray(r) for r in fixed.records]
    added = {}
    for record, offset, width, text in field_variants:
        fmt = {1: ">B", 2: ">H"}[width]
        old = struct.unpack_from(fmt, fixed.records[record], offset)[0]
        assert old < len(fixed.strings)
        if texts[old] == text:
            continue
        key = (old, text)
        if key not in added:
            added[key] = len(texts)
            texts.append(text)
        new = added[key]
        if new >= 2 ** (width * 8):
            raise ValueError(f"Fixed-data variant index {new} does not fit {width} bytes")
        struct.pack_into(fmt, records[record], offset, new)
    out = bytearray(fixed.source[:sp])
    rp, rs = fixed.chunks[b"DATA"]
    out[rp + 12:rp + 12 + rs] = b"".join(records)
    out.extend(struct.pack(">4sI", b"SOFS", len(texts) * 4) + bytes(len(texts) * 4))
    tp = len(out)
    out.extend(struct.pack(">4sII", b"STRI", 0, len(texts)))
    payload = bytearray()
    for index, text in enumerate(texts):
        struct.pack_into(">I", out, sp + 8 + index * 4, len(payload))
        lines = text.split("\n")
        header = bytearray(struct.pack(">H", len(lines)))
        encoded = bytearray()
        for line in lines:
            assert len(line) <= 65535 and len(encoded) <= 65535
            header.extend(struct.pack(">HH", len(line), len(encoded)))
            encoded.extend(line.encode("utf-8") + b"\0")
        payload.extend(header + encoded)
    size = max(ts, align(len(payload), 4))
    struct.pack_into(">I", out, tp + 4, size)
    out.extend(payload + bytes(size - len(payload)))
    result = bytes(out)
    verified = parse_fixed(result)
    assert verified.records == [bytes(r) for r in records] and verified.logical_indices == fixed.logical_indices
    assert verified.strings == texts
    allowed = {(record, i) for record, offset, width, text in field_variants for i in range(offset, offset + width)}
    assert all(a == b or (k, i) in allowed for k, (old, new) in enumerate(zip(fixed.records, verified.records))
               for i, (a, b) in enumerate(zip(old, new)))
    for record, offset, width, text in field_variants:
        index = int.from_bytes(verified.records[record][offset:offset + width], "big")
        assert verified.strings[index] == text
    return result


def rebuild_csb(source, edits):
    """Rebuild CSB text for {(command ordinal, argument ordinal): string}."""
    from port_mltd_roll import parse_csb
    chunks, strings, records = parse_csb(source)
    sp, ss, sc = chunks[b'STRP']
    lp, ls, lc = chunks[b'LNP ']
    tp, ts, tc = chunks[b'LNT ']
    assert sp == 0x18 and lp == sp + ss and tp == lp + ls
    references = defaultdict(list)
    for k, record in enumerate(records):
        for j, ptr in enumerate(record['pointers']):
            references[ptr].append(edits.get((k,j), strings[ptr]))
    payload, new_pointers = bytearray(), {}
    def intern(text):
        if text not in new_pointers:
            new_pointers[text] = sp + 12 + len(payload)
            payload.extend(text.encode('utf8') + b'\0')
        return new_pointers[text]
    for ptr, original in strings.items():
        for text in references.get(ptr, [original]):
            intern(text)
    new_size = max(ss, align(12 + len(payload), 4))
    delta = new_size - ss
    out = bytearray(source[:sp])
    out.extend(struct.pack('>4sII',b'STRP',new_size,len(new_pointers)))
    out.extend(payload + bytes(new_size - 12 - len(payload)))
    out.extend(source[lp:])
    for k, record in enumerate(records):
        r = record['offset'] + delta
        struct.pack_into('>I',out,r+4,r+8)
        for j, original in enumerate(record['arguments']):
            struct.pack_into('>I',out,r+8+j*4,new_pointers[edits.get((k,j),original)])
        struct.pack_into('>I',out,tp+delta+12+k*4,r)
    result = bytes(out)
    _,_,actual = parse_csb(result)
    assert len(actual) == len(records)
    assert all(r['arguments'] == [edits.get((k,j),text) for j,text in enumerate(records[k]['arguments'])]
               for k,r in enumerate(actual))
    assert all(0 <= k < len(records) and 0 <= j < len(records[k]['arguments']) for k,j in edits)
    return result
