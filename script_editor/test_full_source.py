"""Source-selection regression checks for the complete-game patcher."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from full_patch import source_folder
from full_dialog import FullPatchDialog


class FullSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_complete_disc_and_game_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);game=root/'PS3_GAME';(game/'USRDIR').mkdir(parents=True)
            (game/'PARAM.SFO').write_bytes(b'BLJS10335')
            (game/'USRDIR/EBOOT.BIN').write_bytes(b'boot executable')
            self.assertEqual(source_folder(root),game.resolve())
            self.assertEqual(source_folder(game),game.resolve())

    def test_installed_archives_and_incomplete_game_explain_correct_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);game=root/'dev_hdd0/game/BLJS10335';archive=game/'USRDIR/PSARC';archive.mkdir(parents=True)
            (game/'PARAM.SFO').write_bytes(b'BLJS10335')
            with self.assertRaisesRegex(ValueError,'PSARC archive folder.*original Japanese ISO.*Patch edits'):
                source_folder(archive)
            with self.assertRaisesRegex(ValueError,'no USRDIR/EBOOT.BIN.*Patch edits'):
                source_folder(game)

    def test_invalid_source_stops_before_settings_or_build_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);home=root/'patcher';home.mkdir();settings=home/'settings.json';settings.write_text('{"source":"retained"}')
            before=settings.read_bytes();archive=root/'game/USRDIR/PSARC';archive.mkdir(parents=True)
            dialog=FullPatchDialog(home);dialog.mode.setCurrentIndex(1);dialog.source.setText(str(archive));dialog.output.setText(str(root/'output'))
            dialog.setup.setChecked(False)
            with patch.object(dialog,'failed') as failed,patch.object(dialog,'job_start') as job:
                dialog.build_patch();failed.assert_called_once();job.assert_not_called()
                self.assertIn('PSARC archive folder',failed.call_args.args[0])
            self.assertEqual(settings.read_bytes(),before);self.assertFalse((home/'builds').exists())
            dialog.mode.setCurrentIndex(0)
            with patch.object(dialog,'failed') as failed,patch.object(dialog,'job_start') as job:
                dialog.build_patch();failed.assert_called_once();job.assert_not_called()
                self.assertIn('existing decrypted OGMD ISO',failed.call_args.args[0])
            dialog.close()


if __name__=='__main__':unittest.main()
