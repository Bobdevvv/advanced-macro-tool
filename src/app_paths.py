"""
Where AMT keeps its files.

Everything lives under one folder, ``Documents\\AdvancedMacroTool`` by
default.  The ``AMT_HOME`` environment variable points it somewhere else,
which is how the test suite runs without ever touching the real macros and
settings.

Naming rule: folders are called ``AdvancedMacroTool`` (the data folder, the
repository), files are called ``AMT``/``amt`` (``AMT.exe``, ``amt.log``,
``amt.lock``, ``amt.ico``).

Versions before 1.0 used ``Documents\\MacroTool``; :func:`migrate_legacy_home`
moves that folder to the new name once, on start-up.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

from src import brand

LEGACY_DIR_NAME = "MacroTool"


def resource_dir() -> str:
    """Folder holding the bundled files (assets/, docs/).

    The repository root when run from source; PyInstaller's unpack folder
    (sys._MEIPASS) inside the .exe.
    """
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))


def icon_file() -> str:
    return os.path.join(resource_dir(), "assets", "amt.ico")


def documents_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents")


def _default_home() -> str:
    return os.path.join(documents_dir(), brand.DIR_NAME)


def _legacy_home() -> str:
    return os.path.join(documents_dir(), LEGACY_DIR_NAME)


def home() -> str:
    base = os.environ.get("AMT_HOME")
    if not base:
        base = _default_home()
        # Migration not done yet (the move failed, e.g. an old copy of the
        # app still had the folder open): keep using the old folder rather
        # than starting with an empty library.
        if not os.path.exists(base) and os.path.isdir(_legacy_home()):
            return _legacy_home()
    os.makedirs(base, exist_ok=True)
    return base


def migrate_legacy_home() -> Optional[str]:
    """Rename ``Documents\\MacroTool`` to ``Documents\\AdvancedMacroTool``.

    Runs once: only when the old folder exists and the new one does not.
    The move is a single rename, so macros are never copied or half-moved.
    A custom macro folder inside the old one is updated in settings.json.
    Returns the new folder when something was moved, otherwise None.
    """
    if os.environ.get("AMT_HOME"):
        return None
    old, new = _legacy_home(), _default_home()
    if not os.path.isdir(old) or os.path.exists(new):
        return None
    try:
        os.rename(old, new)
    except OSError:
        return None                 # home() keeps using the old folder
    _rebase_macro_dir(os.path.join(new, "settings.json"), old, new)
    return new


def _rebase_macro_dir(settings_path: str, old: str, new: str) -> None:
    try:
        with open(settings_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return
    path = cfg.get("macro_dir") if isinstance(cfg, dict) else None
    if not isinstance(path, str) or not path:
        return
    norm, root = os.path.normcase(os.path.normpath(path)), os.path.normcase(old)
    if norm != root and not norm.startswith(root + os.sep):
        return
    cfg["macro_dir"] = new + os.path.normpath(path)[len(old):]
    tmp = settings_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, settings_path)
    except OSError:
        pass


def settings_file() -> str:
    return os.path.join(home(), "settings.json")


def default_macro_dir() -> str:
    path = os.path.join(home(), "macros")
    os.makedirs(path, exist_ok=True)
    return path


def log_dir() -> str:
    path = os.path.join(home(), "logs")
    os.makedirs(path, exist_ok=True)
    return path
