from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from pynput.mouse import Controller as _MouseController
from PyQt6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QVBoxLayout

from pynput.mouse import Button

from src.defaults import DEFAULT_HOTKEYS
from src.ui.icons import G
from src.ui.inputs import CountEdit, DurationEdit, NumberEdit
from src.ui.widgets import (
    S2, S3, S5, Card, KeyCombo, Page, Pill, ResponsiveGrid, Segmented,
    button, field, label, label_with_info, with_info,
)


class AutoclickerTab(Page):
    start_requested = pyqtSignal()
    stop_requested  = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Auto Click",
            "Click repeatedly at a steady rate, at the cursor or a fixed point.",
            max_width=980,
            parent=parent,
        )
        self._running = False
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # -- Status hero --
        hero = Card()
        row = QHBoxLayout()
        row.setSpacing(S5)

        left = QVBoxLayout()
        left.setSpacing(S2)
        self.lbl_state = Pill("Stopped", "idle")
        left.addWidget(self.lbl_state)
        self.lbl_count = label("0", "BigValue")
        left.addWidget(self.lbl_count)
        left.addWidget(label("clicks this run", "BigUnit"))
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(S3)
        right.addStretch()
        btns = QHBoxLayout()
        btns.setSpacing(S2)
        self.btn_start = button("Start", "primary", G.PLAY, size="lg")
        self.btn_start.setMinimumWidth(140)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop = button("Stop", "danger_soft", G.STOP, size="lg")
        self.btn_stop.setMinimumWidth(110)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        right.addLayout(btns)
        hk = QHBoxLayout()
        hk.setSpacing(6)
        hk.addStretch()
        hk.addWidget(label("or press", role="faint"))
        self.lbl_hotkey = KeyCombo(DEFAULT_HOTKEYS["hotkey_autoclicker"])
        hk.addWidget(self.lbl_hotkey)
        hk.addWidget(label("anywhere", role="faint"))
        right.addLayout(hk)
        right.addStretch()
        row.addLayout(right)
        hero.body.addLayout(row)
        self.body.addWidget(hero)

        grid = ResponsiveGrid(min_col_width=330)

        # -- Button + limit --
        btn_card = Card("Click", "Which button, and when to stop.", G.MOUSE)
        self.seg_button = Segmented(["Left", "Right", "Middle"])
        self.rb_left, self.rb_right, self.rb_middle = self.seg_button.buttons
        btn_card.body.addLayout(field(
            "Mouse button", self.seg_button,
            info="Which mouse button is clicked each time."))

        self.spin_limit = CountEdit(unit="clicks", unlimited_text="No limit",
                                    maximum=9_999_999, value=0)
        btn_card.body.addLayout(field(
            "Stop after", self.spin_limit,
            "Type a number, or choose No limit to click until you stop it.",
            info="The clicker stops by itself after this many clicks. No limit "
                 "(or typing 0) keeps clicking until you press Stop or the "
                 "auto click hotkey.",
        ))
        grid.add(btn_card)

        # -- Timing --
        t_card = Card("Timing", "Type a unit to switch it: 250ms, 2s, 1m, 1h.",
                      G.SPARKLE)
        self.spin_interval = DurationEdit(0.01, 86400, seconds=0.1)
        self.spin_interval.valueChanged.connect(self._update_rate)
        t_card.body.addLayout(field(
            "Interval", self.spin_interval,
            info="Time from one click to the next. 100 ms is 10 clicks per "
                 "second; the fastest is 10 ms (100 per second)."))

        self.spin_jitter = DurationEdit(0, 10, seconds=0)
        self.spin_jitter.setToolTip("Random ± offset added to each interval.")
        t_card.body.addLayout(field(
            "Jitter ±", self.spin_jitter,
            info="Adds a random amount, up to this much either way, to each "
                 "interval, so the clicks are not perfectly regular. 0 keeps "
                 "a steady rhythm."))

        self.spin_hold = DurationEdit(0.001, 5, seconds=0.04)
        self.spin_hold.setToolTip("How long the button stays pressed per click.")
        t_card.body.addLayout(field(
            "Hold", self.spin_hold,
            info="How long the button stays pressed down on each click. Some "
                 "programs ignore clicks that are released too quickly."))
        self.lbl_rate = label("", "Hint")
        t_card.body.addWidget(self.lbl_rate)
        self._update_rate()
        grid.add(t_card)

        # -- Position --
        pos_card = Card("Position", "Where each click lands.", G.TARGET)
        self.chk_fixed = QCheckBox("Click at a fixed point")
        self.chk_fixed.setCursor(Qt.CursorShape.PointingHandCursor)
        pos_card.body.addLayout(with_info(
            self.chk_fixed,
            "Off: each click happens wherever the cursor is, so you can move "
            "it while clicking.\nOn: the cursor jumps to X, Y before every "
            "click.",
        ))
        pos_card.body.addWidget(label(
            "Off: clicks wherever the cursor is. On: the cursor moves to X, Y "
            "first. Use Pick, then hover the target for 3 seconds.",
            "Hint", wrap=True,
        ))

        # Negative values are real positions: monitors left of or above the
        # main one have negative coordinates.
        self.spin_x = NumberEdit(-32768, 32767, decimals=0, unit="px", value=0)
        self.spin_y = NumberEdit(-32768, 32767, decimals=0, unit="px", value=0)
        self.btn_pick = button("Pick", glyph=G.TARGET,
                               tooltip="Capture the cursor position after 3 seconds")
        self.btn_pick.setMinimumWidth(96)
        self.btn_pick.clicked.connect(self._pick_position)
        pos_grid = QGridLayout()
        pos_grid.setHorizontalSpacing(S2)
        pos_grid.setVerticalSpacing(6)
        xy_tips = {
            "X": "Horizontal screen position in pixels, counted from the left "
                 "edge of your main monitor. Monitors to its left have "
                 "negative values. Easiest: use Pick.",
            "Y": "Vertical screen position in pixels, counted from the top "
                 "edge of your main monitor. Monitors above it have negative "
                 "values. Easiest: use Pick.",
        }
        for col, (title, w) in enumerate((("X", self.spin_x), ("Y", self.spin_y))):
            pos_grid.addWidget(label_with_info(title, xy_tips[title]), 0, col)
            pos_grid.addWidget(w, 1, col)
            pos_grid.setColumnStretch(col, 1)
        pos_grid.addWidget(self.btn_pick, 1, 2)
        pos_card.body.addLayout(pos_grid)

        for w in (self.spin_x, self.spin_y, self.btn_pick):
            w.setEnabled(False)
        self.chk_fixed.toggled.connect(self.spin_x.setEnabled)
        self.chk_fixed.toggled.connect(self.spin_y.setEnabled)
        self.chk_fixed.toggled.connect(self.btn_pick.setEnabled)
        grid.add(pos_card, span=2)

        self.body.addWidget(grid)
        self.fill()

    # ------------------------------------------------------------------

    def _update_rate(self) -> None:
        iv = self.spin_interval.value()
        if iv > 0:
            self.lbl_rate.setText(f"≈ {1 / iv:,.1f} clicks per second")

    def _on_start(self) -> None:
        self.set_running(True)
        self.start_requested.emit()

    def _on_stop(self) -> None:
        self.set_running(False)
        self.stop_requested.emit()

    def set_running(self, running: bool) -> None:
        """Reflect the clicker's state (also used when a hotkey toggles it)."""
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if running:
            self.lbl_count.setText("0")
            self.lbl_state.set("●  Clicking", "ok")
        else:
            self.lbl_state.set("Stopped", "idle")

    def set_stopped(self) -> None:
        self.set_running(False)

    def is_running(self) -> bool:
        return self._running

    def update_count(self, n: int) -> None:
        self.lbl_count.setText(f"{n:,}")

    def update_hotkey_label(self, hk: str) -> None:
        self.lbl_hotkey.set_hotkey(hk)

    def _pick_position(self) -> None:
        self.btn_pick.setEnabled(False)
        self._pick_cd = 3
        if not hasattr(self, "_pick_timer"):     # one timer, reused per Pick
            self._pick_timer = QTimer(self)
            self._pick_timer.setInterval(1000)
            self._pick_timer.timeout.connect(self._pick_tick)
        self._pick_timer.start()
        self.btn_pick.setText("3…")

    def _pick_tick(self) -> None:
        self._pick_cd -= 1
        if self._pick_cd > 0:
            self.btn_pick.setText(f"{self._pick_cd}…")
        else:
            self._pick_timer.stop()
            # Ask pynput, the same library that will do the clicking, so the
            # coordinates are in its units (physical pixels).  Qt's QCursor
            # reports scaled pixels, which are wrong at 125 % / 150 % scaling.
            x, y = _MouseController().position
            self.spin_x.setValue(int(x))
            self.spin_y.setValue(int(y))
            self.btn_pick.setText("Pick")
            self.btn_pick.setEnabled(self.chk_fixed.isChecked())

    # -- Accessors --

    def button(self) -> Button:
        if self.rb_right.isChecked():
            return Button.right
        if self.rb_middle.isChecked():
            return Button.middle
        return Button.left

    def interval(self)      -> float: return self.spin_interval.value()
    def jitter(self)        -> float: return self.spin_jitter.value()
    def hold_duration(self) -> float: return self.spin_hold.value()
    def click_limit(self)   -> int:   return self.spin_limit.value()
    def use_fixed_pos(self) -> bool:  return self.chk_fixed.isChecked()
    def fixed_x(self)       -> int:   return self.spin_x.value()
    def fixed_y(self)       -> int:   return self.spin_y.value()
