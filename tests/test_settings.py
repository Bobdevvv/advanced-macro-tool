"""Default hotkeys and moving old settings to them."""
import json
import unittest

from tests import support
from src import app_paths
from src.core.hotkey_manager import same_hotkey
from src.defaults import (
    DEFAULT_HOTKEYS, PREVIOUS_DEFAULTS, SETTINGS_VERSION, migrate_hotkeys,
)

V1 = dict(PREVIOUS_DEFAULTS[1])          # F9 / F10 / F11 / F8
V2 = dict(PREVIOUS_DEFAULTS[2])          # F9 / F10 / F8 / F7
NEW = dict(DEFAULT_HOTKEYS)


class Defaults(unittest.TestCase):
    def test_defaults_follow_the_sidebar_on_f7_to_f10(self):
        self.assertEqual(
            [NEW["hotkey_record"], NEW["hotkey_play"], NEW["hotkey_test"],
             NEW["hotkey_autoclicker"]],
            ["<f7>", "<f8>", "<f9>", "<f10>"])

    def test_defaults_are_distinct(self):
        vals = list(NEW.values())
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                self.assertFalse(same_hotkey(a, b))


class Migration(unittest.TestCase):
    def hotkeys(self, cfg):
        return {k: cfg[k] for k in DEFAULT_HOTKEYS}

    def test_from_version_1(self):
        cfg = dict(V1)                                   # no version: v1
        self.assertTrue(migrate_hotkeys(cfg))
        self.assertEqual(self.hotkeys(cfg), NEW)
        self.assertEqual(cfg["settings_version"], SETTINGS_VERSION)

    def test_from_version_2_rotation(self):
        """Record F9->F7 while Test play F7->F9: must move together."""
        cfg = {**V2, "settings_version": 2}
        self.assertTrue(migrate_hotkeys(cfg))
        self.assertEqual(self.hotkeys(cfg), NEW)

    def test_keys_the_user_chose_are_kept(self):
        cfg = {**V2, "settings_version": 2, "hotkey_autoclicker": "<ctrl>+<f12>"}
        migrate_hotkeys(cfg)
        self.assertEqual(cfg["hotkey_autoclicker"], "<ctrl>+<f12>")
        self.assertEqual(cfg["hotkey_record"], "<f7>")
        self.assertEqual(cfg["hotkey_test"], "<f9>")

    def test_nothing_moves_if_it_would_clash_with_a_users_key(self):
        # Version 2, but the user moved Record to F8 and Auto click to F12
        # themselves.  Play (still on its old default F10) would move to
        # F8, which the user's Record already uses: so nothing moves.
        cfg = {"settings_version": 2, "hotkey_record": "<f8>", "hotkey_play": "<f10>",
               "hotkey_autoclicker": "<f12>", "hotkey_test": "<f7>"}
        before = self.hotkeys(cfg)
        self.assertFalse(migrate_hotkeys(cfg))
        self.assertEqual(self.hotkeys(cfg), before)
        self.assertEqual(cfg["settings_version"], SETTINGS_VERSION)   # not retried

    def test_runs_only_once(self):
        cfg = {**V1, "settings_version": SETTINGS_VERSION}
        self.assertFalse(migrate_hotkeys(cfg))
        self.assertEqual(cfg["hotkey_autoclicker"], "<f11>")   # chosen after migrating

    def test_damaged_version_counts_as_old(self):
        cfg = {**V1, "settings_version": "x"}
        self.assertTrue(migrate_hotkeys(cfg))
        self.assertEqual(self.hotkeys(cfg), NEW)

    def test_app_migrates_and_saves_an_old_settings_file(self):
        support.qapp()
        support.stub_global_input()
        from src.ui.main_window import MainWindow
        with open(app_paths.settings_file(), "w", encoding="utf-8") as f:
            json.dump({**V2, "settings_version": 2, "theme": "Terminal"}, f)
        w = MainWindow()
        try:
            self.assertEqual(self.hotkeys(w._cfg), NEW)
            with open(app_paths.settings_file(), encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(self.hotkeys(saved), NEW)
            self.assertEqual(saved["settings_version"], SETTINGS_VERSION)
            self.assertEqual(w.tab_cfg.hk_test_edit.text(), "<f9>")
            chips = [w._hk_chips[k].findChildren(type(w._status._label))[0].text()
                     for k in ("hotkey_record", "hotkey_play", "hotkey_test",
                               "hotkey_autoclicker")]
            self.assertEqual(chips, ["F7", "F8", "F9", "F10"])   # sidebar order
        finally:
            w._hotkeys.stop()
            w.deleteLater()
            support.flush_deletes()


if __name__ == "__main__":
    unittest.main()
