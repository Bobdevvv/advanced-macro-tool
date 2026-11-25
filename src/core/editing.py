"""
Macro editing operations (the timeline editor's engine, free of Qt).

Every function takes a list of events and returns a *new* list; nothing is
modified in place, so the editor can keep earlier lists for undo.

**Integrity rule.**  A macro must never contain a release without its
press, and after an edit every press must still be released.  Otherwise a
cut could leave a key or button held down during playback.  All operations
end with ``normalize``, and ``cut_range`` releases keys that were held
across the cut at the cut point.

**Gestures.**  Users think in actions, not raw events: a held key (press,
Windows' auto-repeat presses, release), a click (press + release), a burst
of scrolling, a stretch of mouse movement.  ``gestures`` groups events that
way; selecting or deleting a gesture always covers all of its events.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from src.models.macro import MacroEvent

Events = List[MacroEvent]

# Consecutive scroll events / mouse moves closer than this form one gesture.
SCROLL_GROUP_S = 0.30
MOVE_GROUP_S = 0.50
# Spacing used when building key taps and typed text from scratch.
TAP_STEP_S = 0.03
# Never let a full undo history grow without bound.
MAX_EVENTS = 2_000_000


class EditError(ValueError):
    """An edit that cannot be applied, with a message for the user."""


# ---------------------------------------------------------------------------
# Identity of keys and buttons
# ---------------------------------------------------------------------------

def key_identity(ev: MacroEvent):
    """Which physical key an event belongs to, for pairing press/release.

    Uses the virtual key code where possible, so that old recordings (where
    Ctrl+C was stored as "\\x03" on press but "c" on release) still pair up.
    """
    if ev.vk is not None:
        return ev.vk
    k = ev.key or ""
    if len(k) == 1:
        code = ord(k)
        if 1 <= code <= 26:
            return 0x40 + code                  # control char -> letter key
        if k.isascii() and k.isalnum():
            return ord(k.upper())
    if k.startswith("vk:"):
        try:
            return int(k[3:])
        except ValueError:
            pass
    return k


def _identity(ev: MacroEvent):
    if ev.type in ("key_press", "key_release"):
        return ("key", key_identity(ev))
    if ev.type == "mouse_click":
        return ("btn", ev.button or "left")
    return None


def _is_press(ev: MacroEvent) -> bool:
    return ev.type == "key_press" or (ev.type == "mouse_click" and bool(ev.pressed))


def _is_release(ev: MacroEvent) -> bool:
    return ev.type == "key_release" or (ev.type == "mouse_click" and not ev.pressed)


def _release_for(press: MacroEvent, t: float) -> MacroEvent:
    if press.type == "key_press":
        return MacroEvent("key_release", t, key=press.key, vk=press.vk)
    return MacroEvent("mouse_click", t, x=press.x, y=press.y,
                      button=press.button, pressed=False)


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def sort_events(events: Iterable[MacroEvent]) -> Events:
    # Python's sort is stable: events at the same time keep their order.
    return sorted(events, key=lambda e: e.timestamp)


def shift(events: Iterable[MacroEvent], dt: float) -> Events:
    return [dataclasses.replace(e, timestamp=e.timestamp + dt) for e in events]


def duration(events: Sequence[MacroEvent]) -> float:
    return max((e.timestamp for e in events), default=0.0)


def held_at(events: Sequence[MacroEvent], t: float) -> Dict[object, MacroEvent]:
    """Keys/buttons held just before time ``t``: identity -> first press."""
    held: Dict[object, MacroEvent] = {}
    for e in events:
        if e.timestamp >= t:
            break
        ident = _identity(e)
        if ident is None:
            continue
        if _is_press(e):
            held.setdefault(ident, e)
        elif _is_release(e):
            held.pop(ident, None)
    return held


def normalize(events: Iterable[MacroEvent]) -> Events:
    """Sorted, with orphan releases dropped and every press released.

    A press that is never released gets a release at the end of the macro.
    """
    out: Events = []
    held: Dict[object, MacroEvent] = {}
    for e in sort_events(events):
        if e.timestamp < 0:
            e = dataclasses.replace(e, timestamp=0.0)
        ident = _identity(e)
        if ident is not None:
            if _is_press(e):
                held.setdefault(ident, e)
            elif _is_release(e):
                if ident not in held:
                    continue                     # release without a press
                del held[ident]
        out.append(e)
    end = duration(out)
    out.extend(_release_for(p, end) for p in held.values())
    return out


# ---------------------------------------------------------------------------
# Gestures
# ---------------------------------------------------------------------------

@dataclass
class Gesture:
    kind: str                 # "key" | "click" | "scroll" | "move"
    start: float
    end: float
    indices: List[int] = field(default_factory=list)
    label: str = ""

    @property
    def track(self) -> str:
        return {"key": "keys", "click": "clicks", "scroll": "clicks",
                "move": "moves"}[self.kind]


_NAMED = {"ctrl_l": "Ctrl", "ctrl_r": "Ctrl", "ctrl": "Ctrl", "shift": "Shift",
          "shift_l": "Shift", "shift_r": "Shift", "alt_l": "Alt", "alt_r": "Alt",
          "alt": "Alt", "alt_gr": "AltGr", "cmd": "Win", "cmd_l": "Win",
          "cmd_r": "Win", "space": "Space", "enter": "Enter", "backspace": "Bksp",
          "tab": "Tab", "esc": "Esc", "delete": "Del", "caps_lock": "Caps",
          "page_up": "PgUp", "page_down": "PgDn"}


def key_label(ev: MacroEvent) -> str:
    """Short readable name of the key an event presses."""
    k = ev.key or ""
    if k.startswith("Key."):
        name = k[4:]
        return _NAMED.get(name, name.replace("_", " ").title())
    ident = key_identity(ev)
    if isinstance(ident, int) and (0x30 <= ident <= 0x39 or 0x41 <= ident <= 0x5A):
        return chr(ident)
    if len(k) == 1 and k.isprintable():
        return k
    if isinstance(ident, int):
        return f"Key {ident}"
    return k or "?"


def gestures(events: Sequence[MacroEvent]) -> List[Gesture]:
    """Group events into user-level actions (see module docstring)."""
    out: List[Gesture] = []
    open_: Dict[object, Gesture] = {}
    scroll: Optional[Gesture] = None
    move: Optional[Gesture] = None
    last_t = duration(events)

    for i, e in enumerate(events):
        t = e.timestamp
        if e.type == "mouse_move":
            if move is None or t - move.end > MOVE_GROUP_S:
                move = Gesture("move", t, t, label="Mouse movement")
                out.append(move)
            move.end = t
            move.indices.append(i)
            continue
        if e.type == "mouse_scroll":
            if scroll is None or t - scroll.end > SCROLL_GROUP_S:
                scroll = Gesture("scroll", t, t, label="Scroll")
                out.append(scroll)
            scroll.end = t
            scroll.indices.append(i)
            continue
        if e.type == "mouse_click":
            move = None                      # a click ends a movement stretch
        ident = _identity(e)
        if ident is None:
            continue
        if _is_press(e):
            g = open_.get(ident)
            if g is None:
                kind = "key" if e.type == "key_press" else "click"
                label = key_label(e) if kind == "key" else \
                    f"{(e.button or 'left').title()} click"
                g = Gesture(kind, t, t, label=label)
                open_[ident] = g
                out.append(g)
            g.indices.append(i)
            g.end = t
        else:
            g = open_.pop(ident, None)
            if g is None:
                kind = "key" if e.type == "key_release" else "click"
                g = Gesture(kind, t, t, label="release")
                out.append(g)
            g.indices.append(i)
            g.end = t
    for g in open_.values():                 # never released: runs to the end
        g.end = last_t
    out.sort(key=lambda g: (g.start, g.kind))
    return out


def gesture_indices(gs: Iterable[Gesture]) -> Set[int]:
    return {i for g in gs for i in g.indices}


# ---------------------------------------------------------------------------
# Clipboard type
# ---------------------------------------------------------------------------

@dataclass
class Clip:
    """Events copied out of a macro, with times relative to 0.

    ``length`` is the span that was copied, which can be longer than the
    last event (a copied pause still takes up time when pasted).
    """
    events: Events
    length: float


# ---------------------------------------------------------------------------
# Range operations (time ranges, "ripple" editing)
# ---------------------------------------------------------------------------

def _check_range(a: float, b: float) -> Tuple[float, float]:
    a, b = max(0.0, min(a, b)), max(0.0, max(a, b))
    if b - a <= 0:
        raise EditError("Select a stretch of time first.")
    return a, b


def copy_range(events: Sequence[MacroEvent], a: float, b: float) -> Clip:
    a, b = _check_range(a, b)
    inside = [e for e in events if a <= e.timestamp < b]
    # Keys held when the range starts are part of what the user sees there:
    # copying the middle of a Ctrl hold copies a Ctrl press at the start.
    held = held_at(events, a)
    starts = [dataclasses.replace(p, timestamp=a) for p in held.values()]
    clip_events = normalize(shift(starts + inside, -a))
    # Releases added by normalize sit at the last event; hold them to the end.
    return Clip(clip_events, b - a)


def cut_range(events: Sequence[MacroEvent], a: float, b: float) -> Tuple[Events, Clip]:
    """Remove ``[a, b)`` and close the gap.  Returns (new events, clip)."""
    a, b = _check_range(a, b)
    clip = copy_range(events, a, b)
    before = [e for e in events if e.timestamp < a]
    after = [e for e in events if e.timestamp >= b]

    # Keys held at ``a``: if anything of theirs remains after the cut (more
    # auto-repeat presses, or the release) the hold simply continues.  If
    # their release fell inside the cut and nothing remains, release them at
    # the cut point, or they would stay held for the rest of the macro.
    held = held_at(events, a)
    continues = {_identity(e) for e in after} & set(held)
    fixes = [_release_for(p, a) for ident, p in held.items() if ident not in continues]
    return normalize(before + fixes + shift(after, -(b - a))), clip


def paste(events: Sequence[MacroEvent], clip: Clip, t: float) -> Events:
    """Insert a clip at time ``t``, pushing everything from ``t`` onward later."""
    t = max(0.0, t)
    length = max(clip.length, duration(clip.events))
    if len(events) + len(clip.events) > MAX_EVENTS:
        raise EditError(f"The macro would exceed {MAX_EVENTS:,} events.")
    before = [e for e in events if e.timestamp < t]
    after = shift([e for e in events if e.timestamp >= t], length)
    return normalize(before + shift(clip.events, t) + after)


def move_range(events: Sequence[MacroEvent], a: float, b: float, to: float) -> Events:
    """Move ``[a, b)`` so it starts at ``to`` (a time in the current macro)."""
    a, b = _check_range(a, b)
    if a <= to <= b:
        return list(events)
    rest, clip = cut_range(events, a, b)
    target = to if to < a else to - (b - a)
    return paste(rest, clip, target)


def insert_gap(events: Sequence[MacroEvent], t: float, seconds: float) -> Events:
    if seconds <= 0:
        raise EditError("The wait must be longer than zero.")
    return paste(events, Clip([], seconds), t)


def delete_range(events: Sequence[MacroEvent], a: float, b: float) -> Events:
    return cut_range(events, a, b)[0]


# ---------------------------------------------------------------------------
# Gesture operations
# ---------------------------------------------------------------------------

def delete_gestures(events: Sequence[MacroEvent], gs: Iterable[Gesture]) -> Events:
    drop = gesture_indices(gs)
    return normalize(e for i, e in enumerate(events) if i not in drop)


def shift_gestures(events: Sequence[MacroEvent], gs: Iterable[Gesture], dt: float) -> Events:
    """Move whole gestures in time (no rippling); never before time 0."""
    gs = list(gs)
    idx = gesture_indices(gs)
    if not idx:
        return list(events)
    earliest = min(events[i].timestamp for i in idx)
    dt = max(dt, -earliest)
    return normalize(dataclasses.replace(e, timestamp=e.timestamp + dt) if i in idx else e
                     for i, e in enumerate(events))


def copy_gestures(events: Sequence[MacroEvent], gs: Iterable[Gesture]) -> Clip:
    idx = sorted(gesture_indices(gs))
    if not idx:
        raise EditError("Nothing selected.")
    picked = [events[i] for i in idx]
    t0 = picked[0].timestamp
    clip_events = normalize(shift(picked, -t0))
    return Clip(clip_events, duration(clip_events))


def set_click_position(events: Sequence[MacroEvent], g: Gesture, x: int, y: int) -> Events:
    if g.kind != "click":
        raise EditError("Only clicks have a position.")
    idx = set(g.indices)
    return [dataclasses.replace(e, x=x, y=y) if i in idx else e for i, e in enumerate(events)]


def set_gesture_length(events: Sequence[MacroEvent], g: Gesture, seconds: float) -> Events:
    """Change how long a key or click is held (moves its release)."""
    if g.kind not in ("key", "click"):
        raise EditError("Only key holds and clicks have a length.")
    seconds = max(0.0, seconds)
    last = g.indices[-1]
    if not _is_release(events[last]):
        raise EditError("This action has no release to move.")
    repeats = [i for i in g.indices[1:-1]]
    new_end = g.start + seconds
    out = []
    for i, e in enumerate(events):
        if i == last:
            e = dataclasses.replace(e, timestamp=new_end)
        elif i in repeats and e.timestamp > new_end:
            continue                         # auto-repeats past the new end
        out.append(e)
    return normalize(out)


# ---------------------------------------------------------------------------
# Optimising
# ---------------------------------------------------------------------------

def shorten_pauses(events: Sequence[MacroEvent], longer_than: float, to: float,
                   a: Optional[float] = None, b: Optional[float] = None) -> Events:
    """Shrink every pause longer than ``longer_than`` to ``to`` seconds.

    Includes the idle time before the first event.  With ``a``/``b`` only
    pauses that start inside that range are changed.
    """
    if to < 0 or longer_than < 0:
        raise EditError("Times cannot be negative.")
    if to > longer_than:
        raise EditError("The new pause must not be longer than the limit.")
    src = sort_events(events)
    out: Events = []
    prev_old = prev_new = 0.0
    for e in src:
        gap = e.timestamp - prev_old
        in_scope = (a is None or prev_old >= a) and (b is None or prev_old < b)
        if in_scope and gap > longer_than:
            gap = to
        new_t = prev_new + gap
        out.append(dataclasses.replace(e, timestamp=new_t))
        prev_old, prev_new = e.timestamp, new_t
    return normalize(out)


def remove_mouse_moves(events: Sequence[MacroEvent], a: Optional[float] = None,
                       b: Optional[float] = None) -> Events:
    def keep(e):
        if e.type != "mouse_move":
            return True
        return not ((a is None or e.timestamp >= a) and (b is None or e.timestamp < b))
    return normalize(e for e in events if keep(e))


# ---------------------------------------------------------------------------
# Building from scratch
# ---------------------------------------------------------------------------

def key_combo_events(hotkey: str) -> Clip:
    """Press and release a combination like ``<ctrl>+c`` (a quick tap)."""
    from src.core.hotkey_manager import parse
    try:
        mods, vk = parse(hotkey)
    except ValueError as exc:
        raise EditError(f"Not a valid key combination: {exc}") from exc
    names = {"ctrl": "Key.ctrl_l", "shift": "Key.shift", "alt": "Key.alt_l",
             "cmd": "Key.cmd"}
    order = [m for m in ("ctrl", "alt", "shift", "cmd") if m in mods]
    special = {k.value.vk: f"Key.{k.name}" for k in _special_keys()}
    main_key = special.get(vk) or _vk_name(vk)
    main_vk = None if main_key.startswith("Key.") else vk
    t, ev = 0.0, []
    for m in order:
        ev.append(MacroEvent("key_press", t, key=names[m]))
        t += TAP_STEP_S
    ev.append(MacroEvent("key_press", t, key=main_key, vk=main_vk))
    t += TAP_STEP_S
    ev.append(MacroEvent("key_release", t, key=main_key, vk=main_vk))
    for m in reversed(order):
        t += TAP_STEP_S
        ev.append(MacroEvent("key_release", t, key=names[m]))
    return Clip(ev, t + TAP_STEP_S)


def _special_keys():
    from pynput.keyboard import Key
    return [k for k in Key if k.value.vk is not None]


def _vk_name(vk: int) -> str:
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    return f"vk:{vk}"


def text_events(text: str) -> Clip:
    """Type ``text`` character by character (by character, not key code, so
    any letter or symbol is typed as written whatever the layout)."""
    if not text:
        raise EditError("Type the text to insert.")
    t, ev = 0.0, []
    for ch in text:
        if ch == "\n":
            ev.append(MacroEvent("key_press", t, key="Key.enter"))
            ev.append(MacroEvent("key_release", t + TAP_STEP_S / 2, key="Key.enter"))
        elif ch == "\t":
            ev.append(MacroEvent("key_press", t, key="Key.tab"))
            ev.append(MacroEvent("key_release", t + TAP_STEP_S / 2, key="Key.tab"))
        else:
            ev.append(MacroEvent("key_press", t, key=ch))
            ev.append(MacroEvent("key_release", t + TAP_STEP_S / 2, key=ch))
        t += TAP_STEP_S
    return Clip(ev, t)


def repeat(clip: Clip, times: int) -> Clip:
    times = max(1, int(times))
    if len(clip.events) * times > MAX_EVENTS:
        raise EditError(f"That would be {len(clip.events) * times:,} events; "
                        f"the limit is {MAX_EVENTS:,}.")
    out: Events = []
    for n in range(times):
        out.extend(shift(clip.events, n * clip.length))
    return Clip(out, clip.length * times)
