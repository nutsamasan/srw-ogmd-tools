"""Exercise the actual Tk form against disposable synthetic saves."""
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch
from test_ogmd_save import _make_slot
from ogmd_save import snapshot_slot, load_pilots
from save_editor import SaveEditor


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.slot = _make_slot(Path(self.temp.name))
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.ui = SaveEditor(self.root)
        self.ui.folder_var.set(str(self.slot))
        self.ui.load_selected()

    def close_root(self):
        self.root.update()
        self.root.destroy()

    def test_search_filters_each_tab_and_preserves_staged_changes(self):
        self.ui.pending_pp[0x35] = 9999
        self.ui.search_var.set("Michiru")
        self.root.update()
        self.assertEqual(self.ui.pilot_tree.get_children(), ("53",))
        self.assertEqual(str(self.ui.pilot_tree.item("53", "values")[-1]), "9999 *")
        self.ui.search_var.set("no match")
        self.root.update()
        self.assertEqual(self.ui.pilot_tree.get_children(), ())
        self.ui.clear_search()
        self.root.update()
        self.assertEqual(self.ui.pending_pp[0x35], 9999)
        for tab, query, tree in [(1, "Booster", self.ui.part_tree), (2, "Melee", self.ui.ability_tree), (3, "Blade Railgun L", self.ui.weapon_tree)]:
            self.ui.notebook.select(tab)
            self.ui.search_var.set(query)
            self.root.update()
            self.assertTrue(tree.get_children())
        self.assertTrue(self.ui._validate_ability_text("32767"))

    def test_gui_write_updates_snapshot_and_rejects_stale_save(self):
        self.ui.pending_pp[0x35] = 9000
        with patch("save_editor.messagebox.askyesno", return_value=True), patch("save_editor.messagebox.showinfo"):
            self.ui.save_pilot_changes()
        self.assertEqual(load_pilots(self.slot)[0].pp, 9000)
        self.assertEqual(self.ui.loaded_snapshot, snapshot_slot(self.slot))
        (self.slot / "SYSFLAG.SAV").write_bytes(b"changed externally")
        before = snapshot_slot(self.slot)
        self.ui.funds_var.set("999999")
        with patch("save_editor.messagebox.askyesno", return_value=True), patch("save_editor.messagebox.showerror") as error:
            self.ui.save_funds()
        self.assertTrue(error.called)
        self.assertEqual(snapshot_slot(self.slot), before)


if __name__ == "__main__":
    unittest.main()
