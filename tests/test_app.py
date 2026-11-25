"""The whole window: every page, workflow and state transition.

Real system-wide input hooks are stubbed out (see support.stub_global_input);
recording and hotkeys are driven through the same callbacks pynput would
call.  All files go to a temporary AMT_HOME.
"""
import ctypes
import json
import os
import subprocess
import sys
import textwrap
import unittest
from unittest import mock

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QKeyEvent
from PyQt6.QtWidgets import QMessageBox

from tests import support
from src import app_paths
from src.defaults import DEFAULT_HOTKEYS
from src.models.macro import Macro, MacroEvent as E
from src.storage.macro_store import MacroStore
from src.ui import theme
from src.ui.widgets import InfoTip, _InfoPopup

support.qapp()
support.stub_global_input()
from src.ui.main_window import MainWindow, _clean_cfg  # noqa: E402

IS_WINDOWS = sys.platform == "win32"


def _seed(n=3):
    store = MacroStore(app_paths.default_macro_dir())
    for f in store.list_files():
        store.delete(f)
    for i in range(n):
        store.save(Macro(f"demo {i}", [
            E("mouse_move", 0.0, x=0, y=0),
            E("mouse_click", 0.2, x=10, y=10, button="left", pressed=True),
            E("mouse_click", 0.3, x=10, y=10, button="left", pressed=False),
            E("key_press", 0.4, key="a"), E("key_release", 0.5, key="a")]))
    return store


class AppTest(unittest.TestCase):
    def setUp(self):
        with open(app_paths.settings_file(), "w") as f:
            json.dump({}, f)
        self.store = _seed()
        self.w = MainWindow()
        self.w._player._mouse = support.FakeMouse()
        self.w._player._keyboard = support.FakeKeyboard()
        self.w._clicker._mouse = support.FakeMouse()
        self.w.resize(1180, 760)
        self.w.show()
        support.pump()
        # Never block a test on a dialog.
        for name in ("information", "warning", "critical"):
            p = mock.patch.object(QMessageBox, name, return_value=QMessageBox.StandardButton.Ok)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.w._player.stop()
        self.w._clicker.stop()
        self.w.close()
        # Destroy it: windows left alive pile up, and each new one re-styles
        # all of them, which made the suite slow down quadratically.
        self.w.deleteLater()
        support.pump()
        support.flush_deletes()

    def lib(self):
        return self.w.tab_lib_play

    def select(self, row):
        t = self.lib()
        t.tree.setCurrentItem(t.tree.topLevelItem(row))
        support.pump()


class Shell(AppTest):
    def test_window_title(self):
        self.assertEqual(self.w.windowTitle(), "AMT — Advanced Macro Tool")
        if IS_WINDOWS:
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(int(self.w.winId()), buf, 256)
            self.assertEqual(buf.value, "AMT — Advanced Macro Tool")   # no " - AMT"

    def test_nav_labels_keep_their_ampersand(self):
        self.assertEqual(self.w.nav_buttons[1].text(), "Player && Library")

    def test_every_theme_applies(self):
        for name in theme.THEME_NAMES:
            self.w._apply_theme(name)
        support.pump()
        self.assertEqual(theme.current(), theme.THEME_NAMES[-1])

    def test_compact_sidebar(self):
        self.w.resize(800, 600)
        support.pump()
        self.assertTrue(self.w._compact)
        self.assertEqual(self.w.now_loaded.btn.text(), "")
        self.w.resize(1200, 800)
        support.pump()
        self.assertFalse(self.w._compact)

    def test_damaged_settings_never_crash(self):
        cfg = _clean_cfg({"theme": 5, "hotkey_record": None, "macro_dir": ["x"],
                          "window_geometry": "zz"})
        self.assertEqual(cfg["theme"], theme.DEFAULT_THEME)
        self.assertEqual(cfg["hotkey_record"], DEFAULT_HOTKEYS["hotkey_record"])
        self.assertEqual(cfg["macro_dir"], "")


class Recording(AppTest):
    def _record(self, events, via_button):
        rec = self.w._recorder
        self.w.tab_rec.trigger_start()
        for e in events:
            rec._add(e)
        if via_button:
            self.w.tab_rec._toggle()
        else:
            self.w.tab_rec.trigger_stop()
        support.pump()

    def test_button_stop_drops_its_own_click(self):
        self._record([E("key_press", 0.1, key="a"), E("key_release", 0.2, key="a"),
                      E("mouse_click", 0.3, x=5, y=5, button="left", pressed=True),
                      E("mouse_click", 0.4, x=5, y=5, button="left", pressed=False)],
                     via_button=True)
        m = self.store.load("Untitled-1.json")
        self.assertEqual([e.type for e in m.events], ["key_press", "key_release"])

    def test_taken_name_gets_a_free_one(self):
        self.w.tab_rec.name_input.setText("demo 0")
        self._record([E("key_press", 0.1, key="a")], via_button=False)
        self.assertIn("demo 0 (2).json", self.store.list_files())
        self.assertEqual(len(self.store.load("demo 0.json").events), 5)

    def test_closing_while_recording_saves_it(self):
        self.w.tab_rec.trigger_start()
        self.w._recorder._add(E("key_press", 0.1, key="z"))
        self.w.close()
        support.pump()
        self.assertIn("Untitled-1.json", self.store.list_files())

    def test_new_recording_is_loaded_into_the_player(self):
        self._record([E("key_press", 0.1, key="a")], via_button=False)
        self.assertEqual(self.w.tab_lib_play.loaded_file(), "Untitled-1.json")
        self.assertEqual(self.w.tab_lib_play._selected_file(), "Untitled-1.json")
        self.assertEqual(self.w.now_loaded._name.text(), "Untitled-1")

    def test_new_recording_is_not_loaded_when_switched_off(self):
        self.w._cfg["load_after_record"] = False
        self._record([E("key_press", 0.1, key="a")], via_button=False)
        self.assertIsNone(self.w.tab_lib_play.loaded_file())

    def test_mouse_movement_switch_reaches_recorder(self):
        self.w.tab_rec.chk_mouse_move.setChecked(False)
        self.w.tab_rec.trigger_start()
        self.assertFalse(self.w._recorder.record_moves)
        self.w.tab_rec.trigger_stop()

    def test_hotkeys_are_kept_out_of_recordings(self):
        self.assertEqual(self.w._hotkey_chars(),
                         {"Key.f7", "Key.f8", "Key.f9", "Key.f10"})


class PlayerAndLibrary(AppTest):
    def test_selecting_loads_and_sidebar_follows(self):
        self.select(0)
        self.assertTrue(self.lib().btn_play.isEnabled())
        self.assertEqual(self.w.now_loaded._name.text(), "demo 0")
        self.assertEqual(self.lib().loaded_file(), "demo 0.json")

    def test_browsing_during_playback_keeps_controls_truthful(self):
        self.select(0)
        self.w._on_player_started()
        self.select(1)
        self.assertFalse(self.lib().btn_play.isEnabled())
        self.assertTrue(self.lib().btn_stop.isEnabled())
        self.assertIn("Playing", self.lib().lbl_state.text())
        self.w._on_player_finished()
        self.assertTrue(self.lib().btn_play.isEnabled())

    def test_cannot_delete_the_playing_macro(self):
        self.select(0)
        self.w._on_player_started()
        self.lib()._on_delete()
        self.assertIn("demo 0.json", self.store.list_files())
        self.w._on_player_finished()

    def test_rename_keeps_selection_and_loaded_file(self):
        self.select(0)
        self.w._rename_macro("demo 0.json", "Demo 0")          # case-only
        self.assertIn("Demo 0.json", self.store.list_files())
        self.assertEqual(self.lib().loaded_file(), "Demo 0.json")
        self.assertEqual(self.w.now_loaded._name.text(), "Demo 0")

    def test_rename_onto_taken_name_is_refused(self):
        self.assertIsNone(self.w._rename_macro("demo 0.json", "demo 1"))
        self.assertEqual(len(self.store.list_files()), 3)

    def test_refresh_does_not_reload_the_player(self):
        self.select(0)
        loaded = self.w._loaded_macro
        self.w._refresh_library()
        self.assertIs(self.w._loaded_macro, loaded)

    def test_broken_file_is_listed_and_marked(self):
        with open(self.store.path_for("broken.json"), "w") as f:
            f.write("{")
        self.w._refresh_library()
        texts = [self.lib().tree.topLevelItem(i).text(0)
                 for i in range(self.lib().tree.topLevelItemCount())]
        self.assertTrue(any("broken" in t and "\u26a0" in t for t in texts))

    def _activate(self):
        from PyQt6.QtTest import QTest
        self.w._go_to(1)
        self.w.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(self.w, 3000))

    def _confirm(self, answer):
        """Replace the delete question with a fixed answer (counts calls)."""
        from src.ui.library_player_tab import LibraryPlayerTab
        return mock.patch.object(LibraryPlayerTab, "confirm_delete", return_value=answer)

    def test_delete_and_backspace_delete_from_the_list(self):
        from PyQt6.QtTest import QTest
        self._activate()
        tree = self.lib().tree
        self.select(0)
        tree.setFocus()
        with self._confirm(True) as ask:
            QTest.keyClick(tree, Qt.Key.Key_Delete)
            self.assertEqual(ask.call_count, 1)                 # still asks first
            self.assertEqual(self.store.list_files(), ["demo 1.json", "demo 2.json"])
            # The next macro is highlighted (not loaded), so Delete continues.
            self.assertEqual(self.lib()._selected_file(), "demo 1.json")
            self.assertIsNone(self.lib().loaded_file())
            QTest.keyClick(tree, Qt.Key.Key_Backspace)
            self.assertEqual(self.store.list_files(), ["demo 2.json"])

    def test_answering_no_keeps_the_macro(self):
        from PyQt6.QtTest import QTest
        self._activate()
        self.select(0)
        self.lib().tree.setFocus()
        with self._confirm(False):
            QTest.keyClick(self.lib().tree, Qt.Key.Key_Delete)
        self.assertEqual(len(self.store.list_files()), 3)

    def test_backspace_in_the_filter_box_never_deletes(self):
        from PyQt6.QtTest import QTest
        self._activate()
        self.select(0)
        search = self.lib().search
        search.setFocus()
        QTest.keyClicks(search, "dem")
        with self._confirm(True) as ask:
            QTest.keyClick(search, Qt.Key.Key_Backspace)
            QTest.keyClick(search, Qt.Key.Key_Delete)
        self.assertEqual(ask.call_count, 0)
        self.assertEqual(search.text(), "de")
        self.assertEqual(len(self.store.list_files()), 3)

    def _answer_real_dialog(self, key):
        """Open the real delete question and press ``key`` in it."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        seen = {}

        def press():
            box = QApplication.activeModalWidget()
            seen["box"] = box
            if box is not None:
                QTest.keyClick(box, key)
        QTimer.singleShot(150, press)
        result = self.lib().confirm_delete("demo 0")
        self.assertIsNotNone(seen.get("box"), "the dialog did not open")
        return result

    def test_enter_confirms_the_delete_question(self):
        """Owner request: Enter answers Yes, so deleting is quick."""
        self._activate()
        self.assertTrue(self._answer_real_dialog(Qt.Key.Key_Return))

    def test_escape_cancels_the_delete_question(self):
        self._activate()
        self.assertFalse(self._answer_real_dialog(Qt.Key.Key_Escape))

    def write_macro_file(self, name, content):
        path = os.path.join(support.fresh_dir("import"), name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_load_button_is_replaced_by_import(self):
        self.assertFalse(hasattr(self.lib(), "btn_load"))
        self.assertTrue(self.lib().btn_import.isEnabled())

    def test_import_adds_macros_without_replacing_any(self):
        good = self.write_macro_file("demo 0.json", {      # name already taken
            "name": "demo 0", "events": [{"type": "key_press", "timestamp": 0.1, "key": "x"}]})
        bad = self.write_macro_file("notes.json", "{not a macro")
        imported = self.w._import_macros([good, bad])
        self.assertEqual(imported, ["demo 0 (2).json"])
        self.assertEqual(len(self.store.load("demo 0.json").events), 5)   # untouched
        self.assertEqual(self.lib().loaded_file(), "demo 0 (2).json")     # ready to play

    def test_import_button_and_dropping_files(self):
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDropEvent
        path = self.write_macro_file("dropped.json", {"name": "dropped", "events": []})
        with mock.patch("src.ui.library_player_tab.QFileDialog.getOpenFileNames",
                        return_value=([path], "")):
            self.lib().btn_import.click()
        self.assertIn("dropped.json", self.store.list_files())
        path2 = self.write_macro_file("dropped2.json", {"name": "dropped2", "events": []})
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path2)])
        # A real drag from Explorer: enter, move, drop (Qt ignores a drop that
        # was not preceded by an accepted drag-enter).
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent
        vp, app = self.lib().tree.viewport(), support.qapp()
        args = (Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier)
        self.assertTrue(app.sendEvent(vp, QDragEnterEvent(QPoint(20, 20), *args)))
        app.sendEvent(vp, QDragMoveEvent(QPoint(20, 20), *args))
        app.sendEvent(vp, QDropEvent(QPointF(20, 20), *args))
        self.assertIn("dropped2.json", self.store.list_files())

    def test_clicking_the_selected_macro_again_reloads_it_after_unload(self):
        from PyQt6.QtTest import QTest
        self.select(0)
        self.lib()._on_unload()
        self.assertIsNone(self.lib().loaded_file())
        item = self.lib().tree.topLevelItem(0)
        rect = self.lib().tree.visualItemRect(item)
        QTest.mouseClick(self.lib().tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=rect.center())
        self.assertEqual(self.lib().loaded_file(), "demo 0.json")

    def test_humanise_fields_editable_and_noise_default_zero(self):
        t = self.lib()
        self.assertEqual(t.mouse_noise(), 0)
        self.assertTrue(all(x.isEnabled() for x in (t.spin_jitter, t.spin_curve, t.spin_noise)))

    def test_play_runs_and_finishes(self):
        self.select(0)
        self.w._on_play()
        self.w._player._thread.join(3)
        support.pump(10)
        self.assertFalse(self.w._player.is_playing())
        self.assertTrue(self.lib().btn_play.isEnabled())
        self.assertIn(("move", (10, 10)), self.w._player._mouse.log)


class ComposerPage(AppTest):
    """The timeline editor, driven like a user would (real mouse events on
    the timeline where it matters)."""

    def setUp(self):
        super().setUp()
        self.c = self.w.tab_comp
        self.canvas = self.c.timeline.canvas
        self.w._go_to(2)
        support.pump()
        # Window shortcuts only fire in the active window, as for a real
        # user; make sure it is, rather than let shortcut tests pass vacuously.
        from PyQt6.QtTest import QTest
        self.w.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(self.w, 3000),
                        "test window could not be activated")
        q = mock.patch.object(QMessageBox, "question",
                              return_value=QMessageBox.StandardButton.Discard)
        self.question = q.start()
        self.addCleanup(q.stop)

    def open(self, name="demo 0"):
        self.assertTrue(self.c.open_file(f"{name}.json"))
        support.pump()

    def gesture_center(self, kind):
        i = next(i for i, g in enumerate(self.canvas.gestures) if g.kind == kind)
        rect = next(r for r, j in self.canvas._rects if j == i)
        return rect.center().toPoint()

    def drag(self, start, end):
        from PyQt6.QtTest import QTest
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        for k in range(1, 6):
            p = start + (end - start) * k / 5
            QTest.mouseMove(self.canvas, p)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        support.pump()

    def test_open_shows_actions_and_is_saved(self):
        self.open()
        kinds = sorted(g.kind for g in self.canvas.gestures)
        self.assertEqual(kinds, ["click", "key", "move"])
        self.assertEqual(self.c.lbl_doc_state.text(), "Saved")
        self.assertFalse(self.c.has_unsaved())

    def test_click_select_delete_undo_redo(self):
        from PyQt6.QtTest import QTest
        self.open()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.gesture_center("key"))
        self.assertEqual([g.kind for g in self.canvas.selected_gestures()], ["key"])
        QTest.keyClick(self.canvas, Qt.Key.Key_Delete)
        self.assertNotIn("key", [g.kind for g in self.canvas.gestures])
        self.assertEqual(self.c.lbl_doc_state.text(), "Unsaved changes")
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertIn("key", [g.kind for g in self.canvas.gestures])
        self.assertFalse(self.c.has_unsaved())
        QTest.keyClick(self.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertNotIn("key", [g.kind for g in self.canvas.gestures])

    def test_shortcuts_work_anywhere_in_the_composer(self):
        """Ctrl+Z etc. must not need the timeline to be focused."""
        from PyQt6.QtTest import QTest
        self.open()
        n = len(self.c._events)
        self.c._apply(lambda ev: ev[:-2], self.c._events)
        for target in (self.c.btn_save_copy, self.c.list_avail):
            target.setFocus()
            support.pump()
            QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(len(self.c._events), n, type(target).__name__)
            QTest.keyClick(target, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(len(self.c._events), n - 2, type(target).__name__)

    def test_no_two_shortcuts_share_a_key(self):
        """Regression: Ctrl+Y was registered twice, which Qt treats as
        ambiguous and then fires neither."""
        keys = [sc.key().toString() for sc in self.c._shortcuts]
        self.assertEqual(len(keys), len(set(keys)), keys)
        self.assertTrue(all(keys))

    def test_text_fields_keep_their_own_undo(self):
        from PyQt6.QtTest import QTest
        self.open()
        self.c._apply(lambda ev: ev[:-2], self.c._events)
        edited = len(self.c._events)
        self.c.name_edit.setFocus()
        support.pump()
        QTest.keyClicks(self.c.name_edit, "x")
        QTest.keyClick(self.c.name_edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.c.name_edit.text(), "demo 0")       # typing undone
        self.assertEqual(len(self.c._events), edited)              # timeline untouched
        QTest.keyClick(self.c.name_edit, Qt.Key.Key_Backspace)
        self.assertEqual(len(self.c._events), edited)              # Backspace edits text

    def test_legend_explains_shortcuts_and_shows_test_hotkey(self):
        texts = [w.text() for w in self.c.findChildren(type(self.c.lbl_info))]
        for phrase in ("Undo", "Redo", "Zoom the timeline", "Test play from anywhere"):
            self.assertIn(phrase, texts)
        chips = [w.text() for w in self.c.legend_test_keys.findChildren(type(self.c.lbl_info))]
        self.assertEqual(chips, ["F9"])

    def test_test_play_hotkey_plays_the_edit_from_any_page(self):
        self.open()
        self.c._apply(lambda ev: ev[:3], self.c._events)
        self.w._go_to(4)                                  # another page
        self.w._bridge.hotkey_test.emit()
        support.pump()
        self.assertTrue(self.w._player.is_playing() or self.w._player._mouse.log)
        self.w._player._thread.join(3)
        support.pump(10)
        self.assertIn(("move", (10, 10)), self.w._player._mouse.log)

    def test_test_play_hotkey_on_empty_composer_explains(self):
        self.c._new(confirm=False)
        self.w._bridge.hotkey_test.emit()
        support.pump()
        self.assertFalse(self.w._player.is_playing())
        self.assertIn("empty", self.w._status._label.text())

    def test_drag_an_action_moves_it_later(self):
        self.open()
        before = next(g.start for g in self.canvas.gestures if g.kind == "key")
        start = self.gesture_center("key")
        self.drag(start, start + type(start)(int(self.canvas.pps * 1.0), 0))
        after = next(g.start for g in self.canvas.gestures if g.kind == "key")
        self.assertAlmostEqual(after - before, 1.0, delta=0.05)

    def test_drag_select_time_then_cut_and_paste(self):
        from PyQt6.QtCore import QPoint
        self.open()
        y = int(self.canvas.tracks()[-1].top + self.canvas.tracks()[-1].height + 4)
        x0, x1 = int(self.canvas.x_of(0.15)), int(self.canvas.x_of(0.35))
        self.drag(QPoint(x0, y), QPoint(x1, y))
        a, b = self.canvas.range
        self.assertAlmostEqual(a, 0.15, delta=0.02)
        self.assertAlmostEqual(b, 0.35, delta=0.02)
        self.c.cut()
        self.assertNotIn("click", [g.kind for g in self.canvas.gestures])
        self.canvas.set_playhead(0.0)
        self.c.paste()
        self.assertIn("click", [g.kind for g in self.canvas.gestures])

    def test_save_overwrites_only_the_opened_macro(self):
        self.open()
        self.c._apply(lambda ev: ev[:-2], self.c._events)          # drop last key
        self.assertTrue(self.c._save())
        self.assertEqual(self.store.list_files(), ["demo 0.json", "demo 1.json", "demo 2.json"])
        self.assertLess(len(self.store.load("demo 0.json").events), 5)

    def test_changed_name_saves_a_copy_and_keeps_the_original(self):
        self.open()
        self.c.name_edit.setText("demo 1")                           # taken
        self.assertTrue(self.c._save())
        self.assertIn("demo 1 (2).json", self.store.list_files())
        self.assertEqual(len(self.store.load("demo 0.json").events), 5)
        self.assertEqual(self.c.name_edit.text(), "demo 1 (2)")

    def test_saving_updates_the_player_if_it_has_that_macro(self):
        self.select(0)
        self.open()
        self.c._apply(lambda ev: ev[:-2], self.c._events)
        self.c._save()
        self.assertEqual(len(self.w._loaded_macro.events), len(self.c._events))

    def test_build_a_new_macro_from_scratch(self):
        self.c.ins_text.setText("hi")
        self.c._insert_text()
        self.c.ins_keys.setText("<ctrl>+c")
        self.c._insert_keys()
        self.c.ins_wait.setSeconds(2)
        self.c._insert_wait()
        self.c.list_avail.setCurrentRow(0)
        self.c.spin_times.setValue(2)
        self.c._insert_selected()
        self.c.name_edit.setText("built")
        self.assertTrue(self.c._save())
        m = self.store.load("built.json")
        keys = [e.key for e in m.events if e.type == "key_press"]
        self.assertEqual(keys[:4], ["h", "i", "Key.ctrl_l", "c"])
        self.assertEqual(sum(1 for e in m.events if e.type == "mouse_click"), 4)

    def test_drop_a_library_macro_onto_the_timeline(self):
        self.open()
        n = len(self.c._events)
        self.canvas.macro_dropped.emit("demo 1.json", 0.0)
        self.assertEqual(len(self.c._events), 2 * n)

    def test_unsaved_changes_are_protected(self):
        self.open()
        self.c._apply(lambda ev: ev[:-2], self.c._events)
        self.question.return_value = QMessageBox.StandardButton.Cancel
        self.assertFalse(self.c.open_file("demo 1.json"))
        self.assertEqual(self.c.opened_file(), "demo 0.json")
        closed = self.w.close()
        self.assertFalse(closed)                           # Cancel keeps AMT open
        self.question.return_value = QMessageBox.StandardButton.Discard
        self.assertTrue(self.c.open_file("demo 1.json"))

    def test_deleting_the_opened_macro_keeps_the_edit_as_new(self):
        self.open()
        self.w._delete_macro("demo 0.json")
        self.assertIsNone(self.c.opened_file())
        self.assertEqual(self.c.lbl_doc_state.text(), "New, not saved")
        self.assertTrue(self.c._events)

    def test_edit_button_in_library_opens_composer(self):
        self.w._go_to(1)
        self.select(2)
        self.w.tab_lib_play.btn_edit.click()
        support.pump()
        self.assertEqual(self.w.pages.currentIndex(), 2)
        self.assertEqual(self.c.opened_file(), "demo 2.json")

    def test_test_play_runs_the_unsaved_edit(self):
        self.open()
        self.c._apply(lambda ev: ev[:3], self.c._events)          # move + click only
        self.c._toggle_test()
        self.w._player._thread.join(3)
        support.pump(10)
        self.assertFalse(self.w._player.is_playing())
        self.assertEqual(self.c.btn_test.text(), "Test play")
        self.assertIn(("move", (10, 10)), self.w._player._mouse.log)

    def test_inspector_edits_a_click(self):
        from PyQt6.QtTest import QTest
        self.open()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton,
                         pos=self.gesture_center("click"))
        self.c.ins_x.setValue(-500)
        self.c.ins_y.setValue(42)
        self.c.ins_len.setSeconds(0.5)
        self.c._apply_inspector()
        clicks = [e for e in self.c._events if e.type == "mouse_click"]
        self.assertEqual({(e.x, e.y) for e in clicks}, {(-500, 42)})
        self.assertAlmostEqual(clicks[1].timestamp - clicks[0].timestamp, 0.5)


class AutoClickPage(AppTest):
    def test_hotkey_start_and_stop_sync_buttons(self):
        a = self.w.tab_auto
        self.w._bridge.hotkey_auto_on.emit()
        support.pump()
        self.assertFalse(a.btn_start.isEnabled())
        self.w._bridge.hotkey_auto_off.emit()
        support.pump()
        self.assertTrue(a.btn_start.isEnabled())

    def test_negative_coordinates_accepted(self):
        self.w.tab_auto.spin_x.setValue(-1035)
        self.assertEqual(self.w.tab_auto.fixed_x(), -1035)

    def test_rate_label_tells_the_real_rate(self):
        a = self.w.tab_auto
        a.spin_hold.setValue(0.04)
        a.spin_interval.setValue(0.1)
        self.assertIn("10.0 clicks per second", a.lbl_rate.text())
        self.assertNotIn("hold", a.lbl_rate.text())
        a.spin_interval.setValue(0.01)           # the 40 ms hold cannot fit
        self.assertIn("22.2 clicks per second", a.lbl_rate.text())
        self.assertIn("hold", a.lbl_rate.text())
        a.spin_hold.setValue(0.005)              # 5 ms hold: 100 per second
        self.assertIn("100.0 clicks per second", a.lbl_rate.text())
        a.spin_hold.setValue(0.04)

    def test_rate_label_and_clicker_agree(self):
        from src.core.autoclicker import click_period
        a = self.w.tab_auto
        for iv, hold in ((0.1, 0.04), (0.01, 0.04), (0.25, 0.3)):
            a.spin_interval.setValue(iv)
            a.spin_hold.setValue(hold)
            self.assertIn(f"{1 / click_period(iv, hold):,.1f} clicks per second",
                          a.lbl_rate.text())


class SettingsPage(AppTest):
    """Settings save themselves: no Save button, nothing to forget."""

    def saved_file(self):
        with open(app_paths.settings_file(), encoding="utf-8") as f:
            return json.load(f)

    def type_hotkey(self, edit, text):
        edit.setText(text)
        edit.editingFinished.emit()          # Enter or leaving the field
        support.pump()

    def test_no_save_or_discard_buttons_any_more(self):
        s = self.w.tab_cfg
        self.assertFalse(hasattr(s, "btn_save"))
        self.assertFalse(hasattr(s, "btn_discard"))

    def test_typed_hotkey_saves_itself_and_is_registered(self):
        s = self.w.tab_cfg
        self.type_hotkey(s.hk_play_edit, "<ctrl>+<shift>+1")
        self.assertEqual(self.w._cfg["hotkey_play"], "<ctrl>+<shift>+1")
        self.assertEqual(self.saved_file()["hotkey_play"], "<ctrl>+<shift>+1")
        self.assertEqual(self.w._hotkeys.errors, [])

    def test_bound_hotkey_saves_itself(self):
        from src.ui import settings_tab
        s = self.w.tab_cfg

        class FakeDialog:
            captured = "<ctrl>+r"

            def __init__(self, *_a):
                pass

            def exec(self):
                return settings_tab.QDialog.DialogCode.Accepted

            def deleteLater(self):
                pass
        with mock.patch.object(settings_tab, "KeyCaptureDialog", FakeDialog):
            s._capture_hotkey(s.hk_record_edit)
        self.assertEqual(self.saved_file()["hotkey_record"], "<ctrl>+r")

    def test_hotkeys_are_paused_while_binding(self):
        # Hotkeys are kept from other programs, so with them active the Bind
        # dialog could never receive F8, and pressing it would start playback.
        from src.ui import settings_tab
        s, seen = self.w.tab_cfg, []
        hk = self.w._hotkeys

        class FakeDialog:
            captured = None

            def __init__(self, *_a):
                pass

            def exec(self):
                seen.append(hk.paused)
                raise RuntimeError("dialog failed")      # resume must still happen

            def deleteLater(self):
                pass
        self.assertFalse(hk.paused)
        with mock.patch.object(settings_tab, "KeyCaptureDialog", FakeDialog):
            with self.assertRaises(RuntimeError):
                s._capture_hotkey(s.hk_record_edit)
        self.assertEqual(seen, [True])
        self.assertFalse(hk.paused)

    def test_bad_hotkey_is_explained_inline_and_only_it_is_kept_back(self):
        s = self.w.tab_cfg
        play = DEFAULT_HOTKEYS["hotkey_play"]
        s.hk_test_edit.setText("<f12>")                          # a valid change …
        self.type_hotkey(s.hk_play_edit, DEFAULT_HOTKEYS["hotkey_record"])  # … and a clash
        self.assertEqual(self.w._cfg["hotkey_play"], play)        # clash not saved
        self.assertEqual(self.w._cfg["hotkey_test"], "<f12>")     # the rest is
        self.assertEqual(s.hk_play_edit.property("invalid"), "true")
        self.assertTrue(s.lbl_hk_error.isVisibleTo(s))
        self.assertIn("same keys as Record", s.lbl_hk_error.text())
        self.type_hotkey(s.hk_play_edit, "<ctrl>+<f2>")           # fixed
        self.assertFalse(s.lbl_hk_error.isVisibleTo(s))
        self.assertEqual(self.saved_file()["hotkey_play"], "<ctrl>+<f2>")

    def test_theme_click_applies_and_saves(self):
        s = self.w.tab_cfg
        s._swatch_by_name["Light"].click()
        support.pump()
        self.assertEqual(theme.current(), "Light")
        self.assertEqual(self.saved_file()["theme"], "Light")

    def test_load_new_recordings_switch_is_saved_and_survives_restart(self):
        from src.ui.main_window import _clean_cfg
        s = self.w.tab_cfg
        self.assertTrue(s.chk_load_new.isChecked())               # on by default
        s.chk_load_new.setChecked(False)
        support.pump()
        self.assertIs(self.saved_file()["load_after_record"], False)
        # Regression: the settings cleaner used to drop every non-text value.
        self.assertIs(_clean_cfg(self.saved_file())["load_after_record"], False)

    def test_bind_dialog_captures_ctrl_letter_and_shift_digit(self):
        from src.ui.settings_tab import KeyCaptureDialog
        for key, vk, mods, text, want in (
                (Qt.Key.Key_R, 0x52, Qt.KeyboardModifier.ControlModifier, "\x12", "<ctrl>+r"),
                (Qt.Key.Key_Exclam, 0x31, Qt.KeyboardModifier.ShiftModifier, "!", "<shift>+1")):
            dlg = KeyCaptureDialog()
            dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods, 0, vk, 0, text))
            self.assertEqual(dlg.captured, want)

    def test_unusable_macro_folder_keeps_the_old_one(self):
        old = self.w._store.directory
        with mock.patch("src.ui.main_window.MacroStore", side_effect=OSError("nope")):
            self.w._on_settings_saved({**self.w._cfg, "macro_dir": "Z:\\missing"})
        self.assertEqual(self.w._store.directory, old)


class InfoTips(AppTest):
    def test_popup_shows_at_once_and_hides(self):
        self.w._go_to(1)
        support.pump()
        tip = self.w.tab_lib_play.findChildren(InfoTip)[0]
        support.qapp().sendEvent(tip, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        pop = _InfoPopup.get()
        self.assertTrue(pop.isVisible())
        support.qapp().sendEvent(tip, QEvent(QEvent.Type.Leave))
        self.assertFalse(pop.isVisible())

    def test_icons_survive_the_bubble_being_destroyed_first(self):
        """Regression (deterministic version of the shutdown crash): Qt can
        destroy the shared bubble before the icons; hiding them then must
        not touch the dead object."""
        from PyQt6 import sip
        self.w._go_to(1)
        support.pump()
        pop = _InfoPopup.get()
        pop.deleteLater()
        support.flush_deletes()
        self.assertTrue(sip.isdeleted(pop))
        errors = []
        old_hook = sys.excepthook
        sys.excepthook = lambda *a: errors.append(a[1])
        try:
            self.w._go_to(4)            # hides the page: every icon's hideEvent runs
            support.pump()
        finally:
            sys.excepthook = old_hook
        self.assertEqual(errors, [])
        tip = self.w.tab_cfg.findChildren(InfoTip)[0]
        support.qapp().sendEvent(tip, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        self.assertTrue(_InfoPopup.get().isVisible())   # a fresh bubble is made

    def test_most_settings_have_a_tip(self):
        for page, n in ((self.w.tab_rec, 2), (self.w.tab_lib_play, 6), (self.w.tab_comp, 3),
                        (self.w.tab_auto, 8), (self.w.tab_cfg, 4)):
            self.assertGreaterEqual(len(page.findChildren(InfoTip)), n, type(page).__name__)


class HelpPage(AppTest):
    def setUp(self):
        super().setUp()
        self.h = self.w.tab_help
        self.w._go_to(5)
        support.pump()

    def test_guide_loads_with_contents(self):
        titles = [self.h.toc.item(i).text().strip() for i in range(self.h.toc.count())]
        for section in ("A quick tour of the window", "Record", "Player & Library",
                        "Composer", "Auto Click", "Settings"):
            self.assertIn(section, titles)

    def test_every_link_inside_the_guide_leads_somewhere(self):
        import re
        from src.ui.help_tab import docs_dir
        with open(os.path.join(docs_dir(), "GUIDE.md"), encoding="utf-8") as f:
            text = f.read()
        anchors = re.findall(r"\]\(#([^)]+)\)", text)
        self.assertTrue(anchors)
        for a in anchors:
            self.assertIsNotNone(self.h.heading_position(a), f"broken link #{a}")
        for img in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
            self.assertTrue(os.path.exists(os.path.join(docs_dir(), img)), img)

    def test_contents_and_links_scroll_to_the_section(self):
        from PyQt6.QtCore import QUrl
        bar = self.h.view.verticalScrollBar()
        bar.setValue(0)
        self.h._on_link(QUrl("#auto-click"))
        self.assertGreater(bar.value(), 0)
        bar.setValue(0)
        item = next(self.h.toc.item(i) for i in range(self.h.toc.count())
                    if self.h.toc.item(i).text().strip() == "Settings")
        self.h._on_toc(item)
        self.assertGreater(bar.value(), 0)

    def test_contents_follow_the_reading_position(self):
        bar = self.h.view.verticalScrollBar()
        for title in ("Record", "Composer", "Settings"):
            pos = self.h.heading_position(
                next(t for _l, t, _p in self.h._headings if t == title).lower()
                .replace(" ", "-"))
            self.h.scroll_to_position(pos)
            support.pump()
            self.assertEqual(self.h.toc.currentItem().text().strip(), title)
        bar.setValue(bar.maximum())
        support.pump()
        self.assertEqual(self.h.toc.currentRow(), self.h.toc.count() - 1)
        bar.setValue(0)
        support.pump()
        self.assertEqual(self.h.toc.currentRow(), 0)

    def test_screenshots_fit_the_reading_area(self):
        from PyQt6.QtGui import QTextCursor
        self.w.resize(900, 700)
        support.pump()
        doc = self.h.view.document()
        avail = self.h.view.viewport().width()
        self.assertTrue(self.h._images)
        for pos, _natural in self.h._images:
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
            self.assertLessEqual(c.charFormat().toImageFormat().width(), avail)


class CleanShutdown(unittest.TestCase):
    def test_app_opens_every_page_and_quits_without_errors(self):
        """Regression: at exit Qt destroyed the info bubble before the (i)
        icons, whose hide handlers then touched it and aborted the process.
        Any traceback or non-zero exit during start-up, use or shutdown fails."""
        code = textwrap.dedent(f"""
            import os, sys
            os.environ["AMT_HOME"] = {app_paths.home()!r}
            sys.path.insert(0, {support.ROOT!r})
            from tests import support
            support.qapp()
            support.stub_global_input()
            from PyQt6.QtCore import QPointF, QEvent
            from PyQt6.QtGui import QEnterEvent
            from src.ui.main_window import MainWindow
            from src.ui.widgets import InfoTip
            w = MainWindow()
            w.show()
            for i in range(len(w.nav_buttons)):
                w._go_to(i)
                support.pump()
                for tip in w.pages.currentWidget().findChildren(InfoTip)[:2]:
                    support.qapp().sendEvent(tip, QEnterEvent(QPointF(3, 3), QPointF(3, 3),
                                                              QPointF(3, 3)))
            w.close()
            support.qapp().quit()
            print("clean")
        """)
        r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("clean", r.stdout)
        self.assertEqual(r.stderr.strip(), "", r.stderr)


class CrashSafety(unittest.TestCase):
    def test_error_in_a_slot_is_reported_not_fatal(self):
        """Regression: PyQt6 used to abort the whole app on any slot error."""
        code = textwrap.dedent(f"""
            import os, sys
            os.environ["AMT_HOME"] = {app_paths.home()!r}
            sys.path.insert(0, {support.ROOT!r})
            from unittest import mock
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication([])
            from src.ui import errors
            errors.install(app)
            QMessageBox.exec = lambda self: 0
            def boom(): raise RuntimeError("synthetic")
            QTimer.singleShot(0, boom)
            QTimer.singleShot(300, app.quit)
            app.exec()
            print("survived")
        """)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=60)
        self.assertIn("survived", r.stdout, r.stderr)
        with open(os.path.join(app_paths.log_dir(), "amt.log"), encoding="utf-8") as f:
            self.assertIn("synthetic", f.read())


if __name__ == "__main__":
    unittest.main()
