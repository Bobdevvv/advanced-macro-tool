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

A hotkey belongs to AMT: the key is kept from the program that has focus
(otherwise F7 also toggles caret browsing in browsers and F10 opens menu
bars).  Only the exact bound combination is kept, from its press to its
release; modifier keys, other combinations and simulated input always pass.
Matching therefore happens inside the keyboard hook's filter, the only place
an event can still be stopped, and keys that type text can only be hotkeys
together with Ctrl, Alt or Win.
"""
from __future__ import annotations

import ctypes
import threading
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from pynput import keyboard
from pynput.keyboard import Key

_MODIFIERS: Dict[str, str] = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}

Combo = Tuple[FrozenSet[str], int]        # (modifiers, virtual key code)


# Modifier keys by virtual key code (generic, left and right variants).
_MOD_VKS: Dict[int, str] = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "cmd", 0x5C: "cmd",
}
# Keys that type text (or move through it).  On their own they cannot be a
# hotkey, because a hotkey is kept from every other program.
_TYPING_VKS = frozenset(
    [0x08, 0x09, 0x0D, 0x20, 0xE2]           # backspace, tab, enter, space, <>
    + list(range(0x30, 0x3A))                 # 0-9
    + list(range(0x41, 0x5B))                 # A-Z
    + list(range(0x60, 0x70))                 # number pad
    + list(range(0xBA, 0xC1))                 # ; = , - . / `
    + list(range(0xDB, 0xE0))                 # [ backslash ] ' and OEM_8
)
_COMMAND_MODS = frozenset({"ctrl", "alt", "cmd"})

_WM_KEYDOWN, _WM_SYSKEYDOWN = 0x0100, 0x0104
_LLKHF_INJECTED, _LLKHF_LOWER_IL_INJECTED = 0x10, 0x02
_VK_MASK = 0xE8          # unassigned key code, used to mask a lone Alt/Win tap


def _vk_key_scan(ch: str) -> int:
    # Own prototype: pynput declares user32.VkKeyScanW for its own use, and
    # calling the shared one with the wrong argument type raises.
    fn = ctypes.WINFUNCTYPE(ctypes.c_short, ctypes.c_wchar)(
        ("VkKeyScanW", ctypes.windll.user32))
    return fn(ch)


def _char_vk(ch: str) -> Optional[int]:
    """Virtual key of the key that types ``ch`` on the current layout."""
    if ch.isascii() and ch.isalnum():
        return ord(ch.upper())            # VK codes of A–Z / 0–9 are their ASCII
    try:
        res = _vk_key_scan(ch)
    except (AttributeError, OSError, ctypes.ArgumentError):
        return None
    return None if res == -1 or (res & 0xFF) == 0xFF else res & 0xFF


def _key_is_down(vk: int) -> bool:
    """Whether Windows currently sees ``vk`` as held."""
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except (AttributeError, OSError):
        return True


def _send_mask_key() -> None:
    """Tap an unassigned key, so the focused program does not read the Alt or
    Win the user is holding as a lone tap (menu bar, Start menu) once the
    hotkey's own key has been kept from it."""
    try:
        send = ctypes.windll.user32.keybd_event
        send(_VK_MASK, 0, 0, 0)
        send(_VK_MASK, 0, 0x0002, 0)              # KEYEVENTF_KEYUP
    except (AttributeError, OSError):
        pass


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
    if main in _TYPING_VKS and not mods & _COMMAND_MODS:
        raise ValueError("this key types text, so add Ctrl, Alt or Win to it; "
                         "on its own it would stop working for typing")
    return frozenset(mods), main


def hotkey_error(hotkey: str) -> Optional[str]:
    """None if ``hotkey`` can be used, otherwise a short reason."""
    try:
        parse(hotkey)
    except ValueError as exc:
        msg = str(exc)
        return msg[:1].upper() + msg[1:]
    return None


def same_hotkey(a: str, b: str) -> bool:
    """Whether two hotkey strings mean the same key combination."""
    try:
        return parse(a) == parse(b)
    except ValueError:
        return False


class HotkeyManager:
    """Runs one keyboard hook and calls back on matching combinations.

    Callbacks run on the hook's thread and must return quickly (Windows
    drops a keyboard hook that keeps it waiting); hand them to the UI thread
    with a queued Qt signal.
    """

    def __init__(self) -> None:
        self._bindings: Dict[str, Callable] = {}
        self._combos: Dict[Combo, Callable] = {}
        self._listener: Optional[keyboard.Listener] = None
        self._mod_vks: Set[int] = set()      # modifier keys physically held
        self._down: Set[int] = set()         # other keys physically held
        self._kept: Set[int] = set()         # hotkey keys kept until released
        self.paused = False
        # Hotkeys that could not be registered, with the reason.
        self.errors: List[str] = []
        # Replaceable by tests (they have no real keyboard).
        self._is_down: Callable[[int], bool] = _key_is_down
        self._send_mask: Callable[[], None] = (
            lambda: threading.Thread(target=_send_mask_key, daemon=True).start())

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

    def pause(self) -> None:
        """Let every key through and fire nothing (while binding a hotkey)."""
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._mod_vks.clear()
        self._down.clear()
        self._kept.clear()

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
        self._listener = keyboard.Listener(win32_event_filter=self._filter)
        self._listener.daemon = True
        self._listener.start()

    def _filter(self, msg: int, data) -> bool:
        """pynput's hook filter: sees every key event before any program.

        Returns False because nothing else needs pynput's callbacks; keeping
        a key from other programs is ``suppress_event``, which raises.
        """
        injected = bool(data.flags & (_LLKHF_INJECTED | _LLKHF_LOWER_IL_INJECTED))
        down = msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
        if self.handle_key(data.vkCode, down, injected) and self._listener:
            self._listener.suppress_event()
        return False

    def handle_key(self, vk: int, down: bool, injected: bool) -> bool:
        """Track one key event and fire a hotkey if it completes one.

        Returns True when the event must be kept from other programs.
        """
        if injected:
            # Input synthesised by AMT's own playback or clicker (or another
            # program) neither triggers nor is blocked, and does not count
            # as held: a macro holding Ctrl must not stop F8 from matching.
            return False
        mod = _MOD_VKS.get(vk)
        if mod:
            if down:
                self._mod_vks.add(vk)
            else:
                self._mod_vks.discard(vk)
            return False                       # modifiers always pass
        if not down:
            self._down.discard(vk)
            if vk in self._kept:
                self._kept.discard(vk)
                return True                    # the release of a kept press
            return False
        if vk in self._kept:
            return True                        # auto-repeat of a hotkey
        if vk in self._down:
            return False                       # auto-repeat of another key
        self._down.add(vk)
        if self.paused:
            return False
        # A key-up Windows never delivered (UAC prompt, Ctrl+Alt+Del) must
        # not leave a modifier "held" forever.
        self._mod_vks = {m for m in self._mod_vks if self._is_down(m)}
        mods = frozenset(_MOD_VKS[m] for m in self._mod_vks)
        cb = self._combos.get((mods, vk))
        if cb is None:
            return False
        self._kept.add(vk)
        if mods & {"alt", "cmd"}:
            self._send_mask()
        cb()
        return True
