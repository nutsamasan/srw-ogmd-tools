"""Backed-up, atomic WeaponData archive edits; adapted from the proven pilot patcher."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from .archive_patch import digest, repack
from .weapon_data import PatchError, read_weapons, prepare_weapons
from .vendor.psarc import Psarc
from .vendor import sdat

WEAPON_ENTRY = '/Dat/FixedData/WeaponData.dat'
FILENAMES = ('Logic.psarc.sdat', 'Logic.psarc')


def resolve_target(value):
    path = Path(value).expanduser().resolve()
    if path.is_file() and path.name in FILENAMES:
        return path
    if path.is_dir():
        for relative in ('', 'PSARC', 'USRDIR/PSARC', 'PS3_GAME/USRDIR/PSARC',
                         'dev_hdd0/game/BLJS10335/USRDIR/PSARC', 'game/BLJS10335/USRDIR/PSARC'):
            for name in FILENAMES:
                candidate = path/relative/name
                if candidate.is_file():
                    return candidate.resolve()
    raise PatchError('Select Logic.psarc.sdat, its PSARC/game folder, or the RPCS3 folder. '
                     'For an ISO installation, select the installed dev_hdd0/game/BLJS10335 archive.')


def snapshot(path):
    before = Path(path).stat()
    checksum = digest(path)
    after = Path(path).stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PatchError('The archive changed while reading. Stop the game and read it again.')
    return dict(sha256=checksum, size=after.st_size, mtime_ns=after.st_mtime_ns)


def assert_snapshot(path, expected):
    if snapshot(path) != expected:
        raise PatchError('The archive changed after it was read. Read it again before writing.')


def _entry(arc, name):
    entries = [e for e in arc.entries if e.name == name]
    if len(entries) != 1:
        raise PatchError('Expected exactly one native archive entry: '+name)
    return arc._read_file(entries[0])


def _decode(source, plain, progress):
    with Path(source).open('rb') as stream:
        magic = stream.read(4)
    if magic == b'NPD\0':
        with Path(source).open('rb') as stream:
            stream.seek(0x80)
            header = stream.read(16)
        if len(header) != 16 or int.from_bytes(header[:4], 'big') != 0x0100003C:
            raise PatchError('Unsupported SDAT encryption layout.')
        block_size = int.from_bytes(header[4:8], 'big')
        plain_size = int.from_bytes(header[8:], 'big')
        if block_size != 0x4000 or not 0 < plain_size <= Path(source).stat().st_size:
            raise PatchError('Unsupported SDAT block size or length.')
        progress('Decrypting and verifying the game archive…')
        sdat.decrypt(source, plain, verbose=False)
        if not sdat.verify(source, expect_plain=plain, verbose=False):
            raise PatchError('The source archive failed SDAT verification.')
        return True
    if magic != b'PSAR':
        raise PatchError('This file is not a supported PSARC or SDAT archive.')
    shutil.copyfile(source, plain)
    return False


@contextmanager
def target_lock(path):
    lock = path.with_name(path.name+'.weapon-settings.lock')
    try:
        handle = lock.open('x', encoding='utf8')
    except FileExistsError as exc:
        raise PatchError('Another patch operation owns '+str(lock)+'. If an earlier run crashed, '
                         'close all patcher windows and remove that lock file before retrying.') from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_json(path, data):
    temporary = path.with_name(path.name+'.tmp')
    with temporary.open('w', encoding='utf8') as out:
        json.dump(data, out, indent=2, ensure_ascii=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)


def atomic_copy(source, target, expected):
    fd, temporary = tempfile.mkstemp(prefix=target.name+'.weapon-', suffix='.tmp', dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as out, Path(source).open('rb') as src:
            shutil.copyfileobj(src, out, 1024*1024)
            out.flush()
            os.fsync(out.fileno())
        os.utime(temporary, ns=(expected['mtime_ns'], expected['mtime_ns']))
        if snapshot(temporary) != expected:
            raise PatchError('The replacement copy did not match its checksum, size and timestamp.')
        os.replace(temporary, target)
        if snapshot(target) != expected:
            raise PatchError('The installed archive failed verification.')
    finally:
        temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, target, progress=lambda text: None):
        self.target = resolve_target(target)
        self._temporary = tempfile.TemporaryDirectory(prefix='ogmd-weapon-settings-')
        self.work = Path(self._temporary.name)
        try:
            self.original = snapshot(self.target)
            self.source = self.work/self.target.name
            shutil.copy2(self.target, self.source)
            if snapshot(self.source) != self.original:
                raise PatchError('The source changed while it was copied. Read the archive again.')
            assert_snapshot(self.target, self.original)
            self.plain = self.work/'source.psarc'
            self.encrypted = _decode(self.source, self.plain, progress)
            arc = Psarc(self.plain)
            if (arc.ver_major, arc.ver_minor, arc.compression, arc.toc_entry_size) != (1, 4, b'zlib', 30):
                raise PatchError('Unsupported archive layout.')
            self.weapon = _entry(arc, WEAPON_ENTRY)
            self.weapons = read_weapons(self.weapon)
            assert_snapshot(self.target, self.original)
        except Exception:
            self.close()
            raise

    def close(self):
        self._temporary.cleanup()

    def defaults(self, weapon_ids=None):
        return {uid: self.weapons[uid].defaults for uid in (self.weapons if weapon_ids is None else weapon_ids)}

    def install(self, updates, progress=lambda text: None):
        replacement, changes = prepare_weapons(self.weapon, updates)
        if not changes:
            raise PatchError('There are no weapon changes to write.')
        with target_lock(self.target):
            assert_snapshot(self.target, self.original)
            token = uuid.uuid4().hex
            plain = self.work/(token+'.psarc')
            verification = repack(self.plain, plain, {WEAPON_ENTRY: replacement}, progress=progress)
            output = plain
            if self.encrypted:
                output = self.work/(token+'.sdat')
                progress('Encrypting and verifying every SDAT block…')
                sdat.encrypt(plain, output, self.source, verbose=False)
                if not sdat.verify(output, expect_plain=plain, verbose=False):
                    raise PatchError('The rebuilt archive failed SDAT verification.')
            if output.stat().st_size != self.original['size']:
                raise PatchError('The rebuilt archive does not have the original file size.')
            after = dict(sha256=digest(output), size=self.original['size'], mtime_ns=self.original['mtime_ns'])
            return self._commit(output, after, changes, verification, 'patch', progress)

    def restore_backup(self, manifest, progress=lambda text: None):
        manifest = Path(manifest).resolve()
        doc = json.loads(manifest.read_text(encoding='utf8'))
        if (doc.get('format') != 'ogmd-weapon-settings-v1' or Path(doc.get('target', '')).resolve() != self.target
                or doc.get('filename') != self.target.name):
            raise PatchError('This backup belongs to a different archive.')
        if doc.get('after') != self.original:
            raise PatchError('The archive has changed since that patch. Use Restore all defaults '
                             'to preserve newer changes, or choose the matching latest backup.')
        backup = manifest.parent/doc['filename']
        expected = doc['before']
        if snapshot(backup) != expected:
            raise PatchError('The backup is missing or failed checksum verification.')
        with target_lock(self.target):
            assert_snapshot(self.target, self.original)
            return self._commit(backup, expected, [], {'backup_verified': True}, 'restore-backup', progress)

    def _commit(self, output, after, changes, verification, operation, progress):
        assert_snapshot(self.target, self.original)
        folder = self.target.parent/'_weapon_settings_backups'/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        backup = folder/self.target.name
        atomic_copy(self.source, backup, self.original)
        manifest = folder/'patch.json'
        doc = dict(format='ogmd-weapon-settings-v1', operation=operation, status='prepared',
                   created_utc=datetime.now(timezone.utc).isoformat(), target=str(self.target),
                   filename=self.target.name, before=self.original, after=after, changes=changes,
                   verification=verification)
        atomic_json(manifest, doc)
        assert_snapshot(self.target, self.original)
        progress('Backup verified. Installing and checking the archive…')
        attempted = False
        try:
            doc['status'] = 'installing'
            atomic_json(manifest, doc)
            # Recheck after backup and immediately before replacement.
            assert_snapshot(self.target, self.original)
            attempted = True
            atomic_copy(output, self.target, after)
            doc['status'] = 'complete'
            atomic_json(manifest, doc)
        except Exception as exc:
            if attempted:
                try:
                    atomic_copy(backup, self.target, self.original)
                except Exception as recovery:
                    raise PatchError(f'Write failed and automatic restoration failed: {recovery}. '
                                     f'Restore the verified backup at {backup}.') from exc
            doc['status'] = 'rolled-back' if attempted else 'not-installed'
            try:
                atomic_json(manifest, doc)
            except OSError:
                pass
            raise
        return dict(manifest=str(manifest), backup=str(backup), changes=len(changes), sha256=after['sha256'])
