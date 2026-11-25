from __future__ import annotations

from PyQt6.QtCore import QElapsedTimer, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QVBoxLayout

from src.defaults import DEFAULT_HOTKEYS
from src.ui.icons import G
from src.ui.widgets import (
    S1, S2, S3, S5, Card, KeyCombo, Page, Pill, ResponsiveGrid, button,
    field, label, set_button_glyph, with_info,
)


def _fmt_elapsed(ms: int) -> str:
    s = ms / 1000.0
    m, s = divmod(s, 60)
    return f"{int(m):02d}:{s:04.1f}"


class RecorderTab(Page):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str, bool)   # macro name, stopped via the button

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Record",
            "Capture mouse and keyboard input into a reusable macro.",
            max_width=980,
            parent=parent,
        )
        self._recording   = False
        self._count_fn    = None
        self._pulse_state = False
        self._clock       = QElapsedTimer()

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._pulse_tick)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_count)

        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # -- Status hero --
        hero = Card()
        row = QHBoxLayout()
        row.setSpacing(S5)

        left = QVBoxLayout()
        left.setSpacing(S2)
        self.lbl_status = Pill("Idle", "idle")
        left.addWidget(self.lbl_status)
        left.addSpacing(S1)

        counters = QHBoxLayout()
        counters.setSpacing(S5 + 8)
        ev = QVBoxLayout()
        ev.setSpacing(0)
        self.lbl_events = label("0", "BigValue")
        ev.addWidget(self.lbl_events)
        ev.addWidget(label("events captured", "BigUnit"))
        tm = QVBoxLayout()
        tm.setSpacing(0)
        self.lbl_elapsed = label("00:00.0", "BigValue")
        tm.addWidget(self.lbl_elapsed)
        tm.addWidget(label("elapsed", "BigUnit"))
        counters.addLayout(ev)
        counters.addLayout(tm)
        counters.addStretch()
        left.addLayout(counters)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(S3)
        right.addStretch()
        self.btn_record = button("Start recording", "primary", G.RECORD, size="lg")
        self.btn_record.setMinimumWidth(210)
        self.btn_record.clicked.connect(self._toggle)
        right.addWidget(self.btn_record)

        hk = QHBoxLayout()
        hk.setSpacing(6)
        hk.addStretch()
        hk.addWidget(label("or press", role="faint"))
        self.lbl_hotkey = KeyCombo(DEFAULT_HOTKEYS["hotkey_record"])
        hk.addWidget(self.lbl_hotkey)
        hk.addWidget(label("anywhere", role="faint"))
        right.addLayout(hk)
        right.addStretch()
        row.addLayout(right)

        hero.body.addLayout(row)
        self.body.addWidget(hero)

        # -- Options --
        grid = ResponsiveGrid(min_col_width=320)

        name_card = Card("Macro name", "Used as the file name in your library.", G.RENAME)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. login-sequence")
        self.name_input.setClearButtonEnabled(True)
        name_card.body.addLayout(field(
            "Name", self.name_input,
            "Leave empty to save as Untitled-1, Untitled-2, …",
            info="The macro is saved under this name in your library when you "
                 "stop recording. You can rename it there later.",
        ))
        grid.add(name_card)

        opt_card = Card("Capture", "Choose what ends up in the recording.", G.MOUSE)
        self.chk_mouse_move = QCheckBox("Record mouse movement")
        self.chk_mouse_move.setChecked(True)
        self.chk_mouse_move.setCursor(Qt.CursorShape.PointingHandCursor)
        opt_card.body.addLayout(with_info(
            self.chk_mouse_move,
            "On: every cursor movement is recorded and replayed exactly.\n"
            "Off: only clicks, scrolls and key presses are kept. Playback then "
            "jumps from click to click, unless Humanise movement is on, which "
            "draws natural paths between them.",
        ))
        opt_card.body.addWidget(label(
            "Turn off to keep only clicks, scrolls and keys. Recordings get much "
            "smaller, and the humaniser can still draw paths between clicks.",
            "Hint", wrap=True,
        ))
        grid.add(opt_card)

        self.body.addWidget(grid)
        self.fill()

    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        if self._recording:
            self._do_stop(via_button=True)
        else:
            self._do_start()

    def _do_start(self) -> None:
        self._recording   = True
        self._pulse_state = False
        self.name_input.setEnabled(False)
        self.chk_mouse_move.setEnabled(False)
        self.lbl_events.setText("0")
        self.lbl_elapsed.setText("00:00.0")
        self._clock.start()
        self.btn_record.setText("Stop recording")
        set_button_glyph(self.btn_record, G.STOP, "danger")
        self._pulse_timer.start()
        self._poll_timer.start()
        self._pulse_tick()          # immediate first flash
        self.recording_started.emit()

    def _do_stop(self, via_button: bool = False) -> None:
        self._recording = False
        self._pulse_timer.stop()
        self._poll_timer.stop()
        self._poll_count()
        self.btn_record.setText("Start recording")
        set_button_glyph(self.btn_record, G.RECORD, "primary")
        self.lbl_status.set("Idle", "idle")
        self.name_input.setEnabled(True)
        self.chk_mouse_move.setEnabled(True)
        self.recording_stopped.emit(self.macro_name(), via_button)

    def _pulse_tick(self) -> None:
        self._pulse_state = not self._pulse_state
        self.lbl_status.set("●  Recording", "danger" if self._pulse_state else "dim")

    def _poll_count(self) -> None:
        if self._count_fn:
            self.lbl_events.setText(f"{self._count_fn():,}")
        if self._clock.isValid():
            self.lbl_elapsed.setText(_fmt_elapsed(self._clock.elapsed()))

    # ------------------------------------------------------------------

    def macro_name(self) -> str:
        return self.name_input.text().strip() or "Untitled"

    def record_mouse_move(self) -> bool:
        return self.chk_mouse_move.isChecked()

    def set_count_fn(self, fn) -> None:
        self._count_fn = fn

    def update_hotkey_label(self, hk: str) -> None:
        self.lbl_hotkey.set_hotkey(hk)

    def is_recording(self) -> bool:
        return self._recording

    def trigger_start(self) -> None:
        if not self._recording:
            self._do_start()

    def trigger_stop(self) -> None:
        if self._recording:
            self._do_stop()
