from __future__ import annotations
import ctypes
import random
import threading
import time
from typing import Callable, Optional

from pynput.mouse import Controller as MouseCtrl, Button

# The button is up for at least this long between two clicks; a press that
# follows a release too closely can be merged or ignored by the target.
MIN_RELEASE_GAP = 0.005


def click_period(interval: float, hold: float) -> float:
    """Seconds from one press to the next.

    ``interval`` is the time from one click to the next.  The button has to
    be held for ``hold`` and then be up for a moment, so a hold that does not
    fit inside the interval sets the pace instead.
    """
    return max(interval, hold + MIN_RELEASE_GAP)


class AutoClicker:
    """Dedicated auto-clicker with configurable interval, position, and randomization."""

    def __init__(self) -> None:
        self._thread:     Optional[threading.Thread] = None
        self._stop_event: threading.Event            = threading.Event()
        self._mouse      = MouseCtrl()
        self._count      = 0
        # Clock and wait, replaceable by tests.  ``_wait`` returns True when
        # the clicker has been told to stop.
        self._now  = time.perf_counter
        self._wait = self._stop_event.wait

        # settings
        self.button:            Button = Button.left
        self.interval:          float  = 0.1    # seconds from one click to the next
        self.jitter:            float  = 0.0    # ± seconds of random interval variation
        self.hold_duration:     float  = 0.04   # seconds to hold button per click
        self.click_limit:       int    = 0       # 0 = infinite
        self.use_fixed_pos:     bool   = False
        self.fixed_x:           int    = 0
        self.fixed_y:           int    = 0

        self.on_click: Optional[Callable[[int], None]] = None   # receives click count
        self.on_stop:  Optional[Callable[[], None]]    = None

    # ------------------------------------------------------------------

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._count = 0
        self._thread = threading.Thread(
            target=self._run_precise, daemon=True, name="autoclicker"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def clicks_done(self) -> int:
        return self._count

    # ------------------------------------------------------------------

    def _run_precise(self) -> None:
        """Run with Windows' timer at 1 ms while clicking.

        By default a wait on Windows lasts at least one 15.6 ms timer tick, so
        a 40 ms hold would really be 46.8 ms and 10 ms intervals impossible.
        """
        winmm = getattr(ctypes, "windll", None) and ctypes.windll.winmm
        raised = False
        try:
            raised = bool(winmm) and winmm.timeBeginPeriod(1) == 0
        except (AttributeError, OSError):
            pass
        try:
            self._run()
        finally:
            if raised:
                winmm.timeEndPeriod(1)

    def _run(self) -> None:
        pressed = False
        try:
            next_press = self._now()
            while not self._stop_event.is_set():
                now = self._now()
                late = now - next_press
                if late < 0:
                    if self._wait(-late):
                        break
                elif late > click_period(self.interval, self.hold_duration):
                    # Far behind (the PC was busy or asleep): start a fresh
                    # schedule instead of firing a burst to catch up.
                    next_press = now
                press_at = next_press

                if self.use_fixed_pos:
                    self._mouse.position = (self.fixed_x, self.fixed_y)
                self._mouse.press(self.button)
                pressed = True
                hold = max(0.001, self.hold_duration)
                self._wait(hold)
                self._mouse.release(self.button)
                pressed = False
                released_at = self._now()

                self._count += 1
                if self.on_click:
                    self.on_click(self._count)
                if self.click_limit > 0 and self._count >= self.click_limit:
                    break

                interval = self.interval
                if self.jitter > 0:
                    interval += random.uniform(-self.jitter, self.jitter)
                # Scheduled from the press, so the hold is part of the
                # interval and the rate does not drift.
                next_press = max(press_at + click_period(interval, hold),
                                 released_at + MIN_RELEASE_GAP)
        finally:
            if pressed:                 # never leave the button held down
                try:
                    self._mouse.release(self.button)
                except Exception:
                    pass
            if self.on_stop:
                self.on_stop()
