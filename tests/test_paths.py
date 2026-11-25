"""The data folder: its name, and the one-time move from Documents\\MacroTool."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests import support  # noqa: F401  (sets AMT_HOME for the other tests)

from src import app_paths, brand


class TestDataFolder(unittest.TestCase):
    def setUp(self):
        self.docs = tempfile.mkdtemp(prefix="amt-docs-")
        self.addCleanup(shutil.rmtree, self.docs, True)
        env = {k: v for k, v in os.environ.items() if k != "AMT_HOME"}
        p1 = mock.patch.dict(os.environ, env, clear=True)
        p2 = mock.patch.object(app_paths, "documents_dir", return_value=self.docs)
        for p in (p1, p2):
            p.start()
            self.addCleanup(p.stop)
        self.old = os.path.join(self.docs, "MacroTool")
        self.new = os.path.join(self.docs, "AdvancedMacroTool")

    def _old_install(self, settings: dict | None = None) -> None:
        os.makedirs(os.path.join(self.old, "macros"))
        with open(os.path.join(self.old, "macros", "Hello.json"), "w") as f:
            f.write("{}")
        if settings is not None:
            with open(os.path.join(self.old, "settings.json"), "w") as f:
                json.dump(settings, f)

    def test_folder_is_named_after_the_app(self):
        self.assertEqual(brand.DIR_NAME, "AdvancedMacroTool")
        self.assertEqual(app_paths.home(), self.new)

    def test_old_folder_is_moved_with_everything_in_it(self):
        self._old_install({"theme": "Terminal"})
        self.assertEqual(app_paths.migrate_legacy_home(), self.new)
        self.assertFalse(os.path.exists(self.old))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "macros", "Hello.json")))
        self.assertEqual(app_paths.home(), self.new)
        with open(app_paths.settings_file()) as f:
            self.assertEqual(json.load(f), {"theme": "Terminal"})

    def test_custom_macro_folder_inside_the_old_one_follows(self):
        custom = os.path.join(self.old, "work")
        self._old_install({"macro_dir": custom})
        app_paths.migrate_legacy_home()
        with open(os.path.join(self.new, "settings.json")) as f:
            self.assertEqual(json.load(f)["macro_dir"], os.path.join(self.new, "work"))

    def test_custom_macro_folder_elsewhere_is_left_alone(self):
        elsewhere = os.path.join(self.docs, "MacroToolbox")    # shares the prefix
        self._old_install({"macro_dir": elsewhere})
        app_paths.migrate_legacy_home()
        with open(os.path.join(self.new, "settings.json")) as f:
            self.assertEqual(json.load(f)["macro_dir"], elsewhere)

    def test_never_merges_into_an_existing_new_folder(self):
        self._old_install()
        os.makedirs(self.new)
        self.assertIsNone(app_paths.migrate_legacy_home())
        self.assertTrue(os.path.isdir(self.old))              # untouched

    def test_failed_move_keeps_using_the_old_folder(self):
        self._old_install()
        with mock.patch.object(app_paths.os, "rename", side_effect=PermissionError):
            self.assertIsNone(app_paths.migrate_legacy_home())
        self.assertEqual(app_paths.home(), self.old)
        self.assertFalse(os.path.exists(self.new))            # no empty library
        self.assertEqual(app_paths.migrate_legacy_home(), self.new)   # next start

    def test_test_folder_is_never_migrated(self):
        self._old_install()
        with mock.patch.dict(os.environ, {"AMT_HOME": os.path.join(self.docs, "t")}):
            self.assertIsNone(app_paths.migrate_legacy_home())
        self.assertTrue(os.path.isdir(self.old))


if __name__ == "__main__":
    unittest.main()
