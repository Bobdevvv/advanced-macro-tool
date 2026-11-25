from __future__ import annotations
import datetime
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMessageBox,
    QProgressBar, QScrollArea, QSlider, QSplitter, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.models.macro import Macro
from src.ui import icons
from src.ui.icons import G
from src.ui.inputs import CountEdit, NumberEdit
from src.ui.widgets import (
    S2, S3, S4, S5, S6, Card, FormGrid, Pill, ScrollHint, StatTile, button,
    divider, field, hrow, label, with_info,
)


_ROLE_FILE = Qt.ItemDataRole.UserRole

# Order and captions of the stat tiles.
_EVENT_LABELS = {
    "mouse_move":   "Mouse moves",
    "mouse_click":  "Clicks",
    "mouse_scroll": "Scrolls",
    "key_press":    "Key presses",
    "key_release":  "Key releases",
}

# Below this page width the player and library stack vertically.
_STACK_BELOW = 860


def _fmt_date(ts: float) -> str:
    if not ts:
        return "—"
    return datetime.datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")


def _fmt_duration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.2f} s"
    m, s = divmod(sec, 60)
    return f"{int(m)} m {s:04.1f} s"


class _FileDropFilter(QObject):
    """Accepts .json files dropped onto the library list."""

    def __init__(self, on_files, parent=None) -> None:
        super().__init__(parent)
        self._on_files = on_files

    @staticmethod
    def _paths(event) -> List[str]:
        md = event.mimeData()
        if md is None or not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".json")]

    def eventFilter(self, obj, e) -> bool:
        t = e.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._paths(e):
                e.acceptProposedAction()
                return True
        elif t == QEvent.Type.Drop:
            paths = self._paths(e)
            if paths:
                e.acceptProposedAction()
                self._on_files(paths)
                return True
        return False


# ---------------------------------------------------------------------------
# Combined Library + Player tab
# ---------------------------------------------------------------------------

class LibraryPlayerTab(QWidget):
    # Library signals
    macro_deleted = pyqtSignal(str)   # filename

    # Player signals
    play_requested   = pyqtSignal()
    stop_requested   = pyqtSignal()
    unload_requested = pyqtSignal()
    loaded_changed   = pyqtSignal(object)   # Macro, or None when unloaded
    edit_requested   = pyqtSignal(str)      # open this file in the Composer
    import_requested = pyqtSignal(list)     # paths of .json files to import

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._files:          List[str]          = []
        self._loaded_macro:   Optional[Macro]    = None
        self._loaded_file:    Optional[str]      = None   # file of _loaded_macro
        self._playing:        bool               = False
        self._loops_total:    int                = 1      # fixed when Play starts
        self._rename_fn:      Optional[Callable] = None
        self._export_fn:      Optional[Callable] = None
        self._load_macro_fn:  Optional[Callable] = None   # (filename) → Macro | None

        self._setup_ui()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(S6, S5 + 4, S6, S5)
        root.setSpacing(S5)

        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(label("Player & Library", "PageTitle"))
        head.addWidget(label(
            "Play the loaded macro, or pick another one from your library.",
            "PageSubtitle", wrap=True,
        ))
        root.addLayout(head)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(S4)
        self.splitter.addWidget(self._build_player())
        self.splitter.addWidget(self._build_library())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([560, 380])
        root.addWidget(self.splitter, 1)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        want = (Qt.Orientation.Vertical if self.width() < _STACK_BELOW
                else Qt.Orientation.Horizontal)
        if self.splitter.orientation() != want:
            vertical = want == Qt.Orientation.Vertical
            self.splitter.setOrientation(want)
            self._library_card.setMinimumHeight(300 if vertical else 240)
            total = self.splitter.height() if vertical else self.splitter.width()
            share = 0.5 if vertical else 0.6
            self.splitter.setSizes([int(total * share), int(total * (1 - share))])

    # ------------------------------------------------------------------
    # Left panel — Library
    # ------------------------------------------------------------------

    def _build_library(self) -> QWidget:
        card = Card("Library", "", G.LIBRARY).grow()
        self._library_card = card
        card.setMinimumWidth(280)
        card.setMinimumHeight(240)
        self.lbl_count = Pill("0", "idle")
        card.actions.addWidget(self.lbl_count)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter macros…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.make(G.SEARCH, "faint", 14),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._apply_filter)
        card.body.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["NAME", "CREATED"])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(False)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.currentItemChanged.connect(self._on_tree_select)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        # Macro files dropped onto the list are imported.
        self.tree.viewport().setAcceptDrops(True)
        self._drop_filter = _FileDropFilter(self.import_requested.emit, self)
        self.tree.viewport().installEventFilter(self._drop_filter)
        # Delete / Backspace delete the selected macro, but only while the list
        # itself has focus (WidgetShortcut): Backspace in the filter box must
        # keep editing the search text.
        self._delete_keys = []
        for key in ("Del", "Backspace"):
            sc = QShortcut(QKeySequence(key), self.tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._on_delete)
            self._delete_keys.append(sc)
        card.body.addWidget(self.tree, 1)

        self.lbl_empty = label("No macros yet. Record one on the Record page.",
                               "Hint", wrap=True)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(self.lbl_empty)

        self.btn_import = button("Import…", glyph=G.IMPORT,
                                 tooltip="Add macro files (.json) to your library; "
                                         "you can also drop them onto the list")
        self.btn_edit   = button("", glyph=G.TIMELINE, tooltip="Edit in the Composer")
        self.btn_rename = button("", glyph=G.RENAME, tooltip="Rename")
        self.btn_export = button("", glyph=G.EXPORT, tooltip="Export a copy as JSON…")
        self.btn_delete = button("", "danger_soft", G.DELETE,
                                 tooltip="Delete  (Del or Backspace in the list)")
        for b in (self.btn_edit, self.btn_rename, self.btn_export, self.btn_delete):
            b.setFixedWidth(40)
        for b in (self.btn_edit, self.btn_rename, self.btn_export, self.btn_delete):
            b.setEnabled(False)
        self.btn_edit.clicked.connect(
            lambda: self._selected_file() and self.edit_requested.emit(self._selected_file()))
        self.btn_import.clicked.connect(self._on_import)
        self.btn_rename.clicked.connect(self._on_rename)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_export.clicked.connect(self._on_export)

        actions = QHBoxLayout()
        actions.setSpacing(S2)
        actions.addWidget(self.btn_import, 1)
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_rename)
        actions.addWidget(self.btn_export)
        actions.addWidget(self.btn_delete)
        card.body.addLayout(actions)
        card.body.setStretch(1, 1)
        return card

    # ------------------------------------------------------------------
    # Right panel — Player
    # ------------------------------------------------------------------

    def _build_player(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setMinimumWidth(340)

        inner = QWidget()
        inner.setObjectName("PageContent")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(S4)

        lay.addWidget(self._build_now_playing())
        lay.addWidget(self._build_settings())
        lay.addStretch(1)

        scroll.setWidget(inner)
        self._scroll_hint = ScrollHint(scroll)
        return scroll

    def _build_now_playing(self) -> Card:
        card = Card("Player", "", G.PLAY)
        self.lbl_state = Pill("Nothing loaded", "idle")
        card.actions.addWidget(self.lbl_state)

        name_row = QHBoxLayout()
        name_row.setSpacing(S3)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.lbl_loaded = label("No macro loaded", "MacroName")
        self.lbl_loaded.setWordWrap(True)
        self.lbl_loaded_info = label("Select a macro in the library to load it.",
                                     "Hint", wrap=True)
        info.addWidget(self.lbl_loaded)
        info.addWidget(self.lbl_loaded_info)
        name_row.addLayout(info, 1)
        self.btn_unload = button("Unload", "ghost", G.EJECT)
        self.btn_unload.setEnabled(False)
        self.btn_unload.clicked.connect(self._on_unload)
        name_row.addWidget(self.btn_unload, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(name_row)

        # Event breakdown tiles
        self.stats_box = QWidget()
        self.stats_grid = QGridLayout(self.stats_box)
        self.stats_grid.setContentsMargins(0, 0, 0, 0)
        self.stats_grid.setSpacing(S2)
        self._tiles: Dict[str, StatTile] = {}
        for i, (key, cap) in enumerate(_EVENT_LABELS.items()):
            tile = StatTile(cap, "0")
            self._tiles[key] = tile
            self.stats_grid.addWidget(tile, 0, i)
            self.stats_grid.setColumnStretch(i, 1)
        self.stats_box.setVisible(False)
        card.body.addWidget(self.stats_box)

        self.txt_desc = QTextEdit()
        self.txt_desc.setReadOnly(True)
        self.txt_desc.setFixedHeight(56)
        self.txt_desc.setVisible(False)
        card.body.addWidget(self.txt_desc)

        card.body.addWidget(divider())

        # Progress
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        card.body.addWidget(self.progress)
        prog_row = QHBoxLayout()
        self.lbl_progress = label("Ready", role="muted")
        self.lbl_percent = label("0%", role="mono")
        self.lbl_percent.setProperty("role", "mono")
        prog_row.addWidget(self.lbl_progress, 1)
        prog_row.addWidget(self.lbl_percent)
        card.body.addLayout(prog_row)

        # Transport
        self.btn_play = button("Play", "primary", G.PLAY, size="lg")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.play_requested)
        self.btn_stop = button("Stop", "danger_soft", G.STOP, size="lg")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested)
        transport = QHBoxLayout()
        transport.setSpacing(S2)
        transport.addWidget(self.btn_play, 2)
        transport.addWidget(self.btn_stop, 1)
        card.body.addLayout(transport)
        return card

    def _build_settings(self) -> Card:
        card = Card("Playback", "Applied the next time you press Play.", G.SETTINGS)

        form = FormGrid()
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(1, 100)
        self.slider_speed.setValue(10)
        self.slider_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_speed_val = label("1.0×", role="mono")
        self.lbl_speed_val.setMinimumWidth(44)
        self.lbl_speed_val.setAlignment(Qt.AlignmentFlag.AlignRight |
                                        Qt.AlignmentFlag.AlignVCenter)
        self.slider_speed.valueChanged.connect(
            lambda v: self.lbl_speed_val.setText(f"{v/10:.1f}×"))
        form.add("Speed", hrow(self.slider_speed, self.lbl_speed_val, spacing=S3),
                 info="How fast the macro plays compared with how you recorded "
                      "it. 2× takes half the time, 0.5× twice as long. Waits "
                      "between actions scale too.")

        self.spin_loops = CountEdit(unit="times", unlimited_text="Forever",
                                    maximum=99999, value=1)
        form.add("Loops", self.spin_loops,
                 info="How many times the macro plays in a row. Forever (or "
                      "typing 0) keeps repeating until you press Stop or the "
                      "play hotkey.")
        card.body.addLayout(form)
        card.body.addWidget(divider())

        self.chk_humanize = QCheckBox("Humanise movement")
        self.chk_humanize.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body.addLayout(with_info(
            self.chk_humanize,
            "Throws away the recorded mouse path and draws a new, natural one "
            "between each click and scroll: curved, speeding up and slowing "
            "down like a real hand, at your own recorded speed. Clicks still "
            "land exactly where you recorded them. The four settings below "
            "tune it, and are used only while this is on.",
        ))
        card.body.addWidget(label(
            "Replaces the recorded path with smooth curves between clicks and "
            "adds small timing variation, so no two runs are identical.",
            "Hint", wrap=True,
        ))

        self.spin_jitter = NumberEdit(0, 30, decimals=1, unit="%", value=5)
        self.spin_curve = NumberEdit(0, 80, decimals=1, unit="%", value=25)
        # Off by default; people can add a little wobble if they want it.
        self.spin_noise = NumberEdit(0, 20, decimals=0, unit="px", value=0)
        self.spin_typing = NumberEdit(0, 50, decimals=0, unit="%", value=15)

        self.hum_box = QWidget()
        hum = QGridLayout(self.hum_box)
        hum.setContentsMargins(0, S2, 0, 0)
        hum.setHorizontalSpacing(S3)
        tips = {
            "Timing jitter": "Randomly lengthens or shortens the pauses between "
                             "actions by about this percentage, so the rhythm "
                             "is never exactly the same twice. 0 % keeps your "
                             "recorded timing.",
            "Curve arc": "How far the cursor's path bends away from a straight "
                         "line between two clicks. 0 % moves in straight "
                         "lines, about 25 % looks like a natural wrist arc, "
                         "above 50 % is exaggerated.",
            "Mouse noise": "Adds a tiny random wobble of about this many pixels "
                           "to each point along the path, like a slightly "
                           "unsteady hand. 0 px (the default) keeps the path "
                           "perfectly smooth. Clicks are never moved.",
            "Typing variation": "Varies how long each key is held and the pauses "
                                "between keys, each by about this much, so typing "
                                "has a natural rhythm that differs every run. The "
                                "keys themselves and their order never change, so "
                                "shortcuts like Ctrl+C keep working. 0 % plays "
                                "your typing exactly as recorded.",
        }
        # Always editable, so they can be set up before Humanise is switched on.
        hum.setVerticalSpacing(S3)
        for i, (t, w) in enumerate((("Timing jitter", self.spin_jitter),
                                    ("Curve arc", self.spin_curve),
                                    ("Mouse noise", self.spin_noise),
                                    ("Typing variation", self.spin_typing))):
            hum.addLayout(field(t, w, info=tips[t]), i // 2, i % 2)
        hum.setColumnStretch(0, 1)
        hum.setColumnStretch(1, 1)
        card.body.addWidget(self.hum_box)
        return card

    # ==================================================================
    # Library — data management
    # ==================================================================

    def refresh(self, files: List[str],
                meta: Optional[dict] = None) -> None:
        """
        meta: optional dict of filename → {"created_at": float}
              for displaying dates without loading full macros.
        """
        self._files = files
        current = self._selected_file()

        self.tree.blockSignals(True)
        self.tree.clear()
        for f in files:
            name = f[:-5]                         # strip ".json" only
            info = (meta or {}).get(f, {})
            ts   = info.get("created_at", 0)
            item = QTreeWidgetItem([name, _fmt_date(ts)])
            item.setData(0, _ROLE_FILE, f)
            item.setToolTip(0, name)
            if info.get("error"):
                # Still listed (so it can be deleted), but clearly marked.
                item.setText(0, f"\u26a0  {name}")
                item.setToolTip(0, f"This file cannot be opened: {info['error']}")
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight |
                                     Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)

        # Restore the selection without re-loading the macro: refreshing the
        # list must never change what the player has loaded.
        if current:
            self._select(current)
        self.tree.blockSignals(False)
        self._update_actions()

        self.lbl_count.setText(f"{len(files)}")
        self.lbl_empty.setVisible(not files)
        self._apply_filter(self.search.text())

    def _select(self, filename: str) -> bool:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, _ROLE_FILE) == filename:
                self.tree.setCurrentItem(it)
                return True
        return False

    def select_file(self, filename: str) -> None:
        """Highlight a file in the list without loading it."""
        self.tree.blockSignals(True)
        self._select(filename)
        self.tree.blockSignals(False)
        self._update_actions()

    def _update_actions(self) -> None:
        has = self.tree.currentItem() is not None
        for b in (self.btn_edit, self.btn_rename, self.btn_delete, self.btn_export):
            b.setEnabled(has)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setHidden(bool(needle) and needle not in it.text(0).lower())

    def show_details(self, macro: Optional[Macro]) -> None:
        if macro is None:
            self.stats_box.setVisible(False)
            self.txt_desc.setVisible(False)
            self.txt_desc.clear()
            return

        summary = macro.event_summary()
        for key, tile in self._tiles.items():
            tile.set_value(f"{summary.get(key, 0):,}")
        self.stats_box.setVisible(True)

        self.txt_desc.setText(macro.description)
        self.txt_desc.setVisible(bool(macro.description))

    # ==================================================================
    # Player — data management
    # ==================================================================

    def load_macro(self, macro: Macro, filename: Optional[str] = None) -> None:
        self._loaded_macro = macro
        self._loaded_file = filename
        self.lbl_loaded.setText(macro.name)
        created = datetime.datetime.fromtimestamp(macro.created_at)
        self.lbl_loaded_info.setText(
            f"{_fmt_duration(macro.duration())}   ·   {len(macro.events):,} events"
            f"   ·   recorded {created:%b %d %Y, %H:%M}"
        )
        self.show_details(macro)
        if self._playing:
            # Another macro is still playing: the controls keep reflecting
            # that; the new one is ready for the next Play.
            self.loaded_changed.emit(macro)
            return
        self.btn_play.setEnabled(True)
        self.btn_unload.setEnabled(True)
        self._set_progress(0, "Ready")
        self.lbl_state.set("Ready", "accent")
        self.loaded_changed.emit(macro)

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        if playing:
            self._loops_total = self.spin_loops.value()
        has = self._loaded_macro is not None
        self.btn_play.setEnabled(not playing and has)
        self.btn_stop.setEnabled(playing)
        self.btn_unload.setEnabled(not playing and has)
        if playing:
            self.lbl_state.set("●  Playing", "ok")
        else:
            self.lbl_progress.setText("Finished")
            self.lbl_state.set("Ready" if has else "Nothing loaded",
                               "accent" if has else "idle")

    def update_progress(self, idx: int, total: int) -> None:
        pct = int(idx / total * 100) if total else 0
        self.progress.setValue(pct)
        self.lbl_percent.setText(f"{pct}%")
        self.lbl_progress.setText(f"Event {idx:,} of {total:,}")

    def update_loop(self, loop: int) -> None:
        loops  = self._loops_total
        suffix = "∞" if loops == 0 else f"{loops:,}"
        self.lbl_progress.setText(f"Loop {loop:,} of {suffix}")

    def rename_loaded(self, new_name: str, new_file: Optional[str] = None) -> None:
        """Keep the player's title in step when the loaded macro is renamed."""
        if self._loaded_macro:
            self._loaded_macro.name = new_name
            if new_file:
                self._loaded_file = new_file
            self.lbl_loaded.setText(new_name)
            self.loaded_changed.emit(self._loaded_macro)

    def loaded_macro(self) -> Optional[Macro]:
        return self._loaded_macro

    def loaded_file(self) -> Optional[str]:
        return self._loaded_file

    def is_playing(self) -> bool:
        return self._playing

    def _set_progress(self, pct: int, text: str) -> None:
        self.progress.setValue(pct)
        self.lbl_percent.setText(f"{pct}%")
        self.lbl_progress.setText(text)

    # -- Player accessors --
    def speed(self)          -> float: return self.slider_speed.value() / 10.0
    def loop_count(self)     -> int:   return self.spin_loops.value()
    def humanize(self)       -> bool:  return self.chk_humanize.isChecked()
    def jitter(self)         -> float: return self.spin_jitter.value() / 100.0
    def curve_strength(self) -> float: return self.spin_curve.value()  / 100.0
    def mouse_noise(self)    -> float: return float(self.spin_noise.value())
    def typing_variation(self) -> float: return self.spin_typing.value() / 100.0

    # ==================================================================
    # Callbacks / setters
    # ==================================================================

    def set_rename_fn(self, fn: Callable) -> None:
        self._rename_fn = fn

    def set_export_fn(self, fn: Callable) -> None:
        self._export_fn = fn

    def set_load_macro_fn(self, fn: Callable) -> None:
        """fn(filename) → Macro | None — called to load macro details & player."""
        self._load_macro_fn = fn

    # ==================================================================
    # Internal slots
    # ==================================================================

    def _selected_file(self) -> Optional[str]:
        item = self.tree.currentItem()
        return item.data(0, _ROLE_FILE) if item else None

    def _on_tree_select(self, item: Optional[QTreeWidgetItem], _prev) -> None:
        self._update_actions()
        if item and self._load_macro_fn:
            fname = item.data(0, _ROLE_FILE)
            if fname == self._loaded_file:
                return                       # already loaded
            macro = self._load_macro_fn(fname)
            if macro:
                # Auto-load into player
                self.load_macro(macro, fname)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        # Selection already loads the macro; double-click also plays it.
        if self._loaded_macro:
            self.play_requested.emit()

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        # Clicking the macro that is already selected loads it again, e.g.
        # after Unload (selection did not change, so _on_tree_select is silent).
        if item is self.tree.currentItem():
            self._on_tree_select(item, None)

    def select_and_load(self, filename: str) -> bool:
        """Select a macro in the list and load it into the player."""
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, _ROLE_FILE) == filename:
                if it is self.tree.currentItem():
                    self._on_tree_select(it, None)
                else:
                    self.tree.setCurrentItem(it)
                self.tree.scrollToItem(it)
                return self._loaded_file == filename
        return False

    def _on_import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import macros", "", "Macros (*.json)")
        if paths:
            self.import_requested.emit(paths)

    def _on_unload(self) -> None:
        self._loaded_macro = None
        self._loaded_file = None
        self.lbl_loaded.setText("No macro loaded")
        self.lbl_loaded_info.setText("Select a macro in the library to load it.")
        self.show_details(None)
        self.btn_play.setEnabled(False)
        self.btn_unload.setEnabled(False)
        self._set_progress(0, "Ready")
        self.lbl_state.set("Nothing loaded", "idle")
        self.unload_requested.emit()
        self.loaded_changed.emit(None)

    def _on_rename(self) -> None:
        f = self._selected_file()
        if not f or not self._rename_fn:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Macro", "New name:", text=f[:-5])
        if ok and name.strip() and name.strip() != f[:-5]:
            self._rename_fn(f, name.strip())

    def _on_delete(self) -> None:
        f = self._selected_file()
        if not f:
            return
        if self._playing and f == self._loaded_file:
            QMessageBox.information(self, "Macro is playing",
                                    "Stop playback before deleting this macro.")
            return
        if self.confirm_delete(f[:-5]):
            row = self.tree.indexOfTopLevelItem(self.tree.currentItem())
            if f == self._loaded_file:
                self._on_unload()
            self.macro_deleted.emit(f)          # the list is refreshed by now
            # Highlight the next macro (without loading it), so pressing
            # Delete again carries on down the list.
            count = self.tree.topLevelItemCount()
            if count and row >= 0:
                nxt = self.tree.topLevelItem(min(row, count - 1))
                self.select_file(nxt.data(0, _ROLE_FILE))
                self.tree.setFocus()

    def confirm_delete(self, name: str) -> bool:
        """Ask before deleting.  Enter confirms (Yes is the default button),
        Esc or closing the dialog cancels."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Delete Macro")
        box.setText(f"Delete ‘{name}’?")
        box.setInformativeText("This cannot be undone.")
        yes = box.addButton(QMessageBox.StandardButton.Yes)
        no = box.addButton(QMessageBox.StandardButton.No)
        box.setDefaultButton(yes)
        box.setEscapeButton(no)
        box.exec()
        return box.clickedButton() is yes

    def _on_export(self) -> None:
        f = self._selected_file()
        if not f or not self._export_fn:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Macro", f, "JSON (*.json)"
        )
        if dest:
            self._export_fn(f, dest)
