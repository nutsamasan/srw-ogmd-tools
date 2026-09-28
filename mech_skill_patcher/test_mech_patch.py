"""Skill boundaries, restoration, transaction failure and real GUI staging."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import zlib

import mech_patch as core
from app import App, LABELS
from fixed_data import parse_fixed, rebuild_fixed
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parent.parent
FIXED = ROOT/'work/extracted/ps3_logic/Dat/FixedData'
UNIT = (FIXED/'UnitData.dat').read_bytes()
ABILITY = (FIXED/'AbilityData.dat').read_bytes()


def make_archive(path, unit=UNIT):
    names = [core.UNIT_ENTRY, core.ABILITY_ENTRY, '/unrelated.txt']
    payloads = ['\n'.join(names).encode(), unit, ABILITY, b'English text and other content stay intact.']
    names = ['__manifest__']+names
    blocks = [zlib.compress(payload, 9) for payload in payloads]
    blocks[1] += bytes(4096)  # Valid trailing zlib padding for exact-size rebuilding.
    offset = 32 + len(blocks)*32
    header = b'PSAR'+struct.pack('>HH4s5I', 1, 4, b'zlib', offset, 30, len(blocks), 65536, 0)
    table = []
    for index, (name, payload, block) in enumerate(zip(names, payloads, blocks)):
        table.append(hashlib.md5(name.encode()).digest()+struct.pack('>I', index)+len(payload).to_bytes(5, 'big')+offset.to_bytes(5, 'big'))
        offset += len(block)
    path.write_bytes(header+b''.join(table)+b''.join(len(block).to_bytes(2, 'big') for block in blocks)+b''.join(blocks))
    return path


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.target = make_archive(self.folder/'Logic.psarc')

    def session(self):
        result = core.Session(self.target)
        self.addCleanup(result.close)
        return result

    def test_original_defaults_full_corpus_and_late_record(self):
        session = self.session()
        self.assertEqual(len(session.mechs), 216)
        self.assertTrue(all(mech.skills == mech.defaults for mech in session.mechs.values()))
        last = max(session.mechs)
        updated, changes = core.prepare_unit(UNIT, {1: (12, 17, 20, 21, 24), last: (14, 17, 20, 21, 24)})
        fixed = parse_fixed(UNIT)
        allowed = {fixed.chunks[b'DATA'][0]+12+fixed.logical_indices[uid]*216+off for uid in (1, last) for off in range(0x46, 0x4B)}
        changed = {i for i, (a, b) in enumerate(zip(UNIT, updated)) if a != b}
        self.assertTrue(changed)
        self.assertLessEqual(changed, allowed)
        self.assertEqual(len(changes), 2)

    def test_invalid_ids_duplicates_types_and_empty_slots(self):
        for updates in ({0: (0,)*5}, {9999: (0,)*5}, {True: (0,)*5}, {1: (12,)*5},
                        {1: (48, 0, 0, 0, 0)}, {1: (True, 0, 0, 0, 0)}, {1: (12,)}, {1: (-1, 0, 0, 0, 0)}):
            with self.subTest(updates=updates), self.assertRaises(core.PatchError):
                core.prepare_unit(UNIT, updates)
        updated, _ = core.prepare_unit(UNIT, {1: (0,)*5})
        self.assertEqual(core.read_mechs(updated)[1].skills, (0,)*5)

    def test_wrong_game_stats_and_truncated_table_rejected(self):
        fixed = parse_fixed(UNIT)
        changed = bytearray(UNIT)
        changed[fixed.chunks[b'DATA'][0]+12+216+20] ^= 1
        for raw in (changed, UNIT[:-5], b'not a unit file'):
            with self.assertRaises(core.PatchError):
                core.read_mechs(raw)

    def test_noop_creates_no_backup(self):
        session = self.session()
        before = core.snapshot(self.target)
        with self.assertRaisesRegex(core.PatchError, 'no skill changes'):
            session.install(session.defaults())
        self.assertEqual(core.snapshot(self.target), before)
        self.assertFalse((self.folder/'_mech_skill_backups').exists())

    def test_apply_then_original_defaults_preserve_all_other_entries_and_timestamp(self):
        session = self.session()
        before = core.snapshot(self.target)
        result = session.install({1: (12, 17, 20, 21, 24), 2: (14, 17, 20, 21, 24)})
        self.assertEqual(core.snapshot(Path(result['backup'])), before)
        changed = self.session()
        self.assertEqual(changed.mechs[1].skills, (12, 17, 20, 21, 24))
        self.assertEqual(changed.original['mtime_ns'], before['mtime_ns'])
        self.assertEqual(changed.original['size'], before['size'])
        changed.install(changed.defaults())
        restored = self.session()
        self.assertEqual(restored.unit, UNIT)
        arc = Psarc(restored.plain)
        self.assertEqual(core._entry(arc, '/unrelated.txt'), b'English text and other content stay intact.')
        self.assertEqual(core._entry(arc, core.ABILITY_ENTRY), ABILITY)

    def test_exact_backup_restore_is_byte_identical_and_itself_backed_up(self):
        session = self.session()
        before = core.snapshot(self.target)
        result = session.install({1: (12, 17, 20, 21, 24)})
        changed = self.session()
        patched = changed.original
        restored = changed.restore_backup(result['manifest'])
        self.assertEqual(core.snapshot(self.target), before)
        self.assertEqual(core.snapshot(Path(restored['backup'])), patched)

    def test_defaults_preserve_translations_installed_after_skill_patch(self):
        patched, _ = core.prepare_unit(UNIT, {1: (12, 17, 20, 21, 24)})
        fixed = parse_fixed(patched)
        translated = rebuild_fixed(fixed, {}, [(fixed.logical_indices[1], 2, 2, 'New English R-1')])
        self.target = make_archive(self.target, translated)
        session = self.session()
        session.install(session.defaults([1]))
        after = self.session()
        self.assertEqual(after.mechs[1].installed_name, 'New English R-1')
        self.assertEqual(after.mechs[1].skills, after.mechs[1].defaults)
        # Except for the five skill bytes, the newly translated UnitData is exact.
        expect, _ = core.prepare_unit(translated, session.defaults([1]))
        self.assertEqual(after.unit, expect)

    def test_stale_read_rejected_before_backup(self):
        session = self.session()
        with self.target.open('ab') as out:
            out.write(b'external update')
        before = self.target.read_bytes()
        with self.assertRaisesRegex(core.PatchError, 'changed after'):
            session.install({1: (12, 17, 20, 21, 24)})
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse((self.folder/'_mech_skill_backups').exists())

    def test_lock_blocks_another_writer(self):
        session = self.session()
        with core.target_lock(self.target), self.assertRaisesRegex(core.PatchError, 'Another patch'):
            session.install({1: (12, 17, 20, 21, 24)})
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_post_replace_failure_rolls_back_verified_original(self):
        session = self.session()
        before = core.snapshot(self.target)
        original_copy = core.atomic_copy
        failed = False
        def fail_once(source, target, expected):
            nonlocal failed
            original_copy(source, target, expected)
            if target == self.target and not failed:
                failed = True
                raise OSError('simulated readback failure')
        with patch('mech_patch.atomic_copy', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated'):
                session.install({1: (12, 17, 20, 21, 24)})
        self.assertEqual(core.snapshot(self.target), before)
        manifest = next((self.folder/'_mech_skill_backups').glob('*/patch.json'))
        self.assertEqual(json.loads(manifest.read_text(encoding='utf8'))['status'], 'rolled-back')

    def test_external_update_during_backup_is_preserved(self):
        session = self.session()
        original_copy = core.atomic_copy
        def modify_after_backup(source, target, expected):
            original_copy(source, target, expected)
            if '_mech_skill_backups' in target.parts:
                with self.target.open('ab') as out:
                    out.write(b'new external data')
        with patch('mech_patch.atomic_copy', side_effect=modify_after_backup):
            with self.assertRaisesRegex(core.PatchError, 'changed after'):
                session.install({1: (12, 17, 20, 21, 24)})
        self.assertTrue(self.target.read_bytes().endswith(b'new external data'))

    def test_backup_corruption_is_rejected(self):
        result = self.session().install({1: (12, 17, 20, 21, 24)})
        with Path(result['backup']).open('ab') as out:
            out.write(b'corruption')
        session = self.session()
        before = session.original
        with self.assertRaisesRegex(core.PatchError, 'checksum'):
            session.restore_backup(result['manifest'])
        self.assertEqual(core.snapshot(self.target), before)

    def test_old_or_wrong_target_backup_is_rejected(self):
        first = self.session().install({1: (12, 17, 20, 21, 24)})
        second = self.session().install({2: (14, 17, 20, 21, 24)})
        session = self.session()
        with self.assertRaisesRegex(core.PatchError, 'changed since'):
            session.restore_backup(first['manifest'])
        manifest = Path(second['manifest'])
        doc = json.loads(manifest.read_text(encoding='utf8'))
        doc['target'] = str(self.folder/'Other.psarc')
        manifest.write_text(json.dumps(doc), encoding='utf8')
        with self.assertRaisesRegex(core.PatchError, 'different archive'):
            session.restore_backup(manifest)

    def test_selected_defaults_leave_other_modifications(self):
        self.session().install({1: (12, 17, 20, 21, 24), 2: (14, 17, 20, 21, 24)})
        session = self.session()
        session.install(session.defaults([1]))
        result = self.session()
        self.assertEqual(result.mechs[1].skills, result.mechs[1].defaults)
        self.assertEqual(result.mechs[2].skills, (14, 17, 20, 21, 24))

    def test_folder_resolution_and_unexpected_target(self):
        self.assertEqual(core.resolve_target(self.folder), self.target)
        with self.assertRaises(core.PatchError):
            core.resolve_target(self.folder/'game.iso')

    def test_gui_filter_stage_restore_and_discard(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            app.loaded(self.session())
            app.tree.selection_set('1')
            app.select()
            app.skill_vars[0].set(LABELS[12])
            app.edit(0)
            self.assertEqual(app.pending[1], (12, 0, 0, 0, 0))
            app.search_var.set('HP Regen')
            root.update()
            self.assertTrue(app.tree.exists('1'))
            self.assertEqual(app.pending[1][0], 12)
            app.defaults_selected()
            self.assertFalse(app.pending)
            app.search_var.set('R-1')
            root.update()
            app.tree.selection_set('1')
            app.select()
            app.skill_vars[1].set(LABELS[17])
            app.edit(1)
            root.update()
            self.assertEqual(app.description.get(), core.SKILLS[17]['description'])
            app.discard()
            self.assertFalse(app.pending)
            self.assertEqual(core.snapshot(self.target), app.session.original)
            other = self.folder/'other'
            other.mkdir()
            second = make_archive(other/'Logic.psarc')
            app.target_var.set(str(second))
            with self.assertRaisesRegex(core.PatchError, 'differs from the loaded'):
                app.check_loaded_target()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
