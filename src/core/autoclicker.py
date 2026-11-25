from __future__ import annotations
import random
import threading
from typing import Callable, Optional

from pynput.mouse import Controller as MouseCtrl, Button


class AutoClicker:
    """Dedicated auto-clicker with configurable interval, position, and randomization."""

    def __init__(self) -> None:
        self._thread:     Optional[threading.Thread] = None
        self._stop_event: threading.Event            = threading.Event()
        self._mouse      = MouseCtrl()
        self._count      = 0

        # settings
        self.button:            Button = Button.left
        self.interval:          float  = 0.1    # seconds between clicks
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
            target=self._run, daemon=True, name="autoclicker"
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

    def _run(self) -> None:
        pressed = False
        try:
            while not self._stop_event.is_set():
                if self.use_fixed_pos:
                    self._mouse.position = (self.fixed_x, self.fixed_y)

                self._mouse.press(self.button)
                pressed = True
                self._stop_event.wait(max(0.001, self.hold_duration))
                self._mouse.release(self.button)
                pressed = False

                self._count += 1
                if self.on_click:
                    self.on_click(self._count)

                if self.click_limit > 0 and self._count >= self.click_limit:
                    break

                interval = self.interval
                if self.jitter > 0:
                    interval += random.uniform(-self.jitter, self.jitter)
                self._stop_event.wait(max(0.005, interval))
        finally:
            if pressed:                 # never leave the button held down
                try:
                    self._mouse.release(self.button)
                except Exception:
                    pass
            if self.on_stop:
                self.on_stop()
