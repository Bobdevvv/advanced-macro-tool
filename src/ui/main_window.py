from __future__ import annotations
import json
import os
import shutil
from typing import List, Optional

from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStatusBar,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QByteArray, QObject, Qt, pyqtSignal, pyqtSlot

from src import app_paths
from src.defaults import DEFAULT_HOTKEYS, SETTINGS_VERSION, migrate_hotkeys
from src import brand as brand_info
from src.models.macro import Macro
from src.core.recorder          import Recorder
from src.core.player            import Player
from src.core.autoclicker       import AutoClicker
from src.core.hotkey_manager    import HotkeyManager
from src.storage.macro_store    import MacroExistsError, MacroStore

from src.ui                     import icons, theme
from src.ui.icons               import G
from src.ui.logo                import LogoMark
from src.ui.recorder_tab        import RecorderTab
from src.ui.library_player_tab  import LibraryPlayerTab
from src.ui.composer_tab        import ComposerTab
from src.ui.autoclicker_tab     import AutoclickerTab
from src.ui.settings_tab        import SettingsTab
from src.ui.help_tab            import HelpTab
from src.ui                     import errors
from src.ui.theme               import DEFAULT_THEME
from src.ui.widgets             import (
    KeyCombo, button, label, set_button_glyph, set_prop,
)

# Below this window width the sidebar collapses to icons only.
_COMPACT_BELOW = 960


# ---------------------------------------------------------------------------
# Thread → UI signal bridge
# ---------------------------------------------------------------------------

class _Bridge(QObject):
    player_started  = pyqtSignal()
    player_finished = pyqtSignal()
    player_event    = pyqtSignal(int, int)
    player_loop     = pyqtSignal(int)
    clicker_tick    = pyqtSignal(int)
    clicker_done    = pyqtSignal()
    hotkey_rec_on   = pyqtSignal()
    hotkey_rec_off  = pyqtSignal()
    hotkey_play     = pyqtSignal()
    hotkey_auto_on  = pyqtSignal()
    hotkey_auto_off = pyqtSignal()
    hotkey_test     = pyqtSignal()


class _NowLoaded(QFrame):
    """Sidebar panel showing the loaded macro from every page.

    Clicking the panel opens the player; the button plays or stops.  In the
    compact sidebar only the button remains, with the name as its tooltip.
    """

    play_clicked = pyqtSignal()
    open_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("NowLoaded")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open the player")
        self._macro: Optional[Macro] = None
        self._playing = False
        self._compact = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(4)

        self._head = label("LOADED MACRO", "SectionLabel")
        lay.addWidget(self._head)
        self._name = label("Nothing loaded", "NowName")
        self._meta = label("Pick one in Player & Library", "Hint", wrap=True)
        lay.addWidget(self._name)
        lay.addWidget(self._meta)

        self._progress = QProgressBar()
        self._progress.setObjectName("NowProgress")
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        lay.addSpacing(4)
        lay.addWidget(self._progress)

        self.btn = button("Play", "primary", G.PLAY)
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self.play_clicked)
        lay.addSpacing(4)
        lay.addWidget(self.btn)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_clicked.emit()
        super().mousePressEvent(e)

    def set_macro(self, macro: Optional[Macro]) -> None:
        self._macro = macro
        if macro is None:
            self._name.setText("Nothing loaded")
            self._meta.setText("Pick one in Player & Library")
        else:
            self._name.setText(self._elided(macro.name))
            self._name.setToolTip(macro.name)
            self._meta.setText(f"{macro.duration():.2f} s  ·  {len(macro.events):,} events")
        self.set_playing(False)

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        has = self._macro is not None
        self.btn.setEnabled(has)
        self._progress.setVisible(playing)
        if not playing:
            self._progress.setValue(0)
        self.btn.setText("" if self._compact else ("Stop" if playing else "Play"))
        set_button_glyph(self.btn, G.STOP if playing else G.PLAY,
                         "danger" if playing else "primary")
        name = self._macro.name if has else "No macro loaded"
        self.btn.setToolTip(f"{'Stop' if playing else 'Play'}: {name}" if has else name)

    def set_progress(self, pct: int) -> None:
        self._progress.setValue(pct)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        for w in (self._head, self._name, self._meta):
            w.setVisible(not compact)
        self.layout().setContentsMargins(*( (6, 6, 6, 6) if compact else (12, 10, 12, 12)))
        self.set_playing(self._playing)

    def _elided(self, text: str) -> str:
        fm = self._name.fontMetrics()
        return fm.elidedText(text, Qt.TextElideMode.ElideRight, 190)


class _StatusBar(QStatusBar):
    """Status bar whose message sits in a padded label (Qt's built-in
    message text ignores stylesheet padding and hugs the window edge)."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizeGripEnabled(False)
        self._label = QLabel()
        self.addWidget(self._label, 1)

        # Copyright notice, right-aligned and quieter than status messages.
        notice = QLabel(
            f"{brand_info.APP_NAME}  ·  {brand_info.COPYRIGHT}  ·  "
            f"{brand_info.LICENSE_NAME}"
        )
        notice.setObjectName("Copyright")
        notice.setToolTip(
            f"{brand_info.APP_NAME} ({brand_info.APP_SHORT})\n"
            f"Copyright {brand_info.COPYRIGHT}.\n"
            f"Released under the {brand_info.LICENSE_NAME}; "
            "provided without warranty."
        )
        self.addPermanentWidget(notice)

    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802
        self._label.setText(text)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_CFG = {
    **DEFAULT_HOTKEYS,
    "load_after_record":  True,
    "macro_dir":          "",
    "theme":              DEFAULT_THEME,
}


def _default_macro_dir() -> str:
    return app_paths.default_macro_dir()


def _cfg_path() -> str:
    return app_paths.settings_file()


def _clean_cfg(raw) -> dict:
    """Defaults overlaid with the values from settings.json that have the
    right type.  A hand-edited or damaged file can therefore never crash
    start-up; bad values just fall back to their defaults."""
    cfg = dict(_DEFAULT_CFG)
    if isinstance(raw, dict):
        for key, value in raw.items():
            # Keep a value only if it has the default's type (text for
            # hotkeys and paths, True/False for switches).
            if key in _DEFAULT_CFG and type(value) is not type(_DEFAULT_CFG[key]):
                continue
            cfg[key] = value
    return cfg


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{brand_info.APP_SHORT} — {brand_info.APP_NAME}")
        self.setMinimumSize(720, 520)
        self.resize(1120, 760)

        self._cfg      = self._load_cfg()
        self._store    = self._open_store(self._cfg.get("macro_dir", ""))
        self._recorder = Recorder()
        self._player   = Player()
        self._clicker  = AutoClicker()
        self._hotkeys  = HotkeyManager()
        self._bridge   = _Bridge()
        self._loaded_macro: Optional[Macro] = None
        self._play_source = "player"     # or "editor" for a Composer test play
        self._compact: Optional[bool] = None

        # Theme first, so icons are drawn in the right colours.
        theme.apply_theme(self._cfg.get("theme", DEFAULT_THEME))

        self.tab_rec      = RecorderTab()
        self.tab_lib_play = LibraryPlayerTab()
        self.tab_comp     = ComposerTab()
        self.tab_auto     = AutoclickerTab()
        self.tab_cfg      = SettingsTab()
        self.tab_help     = HelpTab()

        self._build_shell()

        self._status = _StatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")

        self._connect_all()
        self.tab_cfg.load(self._cfg)
        self._apply_theme(self._cfg.get("theme", DEFAULT_THEME))
        self._refresh_library()
        self._register_hotkeys()
        self._update_hotkey_labels()
        self._restore_geometry()

    # ==================================================================
    # Shell: sidebar + pages
    # ==================================================================

    _NAV = (
        ("Record",            G.RECORD),
        ("Player && Library", G.PLAY),
        ("Composer",          G.TIMELINE),
        ("Auto Click",        G.MOUSE),
        ("Settings",          G.SETTINGS),
        ("Help",              G.HELP),
    )

    def _build_shell(self) -> None:
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # -- Sidebar --
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 18, 12, 14)
        side.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        mark = LogoMark(32)
        mark.setObjectName("BrandMark")
        mark.setToolTip(brand_info.APP_NAME)
        brand.addWidget(mark)
        self._brand_text = QWidget()
        self._brand_text.setToolTip(brand_info.APP_NAME)
        bt = QVBoxLayout(self._brand_text)
        bt.setContentsMargins(0, 0, 0, 0)
        bt.setSpacing(0)
        bt.addWidget(label(brand_info.APP_SHORT, "BrandName"))
        bt.addWidget(label(brand_info.TAGLINE, "BrandTag"))
        brand.addWidget(self._brand_text, 1)
        side.addLayout(brand)
        side.addSpacing(22)

        self._section_label = label("WORKSPACE", "SectionLabel")
        self._section_label.setContentsMargins(10, 0, 0, 6)
        side.addWidget(self._section_label)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for i, (text, glyph) in enumerate(self._NAV):
            b = QPushButton(text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("full_text", text)
            b.setToolTip(text.replace("&&", "&"))
            icons.bind(b, glyph, "muted", 17, checked_role="accent")
            self._nav_group.addButton(b, i)
            self.nav_buttons.append(b)
            if text == "Settings":       # Settings and Help sit at the bottom
                side.addStretch(1)
                self.now_loaded = _NowLoaded()
                self.now_loaded.open_clicked.connect(lambda: self._go_to(1))
                self.now_loaded.play_clicked.connect(self._toggle_play_hk)
                side.addWidget(self.now_loaded)
                side.addSpacing(8)
                self._hotkey_panel = self._build_hotkey_panel()
                side.addWidget(self._hotkey_panel)
                side.addSpacing(10)
            side.addWidget(b)
        self._nav_group.idClicked.connect(self._go_to)
        row.addWidget(self.sidebar)

        # -- Pages --
        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        for page in (self.tab_rec, self.tab_lib_play, self.tab_comp,
                     self.tab_auto, self.tab_cfg, self.tab_help):
            self.pages.addWidget(page)
        row.addWidget(self.pages, 1)

        self.setCentralWidget(central)
        self._go_to(0)
        self._set_compact(False)

    def _build_hotkey_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("HotkeyPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        grid.addWidget(label("HOTKEYS", "SectionLabel"), 0, 0, 1, 2)
        self._hk_chips = {}
        for r, (key, text) in enumerate((("hotkey_record", "Record"),
                                         ("hotkey_play", "Play / stop"),
                                         ("hotkey_test", "Test play"),
                                         ("hotkey_autoclicker", "Auto click")), 1):
            grid.addWidget(label(text, role="muted"), r, 0)
            chip = KeyCombo("")
            self._hk_chips[key] = chip
            grid.addWidget(chip, r, 1, Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(0, 1)
        return panel

    def _go_to(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def _set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.sidebar.setFixedWidth(64 if compact else 232)
        self._brand_text.setVisible(not compact)
        self._section_label.setVisible(not compact)
        self._hotkey_panel.setVisible(not compact)
        self.now_loaded.set_compact(compact)
        for b in self.nav_buttons:
            b.setText("" if compact else b.property("full_text"))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._set_compact(self.width() < _COMPACT_BELOW)

    def _set_live(self, index: int, live: bool) -> None:
        """Highlight a nav entry while its activity is running."""
        set_prop(self.nav_buttons[index], "live", "true" if live else "false")

    def _update_hotkey_labels(self) -> None:
        for key, chip in self._hk_chips.items():
            chip.set_hotkey(self._cfg.get(key, ""))
        self.tab_rec.update_hotkey_label(self._cfg.get("hotkey_record", ""))
        self.tab_auto.update_hotkey_label(self._cfg.get("hotkey_autoclicker", ""))
        self.tab_comp.update_hotkey_label(self._cfg.get("hotkey_test", ""))

    def _restore_geometry(self) -> None:
        geo = self._cfg.get("window_geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(geo.encode("ascii")))
            except Exception:
                pass

    # ==================================================================
    # Wiring
    # ==================================================================

    def _connect_all(self) -> None:
        # Recorder
        self.tab_rec.set_count_fn(self._recorder.event_count)
        self.tab_rec.recording_started.connect(self._on_rec_start)
        self.tab_rec.recording_stopped.connect(self._on_rec_stop)

        # Library + Player (combined tab)
        self.tab_lib_play.macro_deleted.connect(self._delete_macro)
        self.tab_lib_play.play_requested.connect(self._on_play)
        self.tab_lib_play.stop_requested.connect(self._on_play_stop)
        self.tab_lib_play.unload_requested.connect(self._on_unload)
        self.tab_lib_play.set_rename_fn(self._rename_macro)
        self.tab_lib_play.set_export_fn(self._export_macro)
        self.tab_lib_play.set_load_macro_fn(self._load_macro_for_display)
        self.tab_lib_play.loaded_changed.connect(self._on_loaded_changed)

        # Player core → bridge → UI
        self._player.on_start  = self._bridge.player_started.emit
        self._player.on_finish = self._bridge.player_finished.emit
        self._player.on_event  = self._bridge.player_event.emit
        self._player.on_loop   = self._bridge.player_loop.emit
        self._bridge.player_started.connect(self._on_player_started)
        self._bridge.player_finished.connect(self._on_player_finished)
        self._bridge.player_event.connect(self._on_player_event)
        self._bridge.player_loop.connect(self._on_player_loop)

        # Composer (timeline editor)
        self.tab_comp.set_load_fn(self._read_macro)
        self.tab_comp.set_save_fn(self._editor_save)
        self.tab_comp.test_play_requested.connect(self._on_editor_test)
        self.tab_comp.test_stop_requested.connect(self._on_play_stop)
        self.tab_lib_play.edit_requested.connect(self._edit_in_composer)
        self.tab_lib_play.import_requested.connect(self._import_macros)

        # AutoClicker
        self.tab_auto.start_requested.connect(self._on_clicker_start)
        self.tab_auto.stop_requested.connect(self._on_clicker_stop)
        self._clicker.on_click = self._bridge.clicker_tick.emit
        self._clicker.on_stop  = self._bridge.clicker_done.emit
        self._bridge.clicker_tick.connect(self._on_clicker_tick)
        self._bridge.clicker_done.connect(self._on_clicker_done)

        # Settings
        self.tab_cfg.settings_changed.connect(self._on_settings_saved)
        self.tab_cfg.binding_started.connect(self._hotkeys.pause)
        self.tab_cfg.binding_finished.connect(self._hotkeys.resume)

        # Hotkey bridge
        self._bridge.hotkey_rec_on.connect(self.tab_rec.trigger_start)
        self._bridge.hotkey_rec_off.connect(self.tab_rec.trigger_stop)
        self._bridge.hotkey_play.connect(self._toggle_play_hk)
        self._bridge.hotkey_auto_on.connect(self._on_clicker_hk_start)
        self._bridge.hotkey_auto_off.connect(self._on_clicker_hk_stop)
        self._bridge.hotkey_test.connect(self._toggle_test_hk)

    # ==================================================================
    # Recorder
    # ==================================================================

    @pyqtSlot()
    def _on_rec_start(self) -> None:
        name = self.tab_rec.macro_name()
        if not name or name.lower() == "untitled":
            name = self._next_untitled_name()
            self.tab_rec.name_input.setText(name)
        self._recorder.suppressed_keys = self._hotkey_chars()
        self._recorder.record_moves = self.tab_rec.record_mouse_move()
        self._recorder.start(name)
        self._set_live(0, True)
        self._status.showMessage(f"Recording '{name}'…")

    @pyqtSlot(str, bool)
    def _on_rec_stop(self, name: str, via_button: bool = False) -> None:
        self._set_live(0, False)
        macro = self._recorder.stop(drop_final_click=via_button)
        if macro is None:
            return
        if not macro.events:
            self._status.showMessage("Recording stopped — no events captured")
            return
        try:
            filename = self._store.save(macro)   # picks a free name if it is taken
        except OSError as exc:
            QMessageBox.critical(
                self, "Could not save the recording",
                f"The recording could not be written to\n{self._store.directory}"
                f"\n\n{exc}")
            return
        renamed = "" if macro.name == name else f" (\u2018{name}\u2019 was taken)"
        self._status.showMessage(
            f"Saved '{macro.name}'{renamed}  ({len(macro.events):,} events, "
            f"{macro.duration():.2f}s)")
        self._refresh_library()
        self.tab_rec.name_input.clear()
        # Ready to test: the new recording becomes the loaded macro.
        if self._cfg.get("load_after_record", True) and not self._player.is_playing():
            self.tab_lib_play.select_and_load(filename)

    def _next_untitled_name(self) -> str:
        """Return the next available Untitled-N name in sequence."""
        used: set[int] = set()
        for f in self._store.list_files():
            n = f[:-5]
            if n.lower() == "untitled":
                used.add(0)
            elif n.lower().startswith("untitled-"):
                try:
                    used.add(int(n.split("-")[-1]))
                except ValueError:
                    pass
        i = 1
        while i in used:
            i += 1
        return f"Untitled-{i}"

    # ==================================================================
    # Library helpers
    # ==================================================================

    def _refresh_library(self) -> None:
        files = self._store.list_files()
        meta  = {f: self._store.get_metadata(f) for f in files}
        self.tab_lib_play.refresh(files, meta)
        self.tab_comp.refresh(files)

    def _read_macro(self, filename: str) -> Optional[Macro]:
        """Read a macro file without changing what the player has loaded
        (the composer uses this to combine macros)."""
        try:
            return self._store.load(filename)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "Could not open macro",
                f"\u2018{filename[:-5]}\u2019 could not be opened.\n\n{exc}")
            return None

    def _load_macro_for_display(self, filename: str) -> Optional[Macro]:
        """Read a macro for the player page.  The page then calls load_macro,
        which reports the change through loaded_changed."""
        return self._read_macro(filename)

    @pyqtSlot(object)
    def _on_loaded_changed(self, macro: Optional[Macro]) -> None:
        """Single place where the loaded macro changes."""
        self._loaded_macro = macro
        self.now_loaded.set_macro(macro)
        if self._player.is_playing():
            self.now_loaded.set_playing(True)

    @pyqtSlot(str)
    def _delete_macro(self, filename: str) -> None:
        # The page has already unloaded it if it was the loaded macro.
        try:
            self._store.delete(filename)
        except OSError as exc:
            QMessageBox.critical(self, "Could not delete macro", str(exc))
            return
        self._refresh_library()
        self.tab_comp.file_deleted(filename)
        self._status.showMessage(f"Deleted '{filename[:-5]}'")

    def _rename_macro(self, old: str, new_name: str) -> Optional[str]:
        """Rename; returns the new file name, or None if it failed."""
        try:
            new_file = self._store.rename(old, new_name)
        except MacroExistsError as exc:
            QMessageBox.warning(self, "Name already in use",
                                f"{exc}\nChoose a different name.")
            return None
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not rename macro", str(exc))
            return None
        if self.tab_lib_play.loaded_file() == old:
            self.tab_lib_play.rename_loaded(new_name, new_file)
        self.tab_comp.file_renamed(old, new_file, new_name)
        self._refresh_library()
        self.tab_lib_play.select_file(new_file)
        self._status.showMessage(f"Renamed to '{new_name}'")
        return new_file

    def _export_macro(self, filename: str, dest: str) -> None:
        try:
            shutil.copy2(self._store.path_for(filename), dest)
        except OSError as exc:
            QMessageBox.critical(self, "Could not export macro",
                                 f"Could not write {dest}\n\n{exc}")
            return
        self._status.showMessage(f"Exported to {dest}")

    # ==================================================================
    # Player
    # ==================================================================

    @pyqtSlot()
    def _on_unload(self) -> None:
        self._loaded_macro = None
        self._status.showMessage("Macro unloaded")

    @pyqtSlot()
    def _on_play(self) -> None:
        if self._loaded_macro is None or self._player.is_playing():
            return
        self._play_source = "player"
        self._player.speed      = self.tab_lib_play.speed()
        self._player.loop_count = self.tab_lib_play.loop_count()
        self._player.humanize   = self.tab_lib_play.humanize()
        self._player.humanizer.timing_jitter  = self.tab_lib_play.jitter()
        self._player.humanizer.curve_strength = self.tab_lib_play.curve_strength()
        self._player.humanizer.mouse_noise    = self.tab_lib_play.mouse_noise()
        self._player.humanizer.typing_variation = self.tab_lib_play.typing_variation()
        self._player.play(self._loaded_macro)

    @pyqtSlot()
    def _on_play_stop(self) -> None:
        self._player.stop()

    @pyqtSlot()
    def _toggle_play_hk(self) -> None:
        if self._player.is_playing():
            self._on_play_stop()
        elif self._loaded_macro:
            self._on_play()

    @pyqtSlot()
    def _on_player_started(self) -> None:
        self.tab_lib_play.set_playing(True)
        self.now_loaded.set_playing(True)
        self.tab_comp.set_playing(True)
        if self._play_source == "editor":
            self._set_live(2, True)
            self._status.showMessage("Test playing the Composer's edit…")
        else:
            self._set_live(1, True)
            name = self._loaded_macro.name if self._loaded_macro else "macro"
            self._status.showMessage(f"Playing '{name}'…")

    @pyqtSlot()
    def _on_player_finished(self) -> None:
        self.tab_lib_play.set_playing(False)
        self.now_loaded.set_playing(False)
        self.tab_comp.set_playing(False)
        self._set_live(1, False)
        self._set_live(2, False)
        self._status.showMessage("Playback finished")

    @pyqtSlot(int, int)
    def _on_player_event(self, idx: int, total: int) -> None:
        self.tab_lib_play.update_progress(idx, total)
        self.now_loaded.set_progress(int(idx / total * 100) if total else 0)

    @pyqtSlot(int)
    def _on_player_loop(self, n: int) -> None:
        self.tab_lib_play.update_loop(n)

    # ==================================================================
    # Composer
    # ==================================================================

    def _editor_save(self, macro: Macro, overwrite: Optional[str]) -> Optional[str]:
        """Save the Composer's edit; returns the file name, or None.

        ``overwrite`` is the opened file when the user is saving changes to
        it; otherwise the macro gets a free name and nothing is replaced.
        """
        wanted = macro.name
        try:
            if overwrite:
                self._store.save_to(macro, overwrite)
                written = overwrite
            else:
                written = self._store.save(macro)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save macro", str(exc))
            return None
        self._refresh_library()
        # Keep the player in step if it has this macro loaded.
        if self.tab_lib_play.loaded_file() == written and not self._player.is_playing():
            self.tab_lib_play.load_macro(Macro.from_dict(macro.to_dict()), written)
        note = "" if macro.name == wanted else f" (\u2018{wanted}\u2019 was taken)"
        self._status.showMessage(f"Saved '{macro.name}'{note}")
        return written

    @pyqtSlot(list)
    def _import_macros(self, paths: list) -> List[str]:
        """Copy macro files into the library; returns the new file names.

        Each file is checked first (it must be a valid macro) and saved under
        a free name, so an import never replaces a macro you already have.
        """
        imported, problems = [], []
        for path in paths:
            name = os.path.basename(path)
            try:
                macro = Macro.load(path)
                imported.append(self._store.save(macro))
            except (OSError, ValueError) as exc:
                problems.append(f"{name}: {exc}")
        if imported:
            self._refresh_library()
            if not self._player.is_playing():
                self.tab_lib_play.select_and_load(imported[0])
            self._status.showMessage(
                f"Imported {len(imported)} macro{'s' if len(imported) != 1 else ''}. "
                "Only play macros from people you trust.")
        if problems:
            QMessageBox.warning(
                self, "Some files were not imported",
                "These files are not AMT macros, or could not be read:\n\n"
                + "\n".join(problems))
        return imported

    @pyqtSlot(str)
    def _edit_in_composer(self, filename: str) -> None:
        if self.tab_comp.open_file(filename):
            self._go_to(2)

    @pyqtSlot()
    def _toggle_test_hk(self) -> None:
        """Test-play hotkey: play the Composer's edit, or stop playback."""
        if self._player.is_playing():
            self._on_play_stop()
        elif self.tab_comp.current_macro().events:
            self._on_editor_test(self.tab_comp.current_macro())
        else:
            self._status.showMessage("Nothing to test: the Composer is empty")

    @pyqtSlot(object)
    def _on_editor_test(self, macro: Macro) -> None:
        """Play the Composer's unsaved edit once, at normal speed."""
        if self._player.is_playing():
            return
        self._play_source = "editor"
        self._player.speed = 1.0
        self._player.loop_count = 1
        self._player.humanize = False
        self._player.play(macro)

    # ==================================================================
    # AutoClicker
    # ==================================================================

    @pyqtSlot()
    def _on_clicker_start(self) -> None:
        self._clicker.button        = self.tab_auto.button()
        self._clicker.interval      = self.tab_auto.interval()
        self._clicker.jitter        = self.tab_auto.jitter()
        self._clicker.hold_duration = self.tab_auto.hold_duration()
        self._clicker.click_limit   = self.tab_auto.click_limit()
        self._clicker.use_fixed_pos = self.tab_auto.use_fixed_pos()
        self._clicker.fixed_x       = self.tab_auto.fixed_x()
        self._clicker.fixed_y       = self.tab_auto.fixed_y()
        self._clicker.start()
        self._set_live(3, True)
        self._status.showMessage("AutoClicker running…")

    @pyqtSlot()
    def _on_clicker_stop(self) -> None:
        self._clicker.stop()
        self._set_live(3, False)
        self._status.showMessage("AutoClicker stopped")

    @pyqtSlot()
    def _on_clicker_hk_start(self) -> None:
        self.tab_auto.set_running(True)
        self._on_clicker_start()

    @pyqtSlot()
    def _on_clicker_hk_stop(self) -> None:
        self.tab_auto.set_running(False)
        self._on_clicker_stop()

    @pyqtSlot(int)
    def _on_clicker_tick(self, n: int) -> None:
        self.tab_auto.update_count(n)

    @pyqtSlot()
    def _on_clicker_done(self) -> None:
        self.tab_auto.set_stopped()
        self._set_live(3, False)
        self._status.showMessage(
            f"AutoClicker finished ({self._clicker.clicks_done} clicks)"
        )

    # ==================================================================
    # Settings
    # ==================================================================

    @pyqtSlot(dict)
    def _on_settings_saved(self, cfg: dict) -> None:
        new_dir = cfg.get("macro_dir", "").strip()
        if new_dir and os.path.normcase(new_dir) != os.path.normcase(self._store.directory):
            try:
                store = MacroStore(new_dir)
            except OSError as exc:
                QMessageBox.critical(
                    self, "Folder not usable",
                    f"Macros cannot be stored in\n{new_dir}\n\n{exc}\n\n"
                    "The previous folder is still in use.")
                cfg["macro_dir"] = self._cfg.get("macro_dir", "")
                self.tab_cfg.load({**self._cfg, **cfg})
            else:
                self._store = store
                self.tab_comp.detach()
                self._refresh_library()
        self._cfg.update(cfg)
        saved = self._save_cfg()
        self._register_hotkeys()
        self._update_hotkey_labels()
        self._apply_theme(cfg.get("theme", DEFAULT_THEME))
        if saved:
            self._status.showMessage("Settings saved")

    @pyqtSlot(str)
    def _apply_theme(self, name: str) -> None:
        theme.apply_theme(name)
        icons.refresh_all()
        self.tab_cfg.refresh_swatches()
        self.tab_help.load()            # its table colours follow the theme

    # ==================================================================
    # Hotkeys
    # ==================================================================

    def _register_hotkeys(self) -> None:
        self._hotkeys.stop()
        self._hotkeys.set_bindings({
            self._cfg.get("hotkey_record"):      self._hk_record,
            self._cfg.get("hotkey_play"):        self._hk_play,
            self._cfg.get("hotkey_autoclicker"): self._hk_auto,
            self._cfg.get("hotkey_test"):        self._hk_test,
        })
        if self._hotkeys.errors:
            self._status.showMessage(
                "Some hotkeys could not be registered: " + "; ".join(self._hotkeys.errors))

    def _hk_record(self) -> None:
        if self._recorder.recording:
            self._bridge.hotkey_rec_off.emit()
        else:
            self._bridge.hotkey_rec_on.emit()

    def _hk_play(self) -> None:
        self._bridge.hotkey_play.emit()

    def _hk_test(self) -> None:
        self._bridge.hotkey_test.emit()

    def _hk_auto(self) -> None:
        if self._clicker.is_running():
            self._bridge.hotkey_auto_off.emit()
        else:
            self._bridge.hotkey_auto_on.emit()

    _MODIFIERS = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr",
                  "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r"}

    def _hotkey_chars(self) -> set:
        """Keys to leave out of recordings: the main key of each hotkey,
        in the recorder's own naming (``Key.f9``), so pressing the record
        hotkey to stop does not end up inside the macro.

        Only special keys (F-keys, Pause, …) are suppressed.  A hotkey ending
        in a letter such as ``<ctrl>+r`` is not, because that would stop
        every typed "r" from being recorded.
        """
        keys: set = set()
        for hk in (
            self._cfg.get("hotkey_record"),
            self._cfg.get("hotkey_play"),
            self._cfg.get("hotkey_autoclicker"),
            self._cfg.get("hotkey_test"),
        ):
            if not hk:
                continue
            last = hk.split("+")[-1].strip()
            if last.startswith("<") and last.endswith(">"):
                name = last[1:-1].lower()
                if name not in self._MODIFIERS:
                    keys.add(f"Key.{name}")
        return keys

    # ==================================================================
    # Config
    # ==================================================================

    def _load_cfg(self) -> dict:
        try:
            with open(_cfg_path(), encoding="utf-8") as f:
                cfg = _clean_cfg(json.load(f))
        except FileNotFoundError:
            return {**_DEFAULT_CFG, "settings_version": SETTINGS_VERSION}
        except (OSError, ValueError):
            errors.log.warning("settings.json could not be read; using defaults")
            return dict(_DEFAULT_CFG)
        if migrate_hotkeys(cfg):
            # Saved now, so the move to the new defaults happens exactly once.
            self._cfg = cfg
            self._save_cfg()
        return cfg

    def _save_cfg(self) -> bool:
        """Write settings.json atomically; returns False (after telling the
        user) if it could not be written."""
        path = _cfg_path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, indent=2)
            os.replace(tmp, path)
            return True
        except OSError as exc:
            QMessageBox.warning(self, "Settings not saved",
                                f"Could not write {path}\n\n{exc}")
            return False

    def _open_store(self, directory: str) -> MacroStore:
        """The configured macro folder, or the default one if it is unusable
        (for example a removed USB drive)."""
        if directory:
            try:
                return MacroStore(directory)
            except OSError:
                errors.log.warning("Configured macro folder unusable; using default")
        return MacroStore(_default_macro_dir())

    # ==================================================================
    # Cleanup
    # ==================================================================

    def closeEvent(self, event) -> None:
        # Unsaved Composer edits: Save / Discard / Cancel (Cancel keeps AMT open).
        if not self.tab_comp.confirm_discard():
            event.ignore()
            return
        # A recording in progress is saved, not thrown away.
        if self._recorder.recording:
            self.tab_rec.trigger_stop()
        self._cfg["window_geometry"] = bytes(self.saveGeometry().toHex()).decode("ascii")
        self._save_cfg()
        self._player.stop()
        self._clicker.stop()
        self._recorder.stop()
        self._hotkeys.stop()
        super().closeEvent(event)
