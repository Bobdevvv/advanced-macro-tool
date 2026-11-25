"""Macro files: format checks, atomic writes, and never losing a macro."""
import json
import os
import unittest
from unittest import mock

from tests import support  # noqa: F401  (isolates AMT_HOME first)
from src.models.macro import Macro, MacroEvent, MacroFormatError
from src.storage.macro_store import MacroExistsError, MacroStore, safe_stem


def _macro(name, n=1):
    return Macro(name, [MacroEvent("key_press", 0.1 * i, key="a") for i in range(n)])


class MacroFileFormat(unittest.TestCase):
    def setUp(self):
        self.dir = support.fresh_dir("fmt")

    def _write(self, content):
        path = os.path.join(self.dir, "x.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_round_trip(self):
        m = Macro("demo", [MacroEvent("mouse_click", 0.5, x=-10, y=20, button="left",
                                      pressed=True)], description="d")
        path = os.path.join(self.dir, "demo.json")
        m.save(path)
        back = Macro.load(path)
        self.assertEqual(back.name, "demo")
        self.assertEqual(back.events[0].x, -10)
        self.assertEqual(back.description, "d")

    def test_rejects_broken_files_with_clear_errors(self):
        for content in ("{not json", [], {"events": "nope"},
                        {"events": [{"type": "key_press"}]}):
            with self.subTest(content=content):
                with self.assertRaises(MacroFormatError):
                    Macro.load(self._write(content))

    def test_missing_name_falls_back_to_file_name(self):
        self.assertEqual(Macro.load(self._write({"events": []})).name, "x")

    def test_events_are_sorted_so_duration_is_right(self):
        path = self._write({"name": "n", "events": [
            {"type": "key_press", "timestamp": 2.0, "key": "a"},
            {"type": "key_press", "timestamp": 1.0, "key": "b"}]})
        self.assertEqual(Macro.load(path).duration(), 2.0)

    def test_failed_write_keeps_the_old_file(self):
        path = os.path.join(self.dir, "keep.json")
        _macro("keep", 3).save(path)
        broken = _macro("keep", 1)
        with mock.patch("json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                broken.save(path)
        self.assertEqual(len(Macro.load(path).events), 3)
        self.assertFalse(os.path.exists(path + ".tmp"))


class StoreNames(unittest.TestCase):
    def setUp(self):
        self.store = MacroStore(support.fresh_dir("store"))

    def test_safe_stem_handles_windows_rules(self):
        self.assertEqual(safe_stem('a/b:c*'), "a_b_c_")
        self.assertEqual(safe_stem("CON"), "_CON")
        self.assertEqual(safe_stem("nul.txt"), "_nul.txt")
        self.assertEqual(safe_stem("name. . "), "name")
        self.assertEqual(safe_stem("   "), "untitled")
        self.assertLessEqual(len(safe_stem("x" * 500)), 100)

    def test_reserved_name_is_really_saved(self):
        f = self.store.save(_macro("CON"))
        self.assertIn(f, self.store.list_files())

    def test_saving_a_taken_name_never_overwrites(self):
        self.store.save(_macro("dup", 5))
        second = _macro("dup", 1)
        f2 = self.store.save(second)
        self.assertEqual(second.name, "dup (2)")
        self.assertEqual(len(self.store.load("dup.json").events), 5)
        self.assertEqual(len(self.store.load(f2).events), 1)

    def test_taken_name_check_ignores_letter_case(self):
        self.store.save(_macro("Report"))
        m = _macro("report")
        self.store.save(m)
        self.assertEqual(m.name, "report (2)")

    def test_overwrite_only_when_asked(self):
        self.store.save(_macro("o", 5))
        self.store.save(_macro("o", 1), overwrite=True)
        self.assertEqual(len(self.store.load("o.json").events), 1)

    def test_rename_case_only_keeps_the_macro(self):
        self.store.save(_macro("test", 2))
        new = self.store.rename("test.json", "Test")
        self.assertEqual(self.store.list_files(), ["Test.json"])
        self.assertEqual(new, "Test.json")
        self.assertEqual(len(self.store.load(new).events), 2)

    def test_rename_onto_another_macro_is_refused(self):
        self.store.save(_macro("keep", 3))
        self.store.save(_macro("other", 1))
        with self.assertRaises(MacroExistsError):
            self.store.rename("other.json", "keep")
        self.assertEqual(len(self.store.load("keep.json").events), 3)
        self.assertIn("other.json", self.store.list_files())

    def test_list_is_sorted_case_insensitively(self):
        for n in ("beta", "Alpha", "gamma"):
            self.store.save(_macro(n))
        self.assertEqual(self.store.list_files(), ["Alpha.json", "beta.json", "gamma.json"])

    def test_broken_file_reports_error_metadata(self):
        with open(self.store.path_for("bad.json"), "w") as f:
            f.write("{")
        meta = self.store.get_metadata("bad.json")
        self.assertTrue(meta["error"])
        self.assertEqual(meta["name"], "bad")


if __name__ == "__main__":
    unittest.main()
