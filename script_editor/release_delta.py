"""Verified COPY/DATA recipes for exact PSARC reconstruction from vanilla data."""
import hashlib
import json
import struct
from pathlib import Path
from archive_patch import digest
from vendor.psarc import Psarc


def sdat_metadata(path, payload=None):
    """Read/replay the release's masked HMAC records, including random padding.

    Encryption uses deterministic keys/IVs here, but its 12-byte HMAC masking
    padding is random. Replaying verified records makes releases reproducible;
    normal SDAT verification still checks every HMAC and all plaintext bytes.
    """
    with Path(path).open('r+b' if payload is not None else 'rb') as stream:
        header=stream.read(256)
        flags,block_size,size=struct.unpack_from('>IIQ',header,0x80)
        if header[:4]!=b'NPD\0' or flags!=0x0100003C:raise ValueError('Unsupported SDAT metadata layout')
        count=(size+block_size-1)//block_size
        if payload is not None and len(payload)!=count*32:raise ValueError('Incomplete SDAT metadata')
        records=bytearray()
        for i in range(count):
            stream.seek(256+i*(block_size+32))
            if payload is None:
                record=stream.read(32)
                if len(record)!=32:raise ValueError('Truncated SDAT metadata')
                records.extend(record)
            else:stream.write(payload[i*32:(i+1)*32])
        return bytes(records)


def build_recipe(source, target, blob):
    source, target, blob = map(Path, (source, target, blob))
    old, new = Psarc(source), Psarc(target)
    index = {}
    with source.open('rb') as stream:
        for e in old.entries:
            offset = e.offset
            for n in old.block_table[e.block_index:e.block_index + (e.size + old.block_size - 1) // old.block_size]:
                n = n or old.block_size
                stream.seek(offset); raw = stream.read(n)
                if len(raw) != n: raise ValueError('Truncated source block')
                index.setdefault((n, hashlib.sha256(raw).digest()), offset)
                offset += n
    ranges = {}
    for e in new.entries:
        offset = e.offset
        for n in new.block_table[e.block_index:e.block_index + (e.size + new.block_size - 1) // new.block_size]:
            n = n or new.block_size
            if offset in ranges and ranges[offset] != n: raise ValueError('Conflicting block alias')
            ranges[offset] = n; offset += n
    ops = []
    def emit(kind, offset, size):
        if not size: return
        if ops and ops[-1][0] == kind and ops[-1][1] + ops[-1][2] == offset:
            ops[-1][2] += size
        else: ops.append([kind, offset, size])
    with target.open('rb') as stream, blob.open('xb') as out:
        position = 0
        for start, n in sorted(ranges.items()):
            if start < position: raise ValueError('Overlapping target blocks')
            if start > position:
                stream.seek(position); raw = stream.read(start-position)
                emit('data', out.tell(), len(raw)); out.write(raw)
            stream.seek(start); raw = stream.read(n)
            if len(raw) != n: raise ValueError('Truncated target block')
            match = index.get((n, hashlib.sha256(raw).digest()))
            if match is None: emit('data', out.tell(), n); out.write(raw)
            else: emit('copy', match, n)
            position = start+n
        stream.seek(position); raw = stream.read()
        emit('data', out.tell(), len(raw)); out.write(raw)
    return dict(source_sha256=digest(source), target_sha256=digest(target), size=target.stat().st_size,
                blob_sha256=digest(blob), blob_size=blob.stat().st_size, ops=ops)


def apply_recipe(source, blob, recipe, destination):
    source, blob, destination = map(Path, (source, blob, destination))
    if destination.exists() or destination.resolve() in (source.resolve(), blob.resolve()):
        raise ValueError('Choose a new recipe output')
    if digest(source) != recipe['source_sha256']: raise ValueError('Vanilla archive revision does not match this release')
    if digest(blob) != recipe['blob_sha256'] or blob.stat().st_size != recipe['blob_size']:
        raise ValueError('Release payload is damaged')
    total = 0
    for kind, offset, size in recipe['ops']:
        limit = source.stat().st_size if kind == 'copy' else blob.stat().st_size if kind == 'data' else -1
        if not all(type(v) is int for v in (offset, size)) or offset < 0 or size <= 0 or offset + size > limit:
            raise ValueError('Invalid release recipe range')
        total += size
    if total != recipe['size']: raise ValueError('Incomplete release recipe')
    with source.open('rb') as original, blob.open('rb') as payload, destination.open('xb') as out:
        for kind, offset, size in recipe['ops']:
            stream = original if kind == 'copy' else payload
            stream.seek(offset)
            while size:
                data = stream.read(min(size, 1024*1024))
                if not data: raise ValueError('Recipe input changed during reconstruction')
                out.write(data); size -= len(data)
    if digest(destination) != recipe['target_sha256']: raise ValueError('Reconstructed English archive checksum failed')
