from __future__ import annotations
import time
import threading
from typing import Callable, List, Optional

from pynput.mouse    import Controller as MouseCtrl, Button
from pynput.keyboard import Controller as KeyboardCtrl, Key, KeyCode

from src.models.macro import Macro, MacroEvent
from src.core.humanizer import Humanizer


def _str_to_key(s: Optional[str]):
    """Recorded key name -> pynput key, or None if it cannot be replayed.

    Unknown names are skipped rather than guessed: typing the first letter of
    an unrecognised name (the old behaviour) would type the wrong key.
    """
    if not s:
        return None
    if len(s) == 1:
        code = ord(s)
        if 1 <= code <= 26:
            # Ctrl+A … Ctrl+Z as recorded by older versions: the control
            # character, not the key.  Replaying the character would press
            # virtual key 1–26 instead (3 is Ctrl+Break), so map it back to
            # the letter key; the recorded Ctrl press does the rest.
            return KeyCode.from_vk(0x40 + code)
        if code < 32 or code == 127:
            return None
        return KeyCode.from_char(s)
    if s.startswith("vk:"):
        try:
            return KeyCode.from_vk(int(s[3:]))
        except ValueError:
            return None
    if s.startswith("Key."):
        return getattr(Key, s[4:], None)
    return None


def _event_key(ev: MacroEvent):
    """The key to press for a key event.

    The recorded *physical* key (virtual key code) wins over the character:
    it reproduces exactly what was pressed whatever modifiers were held, so
    Ctrl+C replays as Ctrl and the C key, and Shift+1 as Shift and the 1 key.
    Named special keys (Key.ctrl_l, Key.f9 …) replay by name.
    """
    if ev.key and ev.key.startswith("Key."):
        return _str_to_key(ev.key)
    if ev.vk is not None:
        return KeyCode.from_vk(ev.vk)
    return _str_to_key(ev.key)


def _str_to_button(s: str) -> Button:
    return {"left": Button.left, "right": Button.right, "middle": Button.middle}.get(
        s, Button.left
    )


class Player:
    """Replays a Macro with configurable speed, looping, and humanisation."""

    def __init__(self) -> None:
        self._thread:     Optional[threading.Thread] = None
        self._stop_event: threading.Event            = threading.Event()

        self._mouse    = MouseCtrl()
        self._keyboard = KeyboardCtrl()

        # runtime state – track held inputs so we can release on abort
        self._held_keys:    set = set()
        self._held_buttons: set = set()

        # settings
        self.speed:      float = 1.0   # playback multiplier (>1 = faster)
        self.loop_count: int   = 1     # 0 = infinite
        self.humanize:   bool  = False

        self.humanizer = Humanizer()

        # callbacks (called from player thread – use thread-safe Qt signal bridges)
        self.on_start:   Optional[Callable[[], None]]             = None
        self.on_finish:  Optional[Callable[[], None]]             = None
        self.on_event:   Optional[Callable[[int, int], None]]     = None  # (idx, total)
        self.on_loop:    Optional[Callable[[int], None]]          = None  # loop number

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(self, macro: Macro) -> None:
        if self.is_playing():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(macro,), daemon=True, name="macro-player"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._release_all()

    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Playback loop
    # ------------------------------------------------------------------

    def _run(self, macro: Macro) -> None:
        if self.on_start:
            self.on_start()
        try:
            loop = 0
            while not self._stop_event.is_set():
                loop += 1
                if self.on_loop:
                    self.on_loop(loop)
                self._play_once(macro)
                if self.loop_count > 0 and loop >= self.loop_count:
                    break
        finally:
            # Whatever happened (finished, stopped, or an error), never leave
            # a key or button held down, and always tell the UI we are done.
            self._release_all()
            if self.on_finish:
                self.on_finish()

    def _play_once(self, macro: Macro) -> None:
        events: List[MacroEvent] = macro.events
        if self.humanize:
            events = self.humanizer.apply(events)

        total = len(events)
        start = time.perf_counter()

        for idx, ev in enumerate(events):
            if self._stop_event.is_set():
                return
            target = ev.timestamp / self.speed
            elapsed = time.perf_counter() - start
            wait = target - elapsed
            if wait > 0:
                self._stop_event.wait(wait)
            if self._stop_event.is_set():
                return
            self._execute(ev)
            if self.on_event:
                self.on_event(idx + 1, total)

    # ------------------------------------------------------------------
    # Event execution
    # ------------------------------------------------------------------

    def _execute(self, ev: MacroEvent) -> None:
        t = ev.type
        if t == "mouse_move":
            self._mouse.position = (ev.x, ev.y)

        elif t == "mouse_click":
            if ev.x is not None and ev.y is not None:
                # Without humanising, recordings made with mouse movement off
                # have no moves: click where the click was recorded.
                self._mouse.position = (ev.x, ev.y)
            btn = _str_to_button(ev.button)
            if ev.pressed:
                self._mouse.press(btn)
                self._held_buttons.add(btn)
            else:
                self._mouse.release(btn)
                self._held_buttons.discard(btn)

        elif t == "mouse_scroll":
            self._mouse.scroll(ev.dx or 0, ev.dy or 0)

        elif t == "key_press":
            key = _event_key(ev)
            if key:
                self._keyboard.press(key)
                self._held_keys.add(key)

        elif t == "key_release":
            key = _event_key(ev)
            if key:
                self._keyboard.release(key)
                self._held_keys.discard(key)

    def _release_all(self) -> None:
        for key in list(self._held_keys):
            try:
                self._keyboard.release(key)
            except Exception:
                pass
        self._held_keys.clear()
        for btn in list(self._held_buttons):
            try:
                self._mouse.release(btn)
            except Exception:
                pass
        self._held_buttons.clear()
