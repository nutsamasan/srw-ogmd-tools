"""Read-only RPCS3 RRC v6 (Windows LE, e6235886) capture inspector.

Schema: RSXThread.cpp serialize specializations, Capture/rsx_replay.h,
rsx_methods.h, Program/program_util.h, and util/serialization.hpp.
No emulator process is accessed. The optional JSON output is a new analysis file.
"""

import argparse
import gzip
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError(f"Out-of-bounds read at {self.pos:#x}, size {size}")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))

    def count(self):
        value = 0
        for shift in range(0, 28, 7):
            byte, = self.unpack('B')
            value |= (byte & 0x7f) << shift
            if not byte & 0x80:
                if value > len(self.data) - self.pos:
                    raise ValueError('Container count exceeds remaining bytes')
                return value
        raise ValueError('Unsupported/invalid VLE length')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path, names):
    compressed = path.read_bytes()
    data = gzip.decompress(compressed)
    r = Reader(data)
    if r.unpack('III') != (0x00435252, 6, 1):
        raise ValueError('Only RRC v6 little-endian captures are supported')
    sections = []

    def mark(name, start, count):
        sections.append(dict(name=name, start=start, end=r.pos, count=count))

    start = r.pos
    tiles = []
    for _ in range(r.count()):
        tile_words = r.unpack('108I')  # 15 * 4 + 8 * 6 u32
        state_id, = r.unpack('Q')
        tiles.append(dict(state_id=state_id, words=list(tile_words)))
    mark('tile_map', start, len(tiles))

    start = r.pos
    memory = []
    for _ in range(r.count()):
        offset, location, data_state = r.unpack('IIQ')
        state_id, = r.unpack('Q')
        memory.append(dict(offset=offset, location=location,
                           data_state=data_state, state_id=state_id))
    mark('memory_map', start, len(memory))

    start = r.pos
    memory_data = []
    for _ in range(r.count()):
        blob = r.take(r.count())
        state_id, = r.unpack('Q')
        memory_data.append(dict(size=len(blob), sha256=sha(blob), state_id=state_id))
    mark('memory_data_map', start, len(memory_data))

    start = r.pos
    displays = []
    for _ in range(r.count()):
        buffers = [dict(zip(('width', 'height', 'pitch', 'offset'), r.unpack('IIII')))
                   for _ in range(8)]
        count, = r.unpack('I')
        if count > 8:
            raise ValueError('Invalid display buffer count')
        state_id, = r.unpack('Q')
        displays.append(dict(state_id=state_id, count=count, buffers=buffers))
    mark('display_buffers_map', start, len(displays))

    start = r.pos
    commands = []
    for index in range(r.count()):
        header, argument = r.unpack('II')
        memory_states = [r.unpack('Q')[0] for _ in range(r.count())]
        tile_state, display_state = r.unpack('QQ')
        method = header & 0xfffc
        argument_count = (header >> 18) & 0x7ff
        # The capture inserts a synthetic NO_OPERATION register index, not a
        # FIFO packet. It has count=0 and does not submit a drawing operation.
        synthetic = index == 0 and header == 0x100 // 4 and argument_count == 0
        commands.append(dict(index=index, header=f'0x{header:08x}',
            method=f'0x{method:04x}', argument=f'0x{argument:08x}',
            name='SYNTHETIC_INITIAL_STATE_NOP' if synthetic else names.get(method, 'UNKNOWN'),
            argument_count=argument_count, memory_states=memory_states,
            tile_state=tile_state, display_state=display_state))
    mark('replay_commands', start, len(commands))

    # Normal RRC captures do not serialize transform_constants. These are not
    # savestates. 544 instructions * 4 words from program_util.h.
    start = r.pos
    program = r.take(544 * 4 * 4)
    mark('initial_transform_program', start, 544)
    start = r.pos
    registers_data = r.take(0x10000)
    registers = struct.unpack('<16384I', registers_data)
    mark('initial_registers', start, len(registers))
    if r.pos != len(data):
        raise ValueError(f'Unexpected trailing data: {len(data) - r.pos} bytes')

    tile_ids = {s['state_id'] for s in tiles}
    display_ids = {s['state_id'] for s in displays}
    memory_ids = {s['state_id'] for s in memory}
    data_ids = {s['state_id'] for s in memory_data}
    for command in commands:
        if command['tile_state'] and command['tile_state'] not in tile_ids:
            raise ValueError('Unresolved tile state')
        if command['display_state'] and command['display_state'] not in display_ids:
            raise ValueError('Unresolved display state')
        if any(state not in memory_ids for state in command['memory_states']):
            raise ValueError('Unresolved memory state')
    if any(block['data_state'] not in data_ids for block in memory):
        raise ValueError('Unresolved memory data state')

    named_registers = [dict(offset=f'0x{i*4:04x}', name=names.get(i*4, 'UNKNOWN'),
                            value=f'0x{value:08x}')
                       for i, value in enumerate(registers) if value]
    program_words = struct.unpack('<2176I', program)
    result = dict(path=str(path), compressed_bytes=len(compressed),
        decompressed_bytes=len(data), sha256=sha(compressed),
        decompressed_sha256=sha(data), validated_exact_eof=True,
        sections=sections, tiles=tiles, memory_blocks=memory, memory_data=memory_data,
        displays=displays, commands=commands,
        command_counts=dict(Counter(c['name'] for c in commands)),
        initial_transform_program_sha256=sha(program),
        initial_transform_program_nonzero_words=sum(bool(w) for w in program_words),
        initial_registers_sha256=sha(registers_data),
        initial_nonzero_registers=named_registers)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', type=Path)
    parser.add_argument('--enums', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    names = {int(value, 16): name for name, value in re.findall(
        r'\b([A-Z][A-Z0-9_]+)\s*=\s*(0[xX][0-9A-Fa-f]+)\s*>>\s*2',
        args.enums.read_text(encoding='utf-8'))}
    results = [inspect(path, names) for path in args.captures]
    output = dict(schema_commit='e6235886', captures=results)
    if args.output:
        # Refuse to overwrite any existing file, especially original captures.
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(output, stream, indent=2)
    for result in results:
        print(Path(result['path']).name)
        print(f"  bytes: {result['compressed_bytes']} -> {result['decompressed_bytes']}; exact EOF valid")
        print('  sections:', ', '.join(f"{s['name']}={s['count']}" for s in result['sections']))
        print('  commands:', result['command_counts'])
        print('  vertex program nonzero words:', result['initial_transform_program_nonzero_words'])
        for display in result['displays']:
            print('  display buffers:', display['buffers'][:display['count']])
    if len(results) > 1:
        base = {reg['offset']: reg for reg in results[0]['initial_nonzero_registers']}
        for result in results[1:]:
            other = {reg['offset']: reg for reg in result['initial_nonzero_registers']}
            print('Register differences vs first:', Path(result['path']).name)
            for offset in sorted(set(base) | set(other)):
                before = base.get(offset, {}).get('value', '0x00000000')
                after = other.get(offset, {}).get('value', '0x00000000')
                if before != after:
                    print(' ', offset, (other.get(offset) or base[offset])['name'], before, '->', after)


if __name__ == '__main__':
    main()
