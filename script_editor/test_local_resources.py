import tempfile
import unittest
from pathlib import Path
from local_resources import PREVIEW_FILES, find_preview_assets, missing_preview_files


class LocalResourcesTest(unittest.TestCase):
    def test_absent_or_empty_resources_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in PREVIEW_FILES:
                (folder / name).touch()
            self.assertEqual(missing_preview_files(folder), list(PREVIEW_FILES))
            self.assertIsNone(find_preview_assets([None, folder / 'absent', folder]))

    def test_first_complete_folder_wins_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            folders = [Path(temp) / name for name in ('incomplete', 'selected', 'bundled')]
            for folder in folders:
                folder.mkdir()
                for name in PREVIEW_FILES:
                    (folder / name).write_bytes(b'fixture')
            (folders[0] / PREVIEW_FILES[0]).unlink()
            self.assertEqual(find_preview_assets(folders), folders[1])
            self.assertEqual((folders[1] / PREVIEW_FILES[0]).read_bytes(), b'fixture')


if __name__ == '__main__':
    unittest.main()
