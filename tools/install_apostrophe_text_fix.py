"""Install or restore the verified contraction correction, with backups.

RPCS3 may stay open, but the game must be stopped. An exclusive read-open test
refuses installation while either target archive is in use. The existing editor
installer provides checksum guards, backups, atomic replacement, and recovery.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'script_editor'), str(ROOT/'work/pydeps')]
from patcher import install_patch

MANIFEST = ROOT/'work/poc/apostrophe_text_fix_20260922/patch.json'


def require_archives_idle(doc):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                             w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    handles = []
    try:
        for target in doc['targets']:
            for archive in doc['archives']:
                path = Path(target)/archive['file']
                handle = k.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    code = ctypes.get_last_error()
                    raise RuntimeError(f'Stop the game before installing/restoring; cannot exclusively read {path} (Windows error {code}). RPCS3 may stay open.')
                handles.append(handle)
    finally:
        for handle in handles:
            k.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--install', action='store_true')
    group.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    doc = json.loads(MANIFEST.read_text(encoding='utf8'))
    assert doc['status'] == 'ready' and doc['changed_rows'] == 5
    assert {a['name'] for a in doc['archives']} == {'Battle', 'Logic'}
    verification = json.loads((MANIFEST.parent/'native_spacing_verification.json').read_text(encoding='utf8'))
    assert verification['status'] == 'passed'
    semantic = json.loads((MANIFEST.parent/'semantic_verification.json').read_text(encoding='utf8'))
    assert semantic['status'] == 'passed'
    assert sum(len(row['changes']) for row in semantic['results']) == 5
    require_archives_idle(doc)
    if args.check:
        print('Both game archives are idle; RPCS3 itself may remain open.')
        return
    result = install_patch(MANIFEST, restore=args.restore,
                           progress=lambda message: print(message, flush=True),
                           closed_check=lambda: require_archives_idle(doc))
    print(json.dumps(dict(status=result['status'], completed=result['completed'])))


if __name__ == '__main__':
    main()
