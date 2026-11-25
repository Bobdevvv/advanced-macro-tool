from __future__ import annotations

import os

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QKeyEvent, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QDialog, QFileDialog, QGridLayout,
    QHBoxLayout, QLineEdit, QVBoxLayout,
)

from src import brand
from src.ui import theme
from src.ui.fonts import UI_FAMILY
from src.ui.icons import G
from src.core.hotkey_manager import hotkey_error, same_hotkey
from src.defaults import DEFAULT_HOTKEYS as D
from src.ui.theme import DEFAULT_THEME, THEME_NAMES
from src.ui.widgets import (
    S2, S3, Card, InfoTip, KeyCombo, Page, ResponsiveGrid, button, label,
    label_with_info, set_prop, with_info,
)


# ---------------------------------------------------------------------------
# Key capture dialog
# ---------------------------------------------------------------------------

_QT_SPECIAL: dict = {}

def _build_special_map():
    m = {
        Qt.Key.Key_F1:  "<f1>",  Qt.Key.Key_F2:  "<f2>",  Qt.Key.Key_F3:  "<f3>",
        Qt.Key.Key_F4:  "<f4>",  Qt.Key.Key_F5:  "<f5>",  Qt.Key.Key_F6:  "<f6>",
        Qt.Key.Key_F7:  "<f7>",  Qt.Key.Key_F8:  "<f8>",  Qt.Key.Key_F9:  "<f9>",
        Qt.Key.Key_F10: "<f10>", Qt.Key.Key_F11: "<f11>", Qt.Key.Key_F12: "<f12>",
        Qt.Key.Key_F13: "<f13>", Qt.Key.Key_F14: "<f14>", Qt.Key.Key_F15: "<f15>",
        Qt.Key.Key_Escape:       "<esc>",
        Qt.Key.Key_Tab:          "<tab>",
        Qt.Key.Key_Space:        "<space>",
        Qt.Key.Key_Return:       "<enter>",
        Qt.Key.Key_Enter:        "<enter>",
        Qt.Key.Key_Backspace:    "<backspace>",
        Qt.Key.Key_Delete:       "<delete>",
        Qt.Key.Key_Insert:       "<insert>",
        Qt.Key.Key_Home:         "<home>",
        Qt.Key.Key_End:          "<end>",
        Qt.Key.Key_PageUp:       "<page_up>",
        Qt.Key.Key_PageDown:     "<page_down>",
        Qt.Key.Key_Up:           "<up>",
        Qt.Key.Key_Down:         "<down>",
        Qt.Key.Key_Left:         "<left>",
        Qt.Key.Key_Right:        "<right>",
        Qt.Key.Key_Print:        "<print_screen>",
        Qt.Key.Key_ScrollLock:   "<scroll_lock>",
        Qt.Key.Key_Pause:        "<pause>",
        Qt.Key.Key_NumLock:      "<num_lock>",
        Qt.Key.Key_CapsLock:     "<caps_lock>",
    }
    return m

def _unshifted_char(vk: int) -> str:
    """The character a key types with no modifiers ("1" for the 1/! key)."""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    try:
        import ctypes
        ch = ctypes.windll.user32.MapVirtualKeyW(vk, 2) & 0xFFFF  # VK -> char
    except (AttributeError, OSError):
        return ""
    c = chr(ch).lower() if ch else ""
    return c if c.isprintable() and not c.isspace() else ""


_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
}


class KeyCaptureDialog(QDialog):
    """Small modal that waits for the user to press a key combination
    and returns it as a pynput-format hotkey string, e.g. '<ctrl>+<f9>'."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bind hotkey")
        self.setModal(True)
        self.setMinimumSize(360, 200)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.captured: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(S3)

        lay.addWidget(label("Press a key or combination", "CardTitle"),
                      0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(label("Modifiers (Ctrl, Alt, Shift) are allowed.", "Hint"),
                      0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_preview = KeyCombo("")
        self.lbl_preview.setMinimumHeight(40)
        prev_row = QHBoxLayout()
        prev_row.addStretch()
        prev_row.addWidget(self.lbl_preview)
        prev_row.addStretch()
        lay.addLayout(prev_row)
        lay.addStretch()

        cancel = button("Cancel", "ghost")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

        global _QT_SPECIAL
        if not _QT_SPECIAL:
            _QT_SPECIAL = _build_special_map()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        if key in _MODIFIER_KEYS:
            return  # wait for non-modifier

        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("<ctrl>")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("<alt>")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("<shift>")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("<cmd>")

        if key in _QT_SPECIAL:
            parts.append(_QT_SPECIAL[key])
        else:
            # Name the physical key, not the typed character: with Ctrl held
            # "R" types "\x12", with Shift "1" types "!".
            char = _unshifted_char(event.nativeVirtualKey())
            if not char:
                return  # a key that cannot be bound; keep waiting
            parts.append(char)

        self.captured = "+".join(parts)
        self.lbl_preview.set_hotkey(self.captured)
        QTimer.singleShot(350, self.accept)  # brief flash so user sees it


# ---------------------------------------------------------------------------
# Theme swatch
# ---------------------------------------------------------------------------

class ThemeSwatch(QAbstractButton):
    """A clickable miniature of the app drawn in one theme's colours."""

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self.theme_name = name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)
        self.setMinimumSize(150, 112)

    def sizeHint(self) -> QSize:
        return QSize(170, 118)

    def paintEvent(self, _e) -> None:
        c   = theme.palette(self.theme_name)
        ui  = theme.palette()             # current theme, for the frame
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        outline = QColor(ui["accent"]) if self.isChecked() else QColor(
            ui["faint"] if self.underMouse() else ui["border2"])

        # Preview area
        prev = QRectF(r.left(), r.top(), r.width(), r.height() - 30)
        clip = QPainterPath()
        clip.addRoundedRect(r, 5, 5)
        p.save()
        p.setClipPath(clip)
        p.fillRect(prev, QColor(c["bg"]))
        side = QRectF(prev.left(), prev.top(), prev.width() * 0.28, prev.height())
        p.fillRect(side, QColor(c["sidebar"]))
        # nav lines in sidebar
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            y = prev.top() + 12 + i * 12
            col = QColor(c["accent"]) if i == 0 else QColor(c["border2"])
            p.setBrush(col)
            p.drawRoundedRect(QRectF(side.left() + 7, y, side.width() - 14, 5), 2.5, 2.5)
        # card
        card = QRectF(side.right() + 8, prev.top() + 10,
                      prev.right() - side.right() - 16, prev.height() - 20)
        p.setBrush(QColor(c["surface"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawRoundedRect(card, 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["text"]))
        p.drawRoundedRect(QRectF(card.left() + 7, card.top() + 8, card.width() * 0.5, 5), 2.5, 2.5)
        p.setBrush(QColor(c["muted"]))
        p.drawRoundedRect(QRectF(card.left() + 7, card.top() + 18, card.width() * 0.7, 4), 2, 2)
        p.setBrush(QColor(c["accent"]))
        p.drawRoundedRect(QRectF(card.left() + 7, card.bottom() - 15, card.width() * 0.38, 9), 3, 3)
        p.setBrush(QColor(c["success"]))
        p.drawEllipse(QRectF(card.right() - 15, card.top() + 8, 7, 7))

        # Label strip
        strip = QRectF(r.left(), prev.bottom(), r.width(), 30)
        p.fillRect(strip, QColor(ui["surface2"]))
        p.restore()

        f = QFont(UI_FAMILY)
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(QColor(ui["text"] if self.isChecked() else ui["muted"]))
        p.drawText(strip.adjusted(10, 0, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.theme_name)
        if self.isChecked():
            p.setPen(QColor(ui["accent"]))
            p.drawText(strip.adjusted(10, 0, -10, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "✓")

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(outline, 2 if self.isChecked() else 1))
        p.drawRoundedRect(r, 5, 5)
        p.end()

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

def _default_dir_hint() -> str:
    return os.path.join("Documents", brand.DIR_NAME, "macros")


class SettingsTab(Page):
    settings_changed = pyqtSignal(dict)   # emitted on every saved change

    def __init__(self, parent=None) -> None:
        super().__init__("Settings", "Hotkeys, appearance and where macros are stored.",
                         max_width=980, parent=parent)
        self._loading = False
        self._saved: dict = {}
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # Header actions
        self.lbl_autosave = label("Changes are saved automatically.", "Hint")
        self.header_actions.addWidget(self.lbl_autosave)

        # -- Hotkeys --
        hk = Card("Global hotkeys", "Work even when AMT is in the background.",
                  G.KEYBOARD)
        grid = QGridLayout()
        grid.setHorizontalSpacing(S3)
        grid.setVerticalSpacing(S3)
        grid.setColumnStretch(1, 1)

        self.hk_record_edit      = QLineEdit()
        self.hk_play_edit        = QLineEdit()
        self.hk_autoclicker_edit = QLineEdit()
        self.hk_test_edit        = QLineEdit()
        # The one list of hotkey fields: saving, loading and validation all
        # read it, so a new hotkey cannot be forgotten in one of them.
        self._hk_fields = (
            ("hotkey_record",      "Record",     D["hotkey_record"],      self.hk_record_edit),
            ("hotkey_play",        "Play",       D["hotkey_play"],        self.hk_play_edit),
            ("hotkey_test",        "Test play",  D["hotkey_test"],        self.hk_test_edit),
            ("hotkey_autoclicker", "Auto click", D["hotkey_autoclicker"], self.hk_autoclicker_edit),
        )
        for r, (title, desc, edit, tip) in enumerate((
            ("Record",      "Start / stop recording",      self.hk_record_edit,
             "Starts a recording, and stops and saves it when pressed again. "
             "The key press itself is not recorded."),
            ("Play",        "Play / stop the loaded macro", self.hk_play_edit,
             "Plays the macro shown in the sidebar's Loaded macro panel, and "
             "stops it when pressed again."),
            ("Test play",   "Play / stop the Composer's edit", self.hk_test_edit,
             "Plays what is open in the Composer right now, including unsaved "
             "changes, and stops it when pressed again. Works from any page "
             "and any window, so you can test the macro where it will run."),
            ("Auto click",  "Start / stop the clicker",     self.hk_autoclicker_edit,
             "Starts the auto clicker with the settings on the Auto Click "
             "page, and stops it when pressed again."),
        )):
            txt = QVBoxLayout()
            txt.setSpacing(0)
            t = label_with_info(title, tip, name="HotkeyName")
            txt.addWidget(t)
            txt.addWidget(label(desc, "Hint"))
            grid.addLayout(txt, r, 0)
            edit.setObjectName("Mono")
            edit.setPlaceholderText("e.g. <f9>")
            edit.setMinimumWidth(140)
            grid.addWidget(edit, r, 1)
            bind = button("Bind…", glyph=G.KEYBOARD,
                          tooltip="Press a key or combination to bind it")
            bind.clicked.connect(lambda _, e=edit: self._capture_hotkey(e))
            grid.addWidget(bind, r, 2)
        hk.body.addLayout(grid)
        self.lbl_hk_error = label("", "HotkeyError", wrap=True)
        self.lbl_hk_error.setVisible(False)
        hk.body.addWidget(self.lbl_hk_error)
        hk.body.addWidget(label(
            "Format: <f9>, <ctrl>+<shift>+r. Bind… fills it in for you. A typed "
            "hotkey is saved when you press Enter or leave the field.", "Hint"))
        self.body.addWidget(hk)

        # -- Behaviour --
        beh = Card("Behaviour", "How AMT reacts to what you do.")
        self.chk_load_new = QCheckBox("Load a new recording into the player")
        self.chk_load_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_load_new.toggled.connect(lambda _on: self._commit())
        beh.body.addLayout(with_info(
            self.chk_load_new,
            "When a recording stops, it is selected in Player & Library and "
            "loaded, so the Play hotkey plays it straight away. Turn off to "
            "keep the macro you had loaded."))
        self.body.addWidget(beh)

        # -- Appearance --
        app = Card("Appearance", "Pick a theme. It is applied and saved straight away.", G.SPARKLE)
        self._swatches = ResponsiveGrid(min_col_width=150, max_cols=4, spacing=S3)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._swatch_by_name = {}
        for name in THEME_NAMES:
            sw = ThemeSwatch(name)
            self._theme_group.addButton(sw)
            self._swatches.add(sw)
            self._swatch_by_name[name] = sw
        self._theme_group.buttonClicked.connect(self._on_theme_clicked)
        app.body.addWidget(self._swatches)
        self.body.addWidget(app)

        # -- Storage --
        st = Card("Storage", "Each macro is one .json file in this folder.", G.FOLDER)
        self.edit_dir = QLineEdit()
        self.edit_dir.setReadOnly(True)
        self.edit_dir.setPlaceholderText(f"Default:  {_default_dir_hint()}")
        btn_browse = button("Browse…", glyph=G.FOLDER)
        btn_browse.clicked.connect(self._browse_dir)
        btn_open = button("Open", "ghost", G.OPEN, tooltip="Open the folder in Explorer")
        btn_open.clicked.connect(self._open_dir)
        row = QHBoxLayout()
        row.setSpacing(S2)
        row.addWidget(self.edit_dir, 1)
        row.addWidget(btn_browse)
        row.addWidget(btn_open)
        row.insertWidget(0, InfoTip(
            "New recordings and combined macros are saved here, and the "
            "library lists the .json files in this folder. Changing it does "
            "not move existing macros."))
        st.body.addLayout(row)
        st.body.addWidget(label(
            "Macros are plain-text keystroke logs. Keep this folder private.",
            "Hint", wrap=True))
        self.body.addWidget(st)
        self.fill()

        # Dirty-state detection after all widgets are built
        for *_x, edit in self._hk_fields:
            edit.editingFinished.connect(self._commit)
        self.edit_dir.textChanged.connect(lambda _t: self._commit())

    # ------------------------------------------------------------------

    def _selected_theme(self) -> str:
        b = self._theme_group.checkedButton()
        return b.theme_name if b else DEFAULT_THEME

    def _on_theme_clicked(self, btn) -> None:
        for sw in self._swatch_by_name.values():
            sw.update()
        self._commit()

    def _capture_hotkey(self, edit: QLineEdit) -> None:
        dlg = KeyCaptureDialog(self)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.captured:
                edit.setText(dlg.captured)
                self._commit()
        finally:
            dlg.deleteLater()           # one dialog per Bind click otherwise

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select macro directory",
                                              self.edit_dir.text())
        if d:
            self.edit_dir.setText(d)

    def _open_dir(self) -> None:
        d = self.edit_dir.text().strip() or os.path.join(
            os.path.expanduser("~"), _default_dir_hint())
        if os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _current(self) -> dict:
        cfg = {key: edit.text().strip() for key, _t, _d, edit in self._hk_fields}
        cfg["macro_dir"] = self.edit_dir.text().strip()
        cfg["theme"] = self._selected_theme()
        cfg["load_after_record"] = self.chk_load_new.isChecked()
        return cfg

    def _hotkey_problems(self, cfg: dict) -> list:
        """Invalid or duplicated hotkeys, as (edit, message) pairs."""
        fields = tuple((title, key, edit) for key, title, _d, edit in self._hk_fields)
        problems = []
        for i, (title, key, edit) in enumerate(fields):
            err = hotkey_error(cfg[key])
            if err:
                problems.append((edit, f"{title}: {err}."))
                continue
            for title2, key2, _e in fields[:i]:
                if same_hotkey(cfg[key], cfg[key2]):
                    problems.append((edit, f"{title} uses the same keys as {title2}."))
        return problems

    def _commit(self) -> None:
        """Save the settings as they are now.

        A hotkey that is invalid or clashes with another is marked red and
        explained under the hotkeys; it keeps its previous value while
        every other change is still saved.
        """
        if self._loading:
            return
        cfg = self._current()
        problems = self._hotkey_problems(cfg)
        bad = {id(e) for e, _m in problems}
        for key, _t, _d, edit in self._hk_fields:
            set_prop(edit, "invalid", "true" if id(edit) in bad else "false")
            if id(edit) in bad:
                cfg[key] = self._saved.get(key, cfg[key])
        self.lbl_hk_error.setText(
            "Not saved: " + " ".join(m for _e, m in problems)
            + " Press Bind… and then the keys you want." if problems else "")
        self.lbl_hk_error.setVisible(bool(problems))
        if cfg != self._saved:
            self._saved = dict(cfg)
            self.settings_changed.emit(cfg)

    # ------------------------------------------------------------------

    def load(self, cfg: dict) -> None:
        self._loading = True
        for *_x, edit in self._hk_fields:
            set_prop(edit, "invalid", "false")
        try:
            for key, _t, default, edit in self._hk_fields:
                edit.setText(cfg.get(key, default))
            self.edit_dir.setText(           cfg.get("macro_dir", ""))
            name = theme.resolve(cfg.get("theme", DEFAULT_THEME))
            sw = self._swatch_by_name.get(name)
            if sw:
                sw.setChecked(True)
            self.chk_load_new.setChecked(bool(cfg.get("load_after_record", True)))
        finally:
            self._loading = False
        self.lbl_hk_error.setVisible(False)
        self._saved = self._current()

    def refresh_swatches(self) -> None:
        for sw in self._swatch_by_name.values():
            sw.update()
