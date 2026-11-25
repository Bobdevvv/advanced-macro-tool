"""
Global hotkeys.

Hotkeys are written like pynput's format — ``<f9>``, ``<ctrl>+r``,
``<ctrl>+<shift>+1`` — but matched by AMT itself.

Why not ``pynput.keyboard.GlobalHotKeys``?  It compares the *character* a key
produces, and on Windows that character changes with the modifiers: Ctrl+R
arrives as ``"\\x12"`` and Shift+1 as ``"!"``, so ``<ctrl>+r`` and
``<shift>+1`` can never fire.  Here every key is compared by its *virtual
key code*, which is the same whatever modifiers are held and whatever the
keyboard layout prints on it.

Matching rules:
* the modifiers held must be exactly the hotkey's modifiers (Ctrl+F9 does not
  also trigger a plain F9 binding);
* a hotkey fires once per press, not on keyboard auto-repeat while held;
* simulated ("injected") input never triggers a hotkey.
"""
from __future__ import annotations

import ctypes
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

_MODIFIERS: Dict[str, str] = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}

Combo = Tuple[FrozenSet[str], int]        # (modifiers, virtual key code)


def _char_vk(ch: str) -> Optional[int]:
    """Virtual key of the key that types ``ch`` on the current layout."""
    if ch.isascii() and ch.isalnum():
        return ord(ch.upper())            # VK codes of A–Z / 0–9 are their ASCII
    try:
        res = ctypes.windll.user32.VkKeyScanW(ord(ch))
    except (AttributeError, OSError):
        return None
    return None if res == -1 or (res & 0xFF) == 0xFF else res & 0xFF


def parse(hotkey: str) -> Combo:
    """``"<ctrl>+r"`` → ({"ctrl"}, 0x52).  Raises ValueError if invalid."""
    if not hotkey or not hotkey.strip():
        raise ValueError("no key set")
    mods: Set[str] = set()
    main: Optional[int] = None
    for raw in hotkey.split("+"):
        part = raw.strip().lower()
        if not part:
            raise ValueError("empty part")
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1]
            if name in _MODIFIERS:
                mods.add(_MODIFIERS[name])
                continue
            if name.isdigit():
                vk = int(name)
            else:
                key = getattr(Key, name, None)
                if key is None or key.value.vk is None:
                    raise ValueError(f"unknown key <{name}>")
                vk = key.value.vk
        elif len(part) == 1:
            vk = _char_vk(part)
            if vk is None:
                raise ValueError(f"'{part}' is not on this keyboard")
        else:
            raise ValueError(f"'{part}' should be written as <{part}>")
        if main is not None:
            raise ValueError("only one non-modifier key is allowed")
        main = vk
    if main is None:
        raise ValueError("a modifier needs another key with it")
    return frozenset(mods), main


def hotkey_error(hotkey: str) -> Optional[str]:
    """None if ``hotkey`` can be used, otherwise a short reason."""
    try:
        parse(hotkey)
    except ValueError as exc:
        return str(exc).capitalize()
    return None


def same_hotkey(a: str, b: str) -> bool:
    """Whether two hotkey strings mean the same key combination."""
    try:
        return parse(a) == parse(b)
    except ValueError:
        return False


class HotkeyManager:
    """Runs one keyboard listener and calls back on matching combinations.

    Callbacks run on the listener thread; hand them to the UI thread with a
    queued Qt signal.
    """

    def __init__(self) -> None:
        self._bindings: Dict[str, Callable] = {}
        self._combos: Dict[Combo, Callable] = {}
        self._listener: Optional[keyboard.Listener] = None
        self._mods: Set[str] = set()
        self._down: Set[int] = set()
        # Hotkeys that could not be registered, with the reason.
        self.errors: List[str] = []

    # ------------------------------------------------------------------

    def set_bindings(self, bindings: Dict[str, Callable]) -> None:
        """Replace all bindings at once (one listener restart)."""
        self._bindings = {hk: cb for hk, cb in bindings.items() if hk}
        self._restart()

    def register(self, hotkey: str, callback: Callable) -> None:
        self._bindings[hotkey] = callback
        self._restart()

    def unregister(self, hotkey: str) -> None:
        self._bindings.pop(hotkey, None)
        self._restart()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._mods.clear()
        self._down.clear()

    # ------------------------------------------------------------------

    def _restart(self) -> None:
        """(Re)start listening with every *valid* binding; invalid ones are
        reported in ``errors`` instead of disabling the rest."""
        self.stop()
        self.errors = []
        self._combos = {}
        for hk, cb in self._bindings.items():
            try:
                self._combos[parse(hk)] = cb
            except ValueError as exc:
                self.errors.append(f"{hk}: {exc}")
        if not self._combos:
            return
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    @staticmethod
    def _identify(key) -> Tuple[Optional[str], Optional[int]]:
        """(modifier name, None) or (None, virtual key code)."""
        if isinstance(key, Key):
            if key.name in _MODIFIERS:
                return _MODIFIERS[key.name], None
            return None, key.value.vk
        if isinstance(key, KeyCode):
            return None, key.vk
        return None, None

    def _on_press(self, key, injected: bool = False) -> None:
        if injected:
            # Input synthesised by AMT's own playback or clicker (or another
            # program) must not trigger hotkeys: a macro containing an F9
            # press would otherwise toggle recording while it plays.
            return
        mod, vk = self._identify(key)
        if mod:
            self._mods.add(mod)
            return
        if vk is None or vk in self._down:     # unknown, or auto-repeat
            return
        self._down.add(vk)
        cb = self._combos.get((frozenset(self._mods), vk))
        if cb is not None:
            cb()

    def _on_release(self, key, injected: bool = False) -> None:
        mod, vk = self._identify(key)
        if mod:
            self._mods.discard(mod)
        elif vk is not None:
            self._down.discard(vk)
