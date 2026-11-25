from __future__ import annotations
import time
import math
import threading
from typing import Callable, Optional

from pynput import mouse, keyboard

from src.models.macro import Macro, MacroEvent


_MIN_MOVE_INTERVAL = 0.030   # seconds between recorded mouse_move events
_MIN_MOVE_DIST     = 4        # pixels of movement required to record


def _key_to_str(key) -> str:
    """Readable name stored in the macro: "a", "Key.space" or "vk:67".

    Control characters (what letters report while Ctrl is held, e.g. "\x03"
    for C) are not readable and not replayable, so those keys are named by
    their key code instead.
    """
    try:
        if key.char is not None and key.char.isprintable():
            return key.char
        if key.vk is not None:
            return f"vk:{key.vk}"
    except AttributeError:
        pass
    return str(key)  # e.g. "Key.space"


def _key_vk(key) -> Optional[int]:
    """Virtual key code of a character key (None for named special keys,
    which replay by name)."""
    vk = getattr(key, "vk", None)
    return vk if isinstance(vk, int) else None


class Recorder:
    """Records mouse and keyboard events into a Macro."""

    def __init__(self) -> None:
        self._macro:    Optional[Macro] = None
        self._t0:       float           = 0.0
        self._recording: bool           = False
        self._lock      = threading.Lock()

        self._mouse_listener:    Optional[mouse.Listener]    = None
        self._keyboard_listener: Optional[keyboard.Listener] = None

        # mouse-move deduplication state
        self._last_move_time: float     = 0.0
        self._last_move_pos:  tuple     = (0, 0)

        # keys to suppress from being recorded (hotkey keys)
        self.suppressed_keys: set[str] = set()

        # when False, only clicks / scrolls / keys are recorded
        self.record_moves: bool = True

        # callbacks
        self.on_event: Optional[Callable[[MacroEvent], None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self, name: str = "Untitled") -> None:
        if self._recording:
            return
        self._macro = Macro(name=name)
        self._t0    = time.perf_counter()
        self._last_move_time = 0.0
        self._last_move_pos  = (0, 0)
        self._recording = True
        self._start_listeners()

    def stop(self, drop_final_click: bool = False) -> Optional[Macro]:
        """Stop and return the recording.

        ``drop_final_click``: the recording was stopped by clicking a button
        in AMT itself, so that click (the last mouse press and everything
        after it) is not part of the user's task and is removed.
        """
        if not self._recording:
            return None
        self._recording = False
        self._stop_listeners()
        macro = self._macro
        if macro is not None:
            with self._lock:
                macro.events = clean_edges(macro.events, drop_final_click)
        return macro

    def event_count(self) -> int:
        if self._macro is None:
            return 0
        return len(self._macro.events)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ts(self) -> float:
        return time.perf_counter() - self._t0

    def _add(self, event: MacroEvent) -> None:
        with self._lock:
            if self._macro:
                self._macro.events.append(event)
        if self.on_event:
            self.on_event(event)

    # -- Mouse callbacks -----------------------------------------------

    # pynput passes ``injected=True`` for input synthesised by a program,
    # e.g. AMT's own playback or clicker.  Only real user input is recorded.

    def _on_move(self, x: int, y: int, injected: bool = False) -> None:
        if not self._recording or not self.record_moves or injected:
            return
        now  = self._ts()
        dist = math.dist((x, y), self._last_move_pos)
        if (now - self._last_move_time) < _MIN_MOVE_INTERVAL and dist < _MIN_MOVE_DIST:
            return
        self._last_move_time = now
        self._last_move_pos  = (x, y)
        self._add(MacroEvent("mouse_move", now, x=x, y=y))

    def _on_click(self, x: int, y: int, button, pressed: bool,
                  injected: bool = False) -> None:
        if not self._recording or injected:
            return
        self._add(MacroEvent("mouse_click", self._ts(), x=x, y=y,
                             button=button.name, pressed=pressed))

    def _on_scroll(self, x: int, y: int, dx: int, dy: int,
                   injected: bool = False) -> None:
        if not self._recording or injected:
            return
        self._add(MacroEvent("mouse_scroll", self._ts(), x=x, y=y, dx=dx, dy=dy))

    # -- Keyboard callbacks --------------------------------------------

    def _on_key_press(self, key, injected: bool = False) -> None:
        if not self._recording or injected:
            return
        s = _key_to_str(key)
        if s in self.suppressed_keys:
            return
        self._add(MacroEvent("key_press", self._ts(), key=s, vk=_key_vk(key)))

    def _on_key_release(self, key, injected: bool = False) -> None:
        if not self._recording or injected:
            return
        s = _key_to_str(key)
        if s in self.suppressed_keys:
            return
        self._add(MacroEvent("key_release", self._ts(), key=s, vk=_key_vk(key)))

    # -- Listener lifecycle --------------------------------------------

    def _start_listeners(self) -> None:
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def _stop_listeners(self) -> None:
        # Join, so no late callback can append to the macro after it has
        # been handed over for saving.
        for attr in ("_mouse_listener", "_keyboard_listener"):
            listener = getattr(self, attr)
            if listener:
                listener.stop()
                if listener is not threading.current_thread():
                    listener.join(timeout=1.0)
                setattr(self, attr, None)


def clean_edges(events: list, drop_final_click: bool) -> list:
    """Remove input that belongs to operating AMT, not to the task.

    * A button *release* at the start whose *press* happened before recording
      began (clicking "Start recording") is dropped: replaying a lone release
      does nothing useful.
    * With ``drop_final_click``, the last mouse press and everything after it
      is dropped: that is the click on "Stop recording".
    """
    out = list(events)
    if drop_final_click:
        for i in range(len(out) - 1, -1, -1):
            e = out[i]
            if e.type == "mouse_click" and e.pressed:
                out = out[:i]
                break
    pressed: set = set()
    cleaned = []
    for e in out:
        if e.type == "mouse_click":
            if e.pressed:
                pressed.add(e.button)
            elif e.button not in pressed:
                continue                 # release without a recorded press
            else:
                pressed.discard(e.button)
        cleaned.append(e)
    return cleaned
