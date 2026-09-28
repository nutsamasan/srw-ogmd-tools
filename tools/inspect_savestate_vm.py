"""Offline VM reader for RPCS3 e6235886 savestates, global format version 22.

Decodes only the header and VM section, not the full FXO serialization.
Original files and the running emulator are never modified or accessed.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import zstandard


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError(f'Invalid read at {self.pos:#x}, length {size:#x}')
        result = memoryview(self.data)[self.pos:self.pos + size]
        self.pos += size
        return result

    def get(self, fmt):
        values = struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))
        return values[0] if len(values) == 1 else values

    def count(self):
        result = 0
        for shift in range(0, 35, 7):
            value = self.get('B')
            result |= (value & 127) << shift
            if not value & 128:
                if result > len(self.data) - self.pos:
                    raise ValueError('Unbounded variable length')
                return result
        raise ValueError('Invalid variable length')

    def string(self):
        return bytes(self.take(self.count())).decode('utf-8')


POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)


class Sparse:
    def __init__(self, reader, size):
        if size % 4096 or size > 0x100000000:
            raise ValueError('Invalid memory size')
        self.size = size
        self.bitmap_offset = reader.pos
        self.bitmap = np.frombuffer(reader.take(size // 1024), dtype=np.uint8)
        self.prefix = np.concatenate((np.zeros(1, dtype=np.uint64), np.cumsum(POPCOUNT[self.bitmap], dtype=np.uint64)))
        self.packed_offset = reader.pos
        self.packed = reader.take(int(self.prefix[-1]) * 128)

    def read(self, offset, size):
        if offset < 0 or offset + size > self.size:
            raise ValueError('Memory read exceeds allocation')
        first, end = offset // 128, (offset + size + 127) // 128
        indices = np.arange(first, end, dtype=np.int64)
        bitmap = self.bitmap[indices // 8]
        bits = indices % 8
        active = (bitmap & (1 << bits)) != 0
        rank = self.prefix[indices // 8] + POPCOUNT[bitmap & ((1 << bits) - 1)]
        out = np.zeros((end - first, 128), dtype=np.uint8)
        packed = np.frombuffer(self.packed, dtype=np.uint8).reshape(-1, 128)
        out[active] = packed[rank[active].astype(np.int64)]
        return out.reshape(-1)[offset % 128:offset % 128 + size].tobytes()


class State:
    def __init__(self, path):
        self.path = path
        with path.open('rb') as source, zstandard.ZstdDecompressor().stream_reader(source, read_across_frames=True) as stream:
            self.data = stream.read(1024 * 1024 * 1024 + 1)
            if len(self.data) > 1024 * 1024 * 1024:
                raise ValueError('Savestate exceeds 1 GiB analysis limit')
        r = Reader(self.data)
        if bytes(r.take(8)) != b'RPCS3SAV' or r.get('B') != 1:
            raise ValueError('Not a little-endian RPCS3 savestate')
        inspection = r.get('B')
        version_offset, following = r.get('QB')
        if version_offset != r.pos or following != 1:
            raise ValueError('Unsupported version-table location')
        versions = [r.get('HH') for _ in range(r.count())]
        if dict(versions).get(0) != 22:
            raise ValueError('Only global version 22 is implemented')
        if r.get('B') != 1:
            raise ValueError('Unsupported metadata marker')
        self.meta = dict(inspection_mode=inspection, versions=versions,
                        build=r.string(), timestamp=r.string(), title=r.string(), note=r.string())
        if any(r.take(32)):
            raise ValueError('Unexpected reserved header data')
        self.meta['boot_path'] = r.string()
        self.meta['disc'] = r.string()
        r.take(16)  # Opaque key field, deliberately not emitted in analysis.
        self.meta['game_dir'] = r.string()
        self.meta['hdd1'] = r.string()
        if self.meta['hdd1']:
            r.take(r.get('Q'))
        hdd0 = []
        while name := r.string():
            size = r.get('Q')
            r.take(size)
            hdd0.append(dict(name=name, bytes=size))
        self.meta['included_hdd0'] = hdd0
        if any(r.take(32)):
            raise ValueError('Unexpected pre-VM reserved data')
        self.meta['vm_start'] = r.pos
        count = r.get('Q')
        if not 0 < count < 10000:
            raise ValueError('Invalid shared-memory count')
        shared = []
        for shared_index in range(count):
            flags, size = r.get('IQ')
            shared.append((flags, Sparse(r, size)))
        self.shared = shared
        self.blocks = []
        self.allocations = []
        count = r.get('Q')
        if count > 10000:
            raise ValueError('Invalid location count')
        for index in range(count):
            if not r.get('B'):
                continue
            addr, size, flags = r.get('IIQ')
            self.blocks.append(dict(index=index, address=f'0x{addr:08x}', size=size, flags=flags))
            while pages := r.get('B'):
                if not pages & 128:
                    raise ValueError('Invalid allocation page flags')
                start, length = r.get('II')
                if not addr <= start < start + length <= addr + size:
                    raise ValueError('Allocation outside location')
                if flags & 0x20:
                    guard = 4096 if flags & 0x10 else 0
                    region = Sparse(r, length - guard * 2)
                    self.allocations.append((start + guard, length - guard * 2, region))
                else:
                    shared_index = r.get('Q')
                    if shared_index >= len(shared):
                        raise ValueError('Invalid shared-memory reference')
                    region = shared[shared_index][1]
                    if length > region.size:
                        raise ValueError('Shared-memory allocation size mismatch')
                    self.allocations.append((start, length, region))
        self.meta['fxo_start'] = r.pos
        self.meta['decompressed_bytes'] = len(self.data)

    def read(self, address, size):
        for start, length, region in self.allocations:
            if start <= address and address + size <= start + length:
                return region.read(address - start, size)
        raise ValueError(f'Unmapped range: {address:#x}+{size:#x}')

    def report(self):
        return dict(path=str(self.path), metadata=self.meta, blocks=self.blocks,
                    allocations=[dict(address=f'0x{start:08x}', size=size,
                       bitmap_offset=region.bitmap_offset, packed_offset=region.packed_offset,
                       packed_bytes=len(region.packed)) for start, size, region in self.allocations])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--extract', action='append', default=[], help='Hex address:length (both hex)')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    state = State(args.state)
    report = state.report()
    print(json.dumps(report, indent=2, ensure_ascii=True))
    for spec in args.extract:
        address, size = [int(s, 16) for s in spec.split(':')]
        data = state.read(address, size)
        target = args.out / f'memory_{address:08x}_{size:x}.bin'
        with target.open('xb') as stream:
            stream.write(data)
        print('Extracted', target, 'sha256', hashlib.sha256(data).hexdigest())
    with (args.out / 'vm_analysis.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    with (args.out / 'fxo_section.bin').open('xb') as stream:
        stream.write(memoryview(state.data)[state.meta['fxo_start']:])


if __name__ == '__main__':
    main()
