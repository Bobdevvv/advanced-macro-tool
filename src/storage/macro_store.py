"""
Macro files on disk.

Every write goes through this class, and it guarantees three things:

* **No accidental overwrite.**  Saving under a name that is already taken
  gets a free name ("login (2)") unless the caller explicitly asks to
  overwrite; renaming onto another macro's name is refused.
* **Valid Windows file names.**  Illegal characters, reserved device names
  (CON, NUL, COM1 …) and trailing dots/spaces are cleaned up, so a save can
  never silently go nowhere.
* **Atomic writes** (see Macro.save): a crash mid-write keeps the old file.

File names are compared case-insensitively, like Windows does.
"""
from __future__ import annotations

import glob
import json
import os
import re
import uuid
from typing import List

from src.models.macro import Macro, MacroFormatError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul",
             *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_MAX_STEM = 100


def safe_stem(name: str) -> str:
    """A file-name stem that Windows accepts for any macro name."""
    stem = _ILLEGAL.sub("_", name).strip().rstrip(". ")
    if not stem:
        stem = "untitled"
    if stem.split(".")[0].lower() in _RESERVED:
        stem = "_" + stem
    return stem[:_MAX_STEM].rstrip(". ") or "untitled"


class MacroExistsError(FileExistsError):
    """Another macro already uses the requested name."""


class MacroStore:
    """Persists Macro objects as JSON files in a directory."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def path_for(self, filename: str) -> str:
        return os.path.join(self.directory, filename)

    def exists(self, filename: str) -> bool:
        return os.path.exists(self.path_for(filename))

    def free_name(self, name: str) -> str:
        """``name`` if no macro uses it yet, otherwise ``name (2)``, ``(3)``…"""
        if not self.exists(safe_stem(name) + ".json"):
            return name
        n = 2
        while self.exists(safe_stem(f"{name} ({n})") + ".json"):
            n += 1
        return f"{name} ({n})"

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def save(self, macro: Macro, overwrite: bool = False) -> str:
        """Save ``macro`` and return its file name.

        Without ``overwrite`` a taken name is never replaced: the macro is
        renamed to the next free name first (and ``macro.name`` updated).
        """
        if not overwrite:
            macro.name = self.free_name(macro.name)
        filename = safe_stem(macro.name) + ".json"
        macro.save(self.path_for(filename))
        return filename

    def save_to(self, macro: Macro, filename: str) -> None:
        """Overwrite one specific, existing macro file (saving an edit of it)."""
        macro.save(self.path_for(filename))

    def load(self, filename: str) -> Macro:
        return Macro.load(self.path_for(filename))

    def delete(self, filename: str) -> None:
        path = self.path_for(filename)
        if os.path.exists(path):
            os.remove(path)

    def rename(self, old_filename: str, new_name: str) -> str:
        """Rename a macro (file and stored name); returns the new file name.

        Raises MacroExistsError if a *different* macro already has the name.
        A change in letter case only ("test" → "Test") is handled even though
        Windows sees both as the same file.
        """
        macro = self.load(old_filename)
        new_filename = safe_stem(new_name) + ".json"
        old_path, new_path = self.path_for(old_filename), self.path_for(new_filename)
        same_file = old_filename.casefold() == new_filename.casefold()
        if not same_file and os.path.exists(new_path):
            raise MacroExistsError(f"A macro named '{new_name}' already exists.")

        macro.name = new_name
        if same_file:
            macro.save(old_path)
            if old_filename != new_filename:
                # Case-only change: go via a temporary name so the file's
                # on-disk spelling actually changes.
                tmp = self.path_for(f".rename-{uuid.uuid4().hex}.json")
                os.replace(old_path, tmp)
                os.replace(tmp, new_path)
        else:
            macro.save(new_path)
            os.remove(old_path)
        return new_filename

    def list_files(self) -> List[str]:
        pattern = os.path.join(self.directory, "*.json")
        names = [os.path.basename(p) for p in glob.glob(pattern)]
        return sorted((n for n in names if not n.startswith(".")), key=str.casefold)

    def get_metadata(self, filename: str) -> dict:
        """Name, created_at and event count without building a Macro.

        A broken file is reported with ``"error"`` instead of raising, so one
        bad file cannot hide the rest of the library.
        """
        stem = os.path.splitext(filename)[0]
        try:
            with open(self.path_for(filename), encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise MacroFormatError("not a macro")
            events = data.get("events", [])
            return {
                "name":        str(data.get("name") or stem),
                "created_at":  float(data.get("created_at", 0.0) or 0.0),
                "event_count": len(events) if isinstance(events, list) else 0,
                "error":       None,
            }
        except (OSError, ValueError, TypeError) as exc:
            return {"name": stem, "created_at": 0.0, "event_count": 0,
                    "error": str(exc) or type(exc).__name__}

    # Kept for API compatibility; not used by the app.
    def load_all(self) -> List[Macro]:
        out = []
        for f in self.list_files():
            try:
                out.append(self.load(f))
            except (OSError, ValueError):
                pass
        return out
