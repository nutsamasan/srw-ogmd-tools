"""Compare saved memory at display-buffer offsets identified in OGMD RRCs.

Offline analysis only. Buffer images are interpretations of saved guest memory,
not host GPU screenshots. Channel order must be verified against visible data.
"""
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image
from inspect_savestate_vm import State

ROOT = (Path(__file__).resolve().parents[1] / 'work/investigation_title_20260904')


def main():
    summary = []
    for index in range(3):
        path = ROOT / 'savestates' / f'BLJS10335_1_{index}.SAVESTAT.zst'
        state = State(path)
        dest = ROOT / f'state{index}'
        dest.mkdir(exist_ok=True)
        report = state.report()
        report['frames'] = []
        print(path.name, state.meta['timestamp'], 'decompressed', len(state.data), flush=True)
        for slot, offset in enumerate([0x10000, 0x3d0000]):
            raw = state.read(0xc0000000 + offset, 1280 * 720 * 4)
            pixels = np.frombuffer(raw, np.uint8).reshape(720, 1280, 4)
            values, counts = np.unique(pixels.reshape(-1, 4), axis=0, return_counts=True)
            top = np.argsort(counts)[-5:][::-1]
            stats = dict(slot=slot, address=f'0x{0xc0000000+offset:08x}',
                sha256=hashlib.sha256(raw).hexdigest(), unique_pixels=len(values),
                channel_mean=pixels.mean(axis=(0, 1)).tolist(),
                top_raw_pixels=[dict(bytes=values[i].tolist(), count=int(counts[i])) for i in top])
            report['frames'].append(stats)
            print(' display', slot, 'unique',len(values), 'top', stats['top_raw_pixels'], flush=True)
            Image.fromarray(pixels[:, :, [1, 2, 3]]).save(dest / f'display{slot}_argb.png')
            Image.fromarray(pixels[:, :, [2, 1, 0]]).save(dest / f'display{slot}_bgra.png')
        fxo = state.data[state.meta['fxo_start']:]
        print('FXO header', repr(fxo[:100]))
        candidates = []
        start = 0
        while (reg := fxo.find(struct.pack('<I', 0x31337000), start)) >= 0:
            start = reg + 1
            if reg < 8704 + 8192 or reg + 65536 > len(fxo):
                continue
            # Three independently known initial-context object/register values.
            if (struct.unpack_from('<I',fxo,reg+0x180)[0] == 0x66604200
                    and struct.unpack_from('<I',fxo,reg+0xe000)[0] == 0xcafebabe):
                registers = struct.unpack_from('<16384I', fxo, reg)
                candidate = dict(fxo_registers_offset=reg,
                    absolute_registers_offset=reg+state.meta['fxo_start'],
                    initial_state_offset=reg-8704-8192,
                    registers={f'0x{i*4:04x}':f'0x{v:08x}' for i,v in enumerate(registers) if v})
                candidates.append(candidate)
        report['rsx_register_candidates'] = candidates
        print('Validated RSX register signature candidates:', [c['fxo_registers_offset'] for c in candidates])
        report['texture_memory'] = []
        for offset in [0x01100000, 0x014c0000]:
            raw = state.read(0xc0000000 + offset, 1280 * 720 * 4)
            pixels = np.frombuffer(raw, np.uint8).reshape(720, 1280, 4)
            stats = dict(offset=f'0x{offset:08x}', sha256=hashlib.sha256(raw).hexdigest(),
                         channel_mean=pixels.mean(axis=(0, 1)).tolist(),
                         min=pixels.min(axis=(0,1)).tolist(), max=pixels.max(axis=(0,1)).tolist())
            report['texture_memory'].append(stats)
            print(' Texture', stats, flush=True)
            Image.fromarray(pixels[:, :, [1, 2, 3]]).save(dest / f'texture_{offset:08x}_argb.png')
            Image.fromarray(pixels[:, :, [2, 1, 0]]).save(dest / f'texture_{offset:08x}_bgra.png')
        with (dest/'frame_analysis.json').open('w',encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
        with (dest/'fxo_section.bin').open('wb') as stream:
            stream.write(fxo)
        summary.append(dict(state=index, timestamp=state.meta['timestamp'],
                            frames=report['frames'], rsx_candidates=len(candidates)))
    with (ROOT/'savestate_frames_summary.json').open('w',encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2)


if __name__ == '__main__':
    main()
