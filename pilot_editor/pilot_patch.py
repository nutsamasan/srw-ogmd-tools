"""Narrow, reversible PilotData edits; archive transactions adapted from the mech patcher."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from archive_patch import digest, repack
from build_catalog import structure, SPIRIT_OFFSETS, EDIT_OFFSETS, profile
from fixed_data import parse_fixed
from vendor.psarc import Psarc
from vendor import sdat

CATALOG = json.loads((Path(__file__).parent/'catalog.json').read_text(encoding='utf8'))
PILOTS = {int(k): v for k, v in CATALOG['pilots'].items()}
SPIRITS = {int(k): v for k, v in CATALOG['spirits'].items()}
PERSONALITIES = {int(k): v for k, v in CATALOG['personalities'].items()}
PILOT_ENTRY = '/Dat/FixedData/PilotData.dat'
SPIRIT_ENTRY = '/Dat/FixedData/SpiritData.dat'
FILENAMES = ('Logic.psarc.sdat', 'Logic.psarc')


class PatchError(ValueError):
    pass


@dataclass(frozen=True)
class SpiritSlot:
    command: int
    cost: int
    level: int
    flag: int = 0


@dataclass(frozen=True)
class PilotSettings:
    personality: int
    spirits: tuple[SpiritSlot, ...]


@dataclass(frozen=True)
class Pilot:
    pilot_id: int
    name: str
    installed_name: str
    settings: PilotSettings
    defaults: PilotSettings


def settings(doc):
    return PilotSettings(doc['personality'], tuple(SpiritSlot(**s) for s in doc['spirits']))


def read_table(raw, kind):
    try:
        fixed = parse_fixed(raw)
        stride = 336 if kind == 'pilot' else 12
        if not fixed.records or any(len(row) != stride for row in fixed.records):
            raise PatchError('Unexpected native record size.')
        if structure(fixed, kind) != CATALOG[kind+'_structure']:
            raise PatchError('Unsupported Moon Dwellers '+kind+' table. Other games/regions and modified pilot stats are not supported.')
        return fixed
    except PatchError:
        raise
    except Exception as exc:
        raise PatchError('The native '+kind+' table is damaged or unsupported.') from exc


def read_pilots(raw):
    fixed = read_table(raw, 'pilot')
    result = {}
    for pid, item in PILOTS.items():
        row = fixed.records[fixed.logical_indices[pid]]
        name_index = int.from_bytes(row[2:4], 'big')
        if name_index >= len(fixed.strings):
            raise PatchError('Invalid pilot name pointer.')
        current = settings(profile(row))
        if current.personality not in PERSONALITIES or any(s.command not in SPIRITS for s in current.spirits):
            raise PatchError('Unsupported Spirit Command or Will profile ID.')
        result[pid] = Pilot(pid, item['name'], fixed.strings[name_index], current, settings(item['defaults']))
    return result


def validate_settings(value, original, defaults=None):
    if not isinstance(value, PilotSettings) or type(value.personality) is not int or value.personality not in PERSONALITIES:
        raise PatchError('Choose one of the supported Will response profiles.')
    if len(value.spirits) != 6 or any(not isinstance(s, SpiritSlot) for s in value.spirits):
        raise PatchError('Choose five normal commands and one Twin command.')
    for index, (s, old) in enumerate(zip(value.spirits, original.spirits)):
        if any(type(x) is not int for x in (s.command, s.cost, s.level, s.flag)):
            raise PatchError('Command settings must be whole numbers.')
        if s == old or (defaults is not None and s == defaults.spirits[index]):
            continue
        if s.command not in SPIRITS:
            raise PatchError('Choose a named Spirit Command or Empty.')
        if s.command == 0:
            if s != SpiritSlot(0, 65535, -1, -1):
                raise PatchError('Empty slots must use the native empty-slot values.')
        elif not (0 <= s.cost <= 999 and 1 <= s.level <= 99 and s.flag == (old.flag if old.command else 0)):
            raise PatchError(f'Slot {index+1}: SP cost must be 0–999 and unlock level 1–99.')
    normal = [s.command for s in value.spirits[:5] if s.command]
    if len(normal) != len(set(normal)) and value.spirits != original.spirits and value != defaults:
        raise PatchError('Do not repeat a command among the five normal slots.')


def prepare_pilot(raw, updates):
    fixed = read_table(raw, 'pilot')
    pilots = read_pilots(raw)
    result = bytearray(raw)
    changes, allowed = [], set()
    for pid, value in updates.items():
        if type(pid) is not int or pid not in pilots:
            raise PatchError('Choose a supported pilot; the dummy pilot cannot be edited.')
        pilot = pilots[pid]
        validate_settings(value, pilot.settings, pilot.defaults)
        if value == pilot.settings:
            continue
        base = fixed.chunks[b'DATA'][0] + 12 + fixed.logical_indices[pid]*336
        result[base+0x13] = value.personality
        for off, s in zip(SPIRIT_OFFSETS, value.spirits):
            result[base+off] = s.command
            result[base+off+2:base+off+4] = s.cost.to_bytes(2, 'big')
            result[base+off+4] = s.level & 255
            result[base+off+5] = s.flag & 255
        allowed.update(base+off for off in EDIT_OFFSETS)
        changes.append(dict(pilot_id=pid, name=pilot.name, before=asdict(pilot.settings), after=asdict(value)))
    if len(result) != len(raw) or any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, result))):
        raise PatchError('Prepared edits changed bytes outside the selected pilot settings.')
    actual = read_pilots(result)
    for pid, value in updates.items():
        if actual[pid].settings != value:
            raise PatchError('Pilot settings failed prepared-output verification.')
    return bytes(result), changes


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
    lock = path.with_name(path.name+'.pilot-settings.lock')
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
    fd, temporary = tempfile.mkstemp(prefix=target.name+'.pilot-', suffix='.tmp', dir=target.parent)
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
        self._temporary = tempfile.TemporaryDirectory(prefix='ogmd-pilot-settings-')
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
            self.pilot = _entry(arc, PILOT_ENTRY)
            read_table(_entry(arc, SPIRIT_ENTRY), 'spirit')
            self.pilots = read_pilots(self.pilot)
            assert_snapshot(self.target, self.original)
        except Exception:
            self.close()
            raise

    def close(self):
        self._temporary.cleanup()

    def defaults(self, pilot_ids=None):
        return {uid: self.pilots[uid].defaults for uid in (self.pilots if pilot_ids is None else pilot_ids)}

    def install(self, updates, progress=lambda text: None):
        replacement, changes = prepare_pilot(self.pilot, updates)
        if not changes:
            raise PatchError('There are no pilot changes to write.')
        with target_lock(self.target):
            assert_snapshot(self.target, self.original)
            token = uuid.uuid4().hex
            plain = self.work/(token+'.psarc')
            verification = repack(self.plain, plain, {PILOT_ENTRY: replacement}, progress=progress)
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
        if (doc.get('format') != 'ogmd-pilot-settings-v1' or Path(doc.get('target', '')).resolve() != self.target
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
        folder = self.target.parent/'_pilot_settings_backups'/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        backup = folder/self.target.name
        atomic_copy(self.source, backup, self.original)
        manifest = folder/'patch.json'
        doc = dict(format='ogmd-pilot-settings-v1', operation=operation, status='prepared',
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
