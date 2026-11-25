"""
Composer: a timeline editor for macros.

Open a macro (or start a new one), then cut, copy, paste, delete and move
parts of it, shorten its pauses, and build onto it by inserting other
macros, waits, key combinations or text.  Every change goes through
``_apply``, which records it for Undo/Redo; nothing touches the file until
Save.  Save overwrites only the macro that was opened, and only if its name
was not changed; otherwise it saves a new macro and leaves the original.
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from src.core import editing as ed
from src.core.editing import Clip, EditError
from src.models.macro import Macro, MacroEvent
from src.defaults import DEFAULT_HOTKEYS
from src.ui.icons import G
from src.ui.inputs import DurationEdit, NumberEdit, format_duration
from src.ui.timeline import TimelineView, fmt_time
from src.ui.widgets import (
    S2, S3, Card, KeyCombo, Page, Pill, ResponsiveGrid, button, field, hrow,
    label, label_with_info, set_button_glyph,
)

_ROLE_FILE = Qt.ItemDataRole.UserRole
_HISTORY = 200                     # undo steps kept
_REPEAT_GAP = 0.05                 # between repeats of an inserted macro

# Shared between macros, so you can copy from one and paste into another.
_clipboard: Optional[Clip] = None


class _LibraryList(QListWidget):
    """Saved macros; drag one onto the timeline to insert it there."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ComposerLibrary")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)


class _KeyFilter(QObject):
    """Passes key presses of one widget to a handler."""

    def __init__(self, handler, parent=None) -> None:
        super().__init__(parent)
        self._handler = handler

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() == QEvent.Type.KeyPress:
            return bool(self._handler(e))
        return False


class ComposerTab(Page):
    test_play_requested = pyqtSignal(object)     # Macro (unsaved edit)
    test_stop_requested = pyqtSignal()
    saved = pyqtSignal(str)                      # file name written

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Composer",
            "Edit a macro on a timeline: trim it, move parts around, shorten "
            "pauses, or build a new one from other macros, keys and text.",
            max_width=1400, parent=parent,
        )
        self._load_fn: Optional[Callable[[str], Optional[Macro]]] = None
        self._save_fn: Optional[Callable[[Macro, Optional[str]], Optional[str]]] = None
        self._events: List[MacroEvent] = []
        self._file: Optional[str] = None             # file this edit came from
        self._source: Optional[Macro] = None         # its metadata
        self._saved_events: List[MacroEvent] = []
        self._saved_name = ""
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []
        self._playing = False
        self._setup_ui()
        self._install_shortcuts()
        self._new(confirm=False)

    # ==================================================================
    # UI
    # ==================================================================

    def _setup_ui(self) -> None:
        # -- Document bar --
        doc = Card()
        row = QHBoxLayout()
        row.setSpacing(S2)
        buttons = QHBoxLayout()
        buttons.setSpacing(S2)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the macro")
        self.name_edit.setMinimumWidth(180)
        self.name_edit.textChanged.connect(self._update_state)
        self.lbl_doc_state = Pill("New", "idle")
        self.btn_new = button("New", "ghost", G.NEW, tooltip="Start an empty macro")
        self.btn_new.clicked.connect(lambda: self._new())
        self.btn_save = button("Save", "primary", G.SAVE)
        self.btn_save.clicked.connect(lambda: self._save())
        self.btn_save_copy = button("Save as copy", glyph=G.SAVE,
                                    tooltip="Save as a new macro; the opened one is not changed")
        self.btn_save_copy.clicked.connect(lambda: self._save(as_copy=True))
        self.btn_test = button("Test play", glyph=G.PLAY,
                               tooltip="Play this edit without saving it")
        self.btn_test.clicked.connect(self._toggle_test)
        row.addWidget(label_with_info(
            "Editing", "Save overwrites the macro you opened. If you change the "
            "name, Save keeps the original and saves a new macro instead."))
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.lbl_doc_state)
        # Buttons on their own row, so the bar fits narrow windows too.
        buttons.addWidget(self.btn_new)
        buttons.addStretch()
        for b in (self.btn_test, self.btn_save_copy, self.btn_save):
            buttons.addWidget(b)
        doc.body.addLayout(row)
        doc.body.addLayout(buttons)
        self.body.addWidget(doc)

        # -- Timeline --
        tl = Card("Timeline", "", G.TIMELINE)
        self.lbl_info = label("", role="mono")
        self.lbl_info.setObjectName("Hint")
        bar = QHBoxLayout()
        bar.setSpacing(6)

        def tool(glyph, tip, fn):
            b = button("", "ghost", glyph, tooltip=tip)
            b.setFixedWidth(38)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b
        self.btn_undo = tool(G.UNDO, "Undo  (Ctrl+Z)", self.undo)
        self.btn_redo = tool(G.REDO, "Redo  (Ctrl+Y)", self.redo)
        bar.addSpacing(S2)
        self.btn_cut = tool(G.CUT, "Cut  (Ctrl+X)", self.cut)
        self.btn_copy = tool(G.COPY, "Copy  (Ctrl+C)", self.copy)
        self.btn_paste = tool(G.PASTE, "Paste at the playhead  (Ctrl+V)", self.paste)
        self.btn_delete = tool(G.DELETE, "Delete  (Del)", self.delete)
        bar.addSpacing(S2)
        tool(G.ZOOM_OUT, "Zoom out  (Ctrl+wheel or -)", lambda: self._zoom(0.67))
        tool(G.ZOOM_IN, "Zoom in  (Ctrl+wheel or +)", lambda: self._zoom(1.5))
        tool(G.FIT, "Fit the whole macro", lambda: self.timeline.canvas.fit())
        bar.addStretch()
        self.lbl_sel = label("", role="muted")
        bar.addWidget(self.lbl_sel)
        tl.body.addLayout(bar)

        self.timeline = TimelineView()
        c = self.timeline.canvas
        c.selection_changed.connect(self._on_selection)
        c.playhead_moved.connect(lambda _t: self._update_info())
        c.range_move_requested.connect(self._on_range_move)
        c.gestures_shift_requested.connect(self._on_gestures_shift)
        c.macro_dropped.connect(self._insert_macro_at)
        # A separate filter object, NOT an eventFilter override on this page:
        # the page is a QScrollArea, and Qt routes its own viewport events
        # through the page's eventFilter, even before __init__ has finished.
        self._keys = _KeyFilter(self._timeline_key, self)
        c.installEventFilter(self._keys)
        tl.body.addWidget(self.timeline)
        tl.body.addWidget(self.lbl_info)
        tl.body.addWidget(self._build_legend())
        self.body.addWidget(tl)

        # -- Cards below --
        grid = ResponsiveGrid(min_col_width=330, max_cols=2)
        # Library sits right under the timeline, next to Selection: opening
        # and inserting macros is what people reach for most.
        grid.add(self._build_inspector())
        grid.add(self._build_library())
        grid.add(self._build_optimise())
        grid.add(self._build_insert())
        self.body.addWidget(grid)
        self.fill()

    def _build_legend(self) -> QWidget:
        """Always-visible list of what the mouse and keyboard can do here."""
        grid = ResponsiveGrid(min_col_width=190, max_cols=4, spacing=6)

        def item(keys, text):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for k in keys:
                chip = label(k, "KeyChip")
                chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(chip)
            lay.addWidget(label(text, "Hint"))
            lay.addStretch()
            grid.add(w)
            return w

        item(["Ctrl", "Z"], "Undo")
        item(["Ctrl", "Y"], "Redo")
        item(["Ctrl", "X"], "Cut")
        item(["Ctrl", "C"], "Copy")
        item(["Ctrl", "V"], "Paste at playhead")
        item(["Del"], "Delete selection")
        item(["Ctrl", "A"], "Select everything")
        item(["Esc"], "Clear selection")
        item(["Ctrl", "Scroll"], "Zoom the timeline")
        item(["Shift", "Scroll"], "Scroll sideways")
        item(["Drag"], "Select time, or move it")
        test = item([], "Test play from anywhere")
        self.legend_test_keys = KeyCombo(DEFAULT_HOTKEYS["hotkey_test"])
        test.layout().insertWidget(0, self.legend_test_keys)
        self._legend_test = test
        grid.setToolTip("These work anywhere on the Composer page, except "
                        "while you are typing in a text box.")
        return grid

    def update_hotkey_label(self, hk: str) -> None:
        """Show the current Test play hotkey in the legend and tooltip."""
        self.legend_test_keys.set_hotkey(hk)
        self._legend_test.setVisible(bool(hk))
        nice = "+".join(self._pretty(hk)) if hk else ""
        self.btn_test.setToolTip("Play this edit without saving it"
                                 + (f"  ({nice}, works from any window)" if nice else ""))

    @staticmethod
    def _pretty(hk: str):
        from src.ui.widgets import pretty_hotkey
        return pretty_hotkey(hk)

    def _install_shortcuts(self) -> None:
        """Editing shortcuts for the whole Composer page.

        Scoped to this page (WidgetWithChildrenShortcut), so they work
        wherever the focus is on the page, not only on the timeline.  A focused
        text field keeps its own Ctrl+Z / Ctrl+C / Del: Qt lets the field
        claim its standard keys before a shortcut fires.
        """
        canvas = self.timeline.canvas
        # One shortcut per key: two shortcuts on the same key (e.g. Ctrl+Y as
        # Redo *and* as the standard Redo) are "ambiguous" and neither fires.
        bindings = (
            ("Ctrl+Z", self.undo),
            ("Ctrl+Y", self.redo),
            ("Ctrl+Shift+Z", self.redo),
            ("Ctrl+X", self.cut),
            ("Ctrl+C", self.copy),
            ("Ctrl+V", self.paste),
            ("Del", self.delete),
            ("Backspace", self.delete),
            ("Ctrl+A",
             lambda: canvas.select_range(0, max(canvas.duration(), 0.001))),
        )
        self._shortcuts = []
        for keys, fn in bindings:
            seq = QKeySequence(keys)
            if seq.isEmpty():
                continue
            sc = QShortcut(seq, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)

    def _build_library(self) -> Card:
        card = Card("Library", "Open a macro to edit it, or insert it into this one.",
                    G.LIBRARY)
        self.list_avail = _LibraryList()
        self.list_avail.setMinimumHeight(170)
        self.list_avail.itemDoubleClicked.connect(lambda *_: self._open_selected())
        card.body.addWidget(self.list_avail, 1)
        self.spin_times = NumberEdit(1, 9999, decimals=0, unit="times", value=1)
        self.spin_times.setMaximumWidth(120)
        btn_open = button("Open", glyph=G.OPEN, tooltip="Edit this macro (double-click)")
        btn_open.clicked.connect(self._open_selected)
        btn_ins = button("Insert at playhead", "primary", G.ADD)
        btn_ins.clicked.connect(self._insert_selected)
        card.body.addLayout(hrow(btn_open, btn_ins, self.spin_times, spacing=S2))
        return card

    def _build_insert(self) -> Card:
        card = Card("Insert at playhead", "Build a macro from scratch, or add to one.",
                    G.ADD)
        self.ins_wait = DurationEdit(0.001, 7 * 86400, seconds=1)
        b_wait = button("Insert wait")
        b_wait.clicked.connect(self._insert_wait)
        card.body.addLayout(field("Wait", hrow(self.ins_wait, b_wait, spacing=S2),
                                  info="Adds a pause at the playhead; everything "
                                       "after it moves later."))

        self.ins_keys = QLineEdit()
        self.ins_keys.setObjectName("Mono")
        self.ins_keys.setPlaceholderText("e.g. <ctrl>+c")
        b_bind = button("Bind…", glyph=G.KEYBOARD)
        b_bind.clicked.connect(self._bind_keys)
        b_keys = button("Insert keys")
        b_keys.clicked.connect(self._insert_keys)
        card.body.addLayout(field("Key combination", hrow(self.ins_keys, b_bind, b_keys,
                                                          spacing=S2),
                                  info="Presses and releases a key or shortcut once, "
                                       "e.g. Ctrl+C. Press Bind… and then the keys."))

        self.ins_text = QLineEdit()
        self.ins_text.setPlaceholderText("Text to type")
        b_text = button("Insert text")
        b_text.clicked.connect(self._insert_text)
        card.body.addLayout(field("Text", hrow(self.ins_text, b_text, spacing=S2),
                                  info="Types the text character by character."))
        return card

    def _build_inspector(self) -> Card:
        card = Card("Selection", "", G.SETTINGS)
        self.inspector = QStackedWidget()

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(label("Click an action on the timeline, or drag across it to "
                           "select a stretch of time.", "Hint", wrap=True))
        el.addStretch()

        one = QWidget()
        ol = QVBoxLayout(one)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(S3)
        self.lbl_one = label("", "CardTitle")
        ol.addWidget(self.lbl_one)
        self.ins_start = DurationEdit(0, 7 * 86400, seconds=0)
        self.ins_len = DurationEdit(0, 86400, seconds=0)
        self.ins_x = NumberEdit(-32768, 32767, 0, "px", 0)
        self.ins_y = NumberEdit(-32768, 32767, 0, "px", 0)
        ol.addLayout(field("Starts at", self.ins_start))
        self.len_field = QWidget()
        lf = QVBoxLayout(self.len_field)
        lf.setContentsMargins(0, 0, 0, 0)
        lf.addLayout(field("Held for", self.ins_len,
                           info="How long the key or button stays pressed."))
        ol.addWidget(self.len_field)
        self.pos_field = QWidget()
        pf = QVBoxLayout(self.pos_field)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.addLayout(field("Position (X, Y)", hrow(self.ins_x, self.ins_y, spacing=S2),
                           info="Where the click happens, in screen pixels."))
        ol.addWidget(self.pos_field)
        b_apply = button("Apply changes", "primary")
        b_apply.clicked.connect(self._apply_inspector)
        b_del1 = button("Delete", "danger_soft", G.DELETE)
        b_del1.clicked.connect(self.delete)
        ol.addLayout(hrow(b_apply, b_del1, spacing=S2, stretch_end=True))

        many = QWidget()
        ml = QVBoxLayout(many)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(S3)
        self.lbl_many = label("", "CardTitle")
        self.lbl_many_hint = label("", "Hint", wrap=True)
        ml.addWidget(self.lbl_many)
        ml.addWidget(self.lbl_many_hint)
        b_cut = button("Cut", glyph=G.CUT)
        b_cut.clicked.connect(self.cut)
        b_copy = button("Copy", glyph=G.COPY)
        b_copy.clicked.connect(self.copy)
        b_del = button("Delete", "danger_soft", G.DELETE)
        b_del.clicked.connect(self.delete)
        ml.addLayout(hrow(b_cut, b_copy, b_del, spacing=S2, stretch_end=True))
        ml.addStretch()

        for w in (empty, one, many):
            self.inspector.addWidget(w)
        card.body.addWidget(self.inspector)
        return card

    def _build_optimise(self) -> Card:
        card = Card("Optimise", "Applies to the selected time, or the whole macro.",
                    G.SPARKLE)
        self.opt_limit = DurationEdit(0, 86400, seconds=1)
        self.opt_to = DurationEdit(0, 86400, seconds=0.3)
        b_pauses = button("Shorten pauses")
        b_pauses.clicked.connect(self._shorten_pauses)
        card.body.addLayout(field(
            "Pauses longer than", self.opt_limit,
            info="Every pause between two actions that is longer than this is "
                 "shortened. The idle time before the first action counts too."))
        card.body.addLayout(field("…become", hrow(self.opt_to, b_pauses, spacing=S2)))
        b_moves = button("Remove mouse movement", glyph=G.MOUSE)
        b_moves.clicked.connect(self._remove_moves)
        card.body.addLayout(hrow(b_moves, label_with_info(
            "", "Deletes cursor movement but keeps clicks, which still happen at "
                "their recorded positions. Turn on Humanise when playing to get "
                "smooth paths between them."), spacing=S2, stretch_end=True))
        self.lbl_scope = label("", "Hint")
        card.body.addWidget(self.lbl_scope)
        return card

    # ==================================================================
    # External API (used by the main window)
    # ==================================================================

    def set_load_fn(self, fn: Callable[[str], Optional[Macro]]) -> None:
        self._load_fn = fn

    def set_save_fn(self, fn: Callable[[Macro, Optional[str]], Optional[str]]) -> None:
        """fn(macro, filename_to_overwrite_or_None) -> written file name or None."""
        self._save_fn = fn

    def refresh(self, files: List[str]) -> None:
        current = self.list_avail.currentItem()
        keep = current.data(_ROLE_FILE) if current else None
        self.list_avail.clear()
        for f in files:
            item = QListWidgetItem(f[:-5])
            item.setData(_ROLE_FILE, f)
            self.list_avail.addItem(item)
            if f == keep:
                self.list_avail.setCurrentItem(item)

    def open_file(self, filename: str) -> bool:
        """Open a saved macro for editing (asks first if there are changes)."""
        if not self.confirm_discard() or self._load_fn is None:
            return False
        macro = self._load_fn(filename)
        if macro is None:
            return False
        self._load(macro, filename)
        return True

    def opened_file(self) -> Optional[str]:
        return self._file

    def has_unsaved(self) -> bool:
        return (self._events != self._saved_events
                or self.name_edit.text().strip() != self._saved_name)

    def confirm_discard(self) -> bool:
        """True if it is fine to replace the current edit."""
        if not self.has_unsaved():
            return True
        r = QMessageBox.question(
            self, "Unsaved changes",
            f"Save your changes to ‘{self.name_edit.text().strip() or 'this macro'}"
            "’ first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Save:
            return self._save()
        return r == QMessageBox.StandardButton.Discard

    def file_renamed(self, old: str, new: str, new_name: str) -> None:
        if self._file == old:
            self._file = new
            if self.name_edit.text().strip() == self._saved_name:
                self.name_edit.setText(new_name)
            self._saved_name = new_name
            self._update_state()

    def file_deleted(self, filename: str) -> None:
        """The opened macro was deleted: keep the edit as a new, unsaved one."""
        if self._file is not None and self._file == filename:
            self._file = None
            self._saved_events = []
            self._update_state()

    def detach(self) -> None:
        """The macro folder changed: the edit no longer belongs to a file."""
        if self._file is not None:
            self.file_deleted(self._file)

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.btn_test.setText("Stop" if playing else "Test play")
        set_button_glyph(self.btn_test, G.STOP if playing else G.PLAY,
                         "danger_soft" if playing else None)
        self._update_state()

    def current_macro(self) -> Macro:
        src = self._source
        return Macro(name=self.name_edit.text().strip() or "new-macro",
                     events=list(self._events),
                     created_at=src.created_at if src else time.time(),
                     description=src.description if src else "")

    # ==================================================================
    # Document
    # ==================================================================

    def _new(self, confirm: bool = True) -> None:
        if confirm and not self.confirm_discard():
            return
        self._file, self._source = None, None
        self._saved_events, self._saved_name = [], ""
        self.name_edit.setText("")
        self._reset_history([])

    def _load(self, macro: Macro, filename: str) -> None:
        self._file, self._source = filename, macro
        events = ed.normalize(macro.events)
        self._saved_events = list(events)
        self._saved_name = macro.name
        self.name_edit.setText(macro.name)
        self._reset_history(events)
        self.timeline.canvas.fit()

    def _reset_history(self, events: List[MacroEvent]) -> None:
        self._undo.clear()
        self._redo.clear()
        self._events = list(events)
        self.timeline.canvas.set_playhead(0.0, emit=False)
        self.timeline.canvas.set_events(self._events)
        self.timeline.refresh()
        self._on_selection()

    def _save(self, as_copy: bool = False) -> bool:
        if self._save_fn is None:
            return False
        if not self._events:
            QMessageBox.information(self, "Nothing to save",
                                    "This macro is empty. Add something to it first.")
            return False
        macro = self.current_macro()
        overwrite = None if (as_copy or self._file is None
                             or macro.name != self._saved_name) else self._file
        written = self._save_fn(macro, overwrite)
        if not written:
            return False
        self._file, self._source = written, macro
        self._saved_events = list(self._events)
        self._saved_name = macro.name
        self.name_edit.setText(macro.name)        # may have become "name (2)"
        self._update_state()
        self.saved.emit(written)
        return True

    def _open_selected(self) -> None:
        item = self.list_avail.currentItem()
        if item is not None:
            self.open_file(item.data(_ROLE_FILE))

    def _toggle_test(self) -> None:
        if self._playing:
            self.test_stop_requested.emit()
        elif self._events:
            self.test_play_requested.emit(self.current_macro())

    # ==================================================================
    # Editing (all changes go through _apply)
    # ==================================================================

    def _apply(self, fn, *args, select_range=None, keep_selection=False) -> bool:
        """Run an editing function on the events, with undo and error report."""
        try:
            new = fn(*args)
        except EditError as exc:
            QMessageBox.information(self, "Can't do that", str(exc))
            return False
        if new == self._events:
            return False
        self._undo.append((self._events, self.timeline.canvas.playhead))
        del self._undo[:-_HISTORY]
        self._redo.clear()
        self._set_events(new, keep_selection)
        if select_range:
            self.timeline.canvas.select_range(*select_range)
        return True

    def _set_events(self, events, keep_selection=False) -> None:
        self._events = list(events)
        self.timeline.canvas.set_events(self._events, keep_selection)
        self.timeline.refresh()
        self._on_selection()

    def undo(self) -> None:
        if self._undo:
            events, ph = self._undo.pop()
            self._redo.append((self._events, self.timeline.canvas.playhead))
            self._set_events(events)
            self.timeline.canvas.set_playhead(ph, emit=False)
            self._update_state()

    def redo(self) -> None:
        if self._redo:
            events, ph = self._redo.pop()
            self._undo.append((self._events, self.timeline.canvas.playhead))
            self._set_events(events)
            self.timeline.canvas.set_playhead(ph, emit=False)
            self._update_state()

    def _selection(self):
        c = self.timeline.canvas
        return c.range, c.selected_gestures()

    def copy(self) -> None:
        global _clipboard
        rng, gs = self._selection()
        try:
            if rng:
                _clipboard = ed.copy_range(self._events, *rng)
            elif gs:
                _clipboard = ed.copy_gestures(self._events, gs)
            else:
                return
        except EditError as exc:
            QMessageBox.information(self, "Can't copy", str(exc))
            return
        self._update_state()

    def cut(self) -> None:
        rng, gs = self._selection()
        if not (rng or gs):
            return
        self.copy()
        self.delete()

    def delete(self) -> None:
        rng, gs = self._selection()
        if rng:
            if self._apply(ed.delete_range, self._events, *rng):
                self.timeline.canvas.set_playhead(rng[0])
        elif gs:
            self._apply(ed.delete_gestures, self._events, gs)

    def paste(self) -> None:
        if _clipboard is not None:
            self._insert_clip(_clipboard)

    def _insert_clip(self, clip: Clip, t: Optional[float] = None) -> None:
        t = self.timeline.canvas.playhead if t is None else t
        length = max(clip.length, ed.duration(clip.events))
        if self._apply(ed.paste, self._events, clip, t, select_range=(t, t + length)):
            self.timeline.canvas.set_playhead(t + length)
            self.timeline.ensure_visible(t)

    def _insert_macro_at(self, filename: str, t: float) -> None:
        if self._load_fn is None:
            return
        macro = self._load_fn(filename)
        if macro is None:
            return
        try:
            clip = ed.repeat(Clip(ed.normalize(macro.events), macro.duration() + _REPEAT_GAP),
                             int(self.spin_times.value()))
        except EditError as exc:
            QMessageBox.information(self, "Can't insert", str(exc))
            return
        self._insert_clip(clip, t)

    def _insert_selected(self) -> None:
        item = self.list_avail.currentItem()
        if item is not None:
            self._insert_macro_at(item.data(_ROLE_FILE), self.timeline.canvas.playhead)

    def _insert_wait(self) -> None:
        t = self.timeline.canvas.playhead
        self._apply(ed.insert_gap, self._events, t, self.ins_wait.seconds(),
                    select_range=(t, t + self.ins_wait.seconds()))

    def _insert_keys(self) -> None:
        try:
            clip = ed.key_combo_events(self.ins_keys.text().strip())
        except EditError as exc:
            QMessageBox.information(self, "Can't insert keys", str(exc))
            return
        self._insert_clip(clip)

    def _insert_text(self) -> None:
        try:
            clip = ed.text_events(self.ins_text.text())
        except EditError as exc:
            QMessageBox.information(self, "Can't insert text", str(exc))
            return
        self._insert_clip(clip)

    def _bind_keys(self) -> None:
        from src.ui.settings_tab import KeyCaptureDialog
        dlg = KeyCaptureDialog(self)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.captured:
                self.ins_keys.setText(dlg.captured)
        finally:
            dlg.deleteLater()

    def _on_range_move(self, a: float, b: float, to: float) -> None:
        new_start = to if to < a else to - (b - a)
        self._apply(ed.move_range, self._events, a, b, to,
                    select_range=(new_start, new_start + (b - a)))

    def _on_gestures_shift(self, gs, dt: float) -> None:
        self._apply(ed.shift_gestures, self._events, gs, dt)

    def _shorten_pauses(self) -> None:
        rng, _gs = self._selection()
        a, b = rng if rng else (None, None)
        self._apply(ed.shorten_pauses, self._events, self.opt_limit.seconds(),
                    self.opt_to.seconds(), a, b)

    def _remove_moves(self) -> None:
        rng, _gs = self._selection()
        a, b = rng if rng else (None, None)
        self._apply(ed.remove_mouse_moves, self._events, a, b)

    def _apply_inspector(self) -> None:
        gs = self.timeline.canvas.selected_gestures()
        if len(gs) != 1:
            return
        g = gs[0]

        def change(events):
            # Each step can renumber gestures, so later steps look g up again.
            if g.kind in ("key", "click") and abs(self.ins_len.seconds() - (g.end - g.start)) > 1e-9:
                events = ed.set_gesture_length(events, g, self.ins_len.seconds())
            if g.kind == "click":
                events = ed.set_click_position(events, _same_gesture(events, g),
                                               int(self.ins_x.value()), int(self.ins_y.value()))
            dt = self.ins_start.seconds() - g.start
            if abs(dt) > 1e-9:
                events = ed.shift_gestures(events, [_same_gesture(events, g)], dt)
            return events
        self._apply(change, self._events)

    def _zoom(self, factor: float) -> None:
        c = self.timeline.canvas
        c.set_zoom(c.pps * factor)

    # ==================================================================
    # Keyboard (when the timeline has focus)
    # ==================================================================

    def _timeline_key(self, e) -> bool:
        """Keys that only make sense on the timeline itself (zoom, Esc).

        Editing shortcuts (undo, copy …) are page-wide; see
        _install_shortcuts.  These stay here so typing "-" in a number field
        never zooms the timeline.
        """
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        K = Qt.Key
        canvas = self.timeline.canvas
        actions = {
            (K.Key_Escape, False): canvas.clear_selection,
            (K.Key_Plus, False): lambda: self._zoom(1.5),
            (K.Key_Equal, False): lambda: self._zoom(1.5),
            (K.Key_Minus, False): lambda: self._zoom(0.67),
        }
        fn = actions.get((Qt.Key(e.key()), ctrl))
        if fn is not None:
            fn()
            return True
        return False

    # ==================================================================
    # Display
    # ==================================================================

    def _on_selection(self) -> None:
        rng, gs = self._selection()
        if rng:
            a, b = rng
            n = sum(1 for g in self.timeline.canvas.gestures if g.end >= a and g.start < b)
            self.lbl_many.setText(f"{fmt_time(a, 0.01)} to {fmt_time(b, 0.01)}")
            self.lbl_many_hint.setText(
                f"{format_duration(b - a)} of time with {n} action{'s' if n != 1 else ''}. "
                "Cut or delete it (the rest closes up), drag it to move it, or "
                "use Optimise on just this part.")
            self.inspector.setCurrentIndex(2)
        elif len(gs) == 1:
            g = gs[0]
            self.lbl_one.setText(g.label if g.kind in ("key", "click") else
                                 {"scroll": "Scroll", "move": "Mouse movement"}[g.kind])
            self.ins_start.setSeconds(g.start)
            self.len_field.setVisible(g.kind in ("key", "click"))
            self.ins_len.setSeconds(g.end - g.start)
            self.pos_field.setVisible(g.kind == "click")
            if g.kind == "click":
                ev = self._events[g.indices[0]]
                self.ins_x.setValue(ev.x or 0)
                self.ins_y.setValue(ev.y or 0)
            self.inspector.setCurrentIndex(1)
        elif gs:
            self.lbl_many.setText(f"{len(gs)} actions selected")
            self.lbl_many_hint.setText("Drag them on the timeline to move them "
                                       "together, or cut, copy or delete them.")
            self.inspector.setCurrentIndex(2)
        else:
            self.inspector.setCurrentIndex(0)
        self.lbl_scope.setText("Will change: the selected time" if rng
                               else "Will change: the whole macro")
        self._update_state()

    def _update_info(self) -> None:
        c = self.timeline.canvas
        n = len(c.gestures)
        self.lbl_info.setText(
            f"Playhead {fmt_time(c.playhead, 0.01)}   ·   length "
            f"{fmt_time(c.duration(), 0.01)}   ·   {n} action{'s' if n != 1 else ''}")

    def _update_state(self) -> None:
        rng, gs = self._selection()
        has_sel = bool(rng or gs)
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))
        for b in (self.btn_cut, self.btn_copy, self.btn_delete):
            b.setEnabled(has_sel)
        self.btn_paste.setEnabled(_clipboard is not None)
        self.btn_test.setEnabled(bool(self._events) or self._playing)
        if self._file is None:
            self.lbl_doc_state.set("New, not saved", "warn" if self._events else "idle")
        elif self.has_unsaved():
            self.lbl_doc_state.set("Unsaved changes", "warn")
        else:
            self.lbl_doc_state.set("Saved", "ok")
        self.btn_save.setEnabled(bool(self._events) and (self.has_unsaved() or self._file is None))
        self.lbl_sel.setText("" if not has_sel else
                             ("Time selected" if rng else f"{len(gs)} selected"))
        self._update_info()


def _same_gesture(events, g: ed.Gesture) -> ed.Gesture:
    """Find ``g`` again after an edit renumbered the gestures (same kind,
    closest start)."""
    cands = [x for x in ed.gestures(events) if x.kind == g.kind]
    return min(cands, key=lambda x: abs(x.start - g.start))
