"""Capture a frozen OGMD file-read failure using query/read process access only.

Run after the failure, before stopping emulation. No emulator state, game file,
configuration, or save is changed. Output is restricted to this game's guest
stacks and bounded reachable loader/heap pages plus its RPCS3 log.
"""
import argparse
import ctypes
import datetime
import hashlib
import json
import re
import struct
import subprocess
from collections import deque
from ctypes import wintypes as w
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RPC = Path(r'local_data/rpcs3')


def parse_failure(text):
    marker = "fios mediathread 2's thread context:"
    start = text.rfind(marker)
    if start < 0:
        raise ValueError('The log has no recorded mediathread 2 crash context.')
    block = text[start:]
    if 'In function: sys_fs_read' not in block[:500]:
        raise ValueError('The latest context is not the expected file-read failure.')
    regs = {int(n): int(value, 16) for n, value in
            re.findall(r'^r(\d+)\s*[^:]*:\s*(0x[0-9a-fA-F]+)', block, re.M)}
    stack = re.search(r'Stack: (0x[0-9a-f]+)\.\.(0x[0-9a-f]+)', block)
    if not stack or not {1, 3, 4, 5, 6, 26}.issubset(regs):
        raise ValueError('The recorded failure is incomplete.')
    return regs, tuple(int(x, 16) for x in stack.groups())


def snapshot_log(rpc, out):
    log = rpc/'log/RPCS3.log'
    # rg opens the live Windows log with sharing compatible with RPCS3.
    result = subprocess.run(['rg', '--text', '--no-line-number', '^', str(log)],
                            capture_output=True, check=True)
    (out/'RPCS3.log').write_bytes(result.stdout)
    return result.stdout.decode('utf8', errors='replace')


def capture(pid, rpc=DEFAULT_RPC):
    now = datetime.datetime.now(datetime.timezone.utc)
    out = ROOT/'work/poc/endgame_crash_20260921'/('capture_'+now.strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    text = snapshot_log(rpc, out)
    regs, stack = parse_failure(text)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    handle = k.OpenProcess(0x1010, False, pid)  # QUERY_LIMITED_INFORMATION | VM_READ
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def host_read(address, size):
        data = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if not k.ReadProcessMemory(handle, address, data, size, ctypes.byref(count)) or count.value != size:
            raise ctypes.WinError(ctypes.get_last_error())
        return data.raw

    try:
        # Native FIOS instructions, independent of the font-hook revision.
        expected = bytes.fromhex('7f9b07b4809a0050e8ba004038c100907f63db78')
        base = None
        for candidate in (0x400000000, 0x300000000, 0x200000000):
            try:
                if host_read(candidate+0xb18964, len(expected)) == expected:
                    base = candidate
                    break
            except OSError:
                pass
        if base is None:
            raise RuntimeError('The OGMD guest is no longer readable. Leave the crashed game frozen before retrying.')

        def read(address, size):
            return host_read(base+address, size)

        request = read(regs[26], 0x58)
        length = struct.unpack_from('>Q', request, 0x40)[0]
        buffer = struct.unpack_from('>I', request, 0x50)[0]
        if (length, buffer) != (regs[5], regs[4]):
            raise RuntimeError('The current loader request differs from the logged crash. Refusing a stale capture.')

        report = dict(pid=pid, captured_utc=now.isoformat(), host_base=hex(base),
                      process_access='query and read only', memory_modified=False,
                      registers={str(n): hex(value) for n, value in regs.items()},
                      request_address=hex(regs[26]), read_buffer=hex(buffer),
                      read_size=length, file_descriptor=regs[3], captures=[], strings=[])
        seen = set()
        queue = deque()

        def enqueue(raw):
            for (value,) in struct.iter_unpack('>I', raw[:len(raw)//4*4]):
                if 0x30000000 <= value < 0x40000000 or 0xe80000 <= value < 0x1100000:
                    page = value & ~0xfff
                    if page not in seen:
                        queue.append(page)

        def save(address, raw):
            name = f'guest_{address:08x}.bin'
            (out/name).write_bytes(raw)
            report['captures'].append(dict(address=hex(address), size=len(raw),
                                           file=name, sha256=hashlib.sha256(raw).hexdigest()))
            for match in re.finditer(rb'[ -~]{8,}', raw):
                s = match.group().decode('ascii')
                if '/Dat/' in s or '.psarc' in s or '.PSSG' in s or '.edp' in s:
                    report['strings'].append(dict(address=hex(address+match.start()), text=s[:512]))
            enqueue(raw)

        save(stack[0], read(stack[0], stack[1]-stack[0]+1))
        save(0xd0001000, read(0xd0001000, 0x20000))
        for value in regs.values():
            enqueue(struct.pack('>I', value & 0xffffffff))
        while queue and len(seen) < 256:
            page = queue.popleft()
            if page in seen:
                continue
            seen.add(page)
            try:
                raw = read(page, 0x1000)
            except OSError:
                continue
            save(page, raw)
        report['reachable_page_limit'] = 256
        report['capture_complete'] = True
        (out/'capture.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
        print(json.dumps(dict(output=str(out/'capture.json'), pages=len(report['captures']),
                              file_descriptor=regs[3], buffer=hex(buffer), size=length)))
    finally:
        k.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int)
    parser.add_argument('--rpc', type=Path, default=DEFAULT_RPC)
    args = parser.parse_args()
    capture(args.pid, args.rpc)
