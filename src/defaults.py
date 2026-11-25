"""
Default settings, in one place.

Everything that needs a default hotkey reads it from here: the settings
file, the Settings page, the sidebar, the page hints and the docs tests.

The hotkeys follow the sidebar from top to bottom (Record, Player & Library,
Composer, Auto Click) on F7 to F10.  That range avoids the keys browsers use
most (F5 reload, F6 address bar, F11 full screen, F12 developer tools).
"""
from __future__ import annotations

from typing import Dict

DEFAULT_HOTKEYS = {
    "hotkey_record":      "<f7>",
    "hotkey_play":        "<f8>",
    "hotkey_test":        "<f9>",
    "hotkey_autoclicker": "<f10>",
}

# The defaults each earlier settings version shipped with.  A saved hotkey
# that still has the default of the version it was saved by is moved to the
# current default; hotkeys the user chose are never touched.
PREVIOUS_DEFAULTS: Dict[int, Dict[str, str]] = {
    1: {"hotkey_record": "<f9>", "hotkey_play": "<f10>",
        "hotkey_autoclicker": "<f11>", "hotkey_test": "<f8>"},
    2: {"hotkey_record": "<f9>", "hotkey_play": "<f10>",
        "hotkey_autoclicker": "<f8>", "hotkey_test": "<f7>"},
}

SETTINGS_VERSION = 3


def migrate_hotkeys(cfg: dict) -> bool:
    """Bring hotkeys saved by an older version up to the current defaults.

    Returns True if any hotkey changed.  All hotkeys that still have their
    old default move *together* (the change is a rotation, e.g. Record
    F9 -> F7 while Test play F7 -> F9, so moving them one by one could
    collide).  If the result would put two actions on one key, because the
    user chose one of the new keys for something else, nothing is moved.
    """
    try:
        version = int(cfg.get("settings_version", 1))
    except (TypeError, ValueError):
        version = 1
    if version >= SETTINGS_VERSION:
        return False
    old = PREVIOUS_DEFAULTS.get(version, PREVIOUS_DEFAULTS[1])
    moving = [k for k in DEFAULT_HOTKEYS if k in old and cfg.get(k, old[k]) == old[k]]
    proposed = {k: cfg.get(k, DEFAULT_HOTKEYS[k]) for k in DEFAULT_HOTKEYS}
    for k in moving:
        proposed[k] = DEFAULT_HOTKEYS[k]
    cfg["settings_version"] = SETTINGS_VERSION
    values = list(proposed.values())
    if len(values) != len(set(values)):
        return False                     # would clash with a user's choice
    changed = any(cfg.get(k) != v for k, v in proposed.items())
    cfg.update(proposed)
    return changed
