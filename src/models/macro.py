from __future__ import annotations
import json
import os
import time
import dataclasses
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class MacroEvent:
    type: str        # mouse_move | mouse_click | mouse_scroll | key_press | key_release
    timestamp: float

    x:       Optional[int]   = None
    y:       Optional[int]   = None
    button:  Optional[str]   = None  # left | right | middle
    pressed: Optional[bool]  = None
    dx:      Optional[int]   = None
    dy:      Optional[int]   = None
    key:     Optional[str]   = None  # readable: "a", "Key.ctrl_l", "vk:67"
    # Windows virtual key code of the physical key.  Playback uses it when
    # present, because the character alone is ambiguous: with Ctrl held the
    # C key reports the character "\x03", which is not the C key at all.
    vk:      Optional[int]   = None

    def to_dict(self) -> dict:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> MacroEvent:
        valid = {f.name for f in dataclasses.fields(cls)}
        ev = cls(**{k: v for k, v in d.items() if k in valid})
        if ev.vk is not None and not isinstance(ev.vk, int):
            ev.vk = None                 # tolerate hand-edited files
        return ev


@dataclass
class Macro:
    name:        str
    events:      List[MacroEvent] = field(default_factory=list)
    created_at:  float            = field(default_factory=time.time)
    description: str              = ""

    def duration(self) -> float:
        return self.events[-1].timestamp if self.events else 0.0

    def event_summary(self) -> dict:
        counts: dict = {}
        for e in self.events:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "created_at":  self.created_at,
            "events":      [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict, fallback_name: str = "Untitled") -> Macro:
        """Build a Macro from parsed JSON, rejecting anything malformed with a
        clear MacroFormatError instead of a KeyError deep in the UI."""
        if not isinstance(d, dict):
            raise MacroFormatError("the file does not contain a macro")
        raw_events = d.get("events", [])
        if not isinstance(raw_events, list):
            raise MacroFormatError("'events' is not a list")
        events: List[MacroEvent] = []
        for i, e in enumerate(raw_events):
            if not isinstance(e, dict) or "type" not in e or "timestamp" not in e:
                raise MacroFormatError(f"event {i + 1} is incomplete")
            try:
                events.append(MacroEvent.from_dict(e))
            except TypeError as exc:
                raise MacroFormatError(f"event {i + 1} is invalid: {exc}") from exc
        events.sort(key=lambda ev: ev.timestamp)   # duration() relies on order
        return cls(
            name=str(d.get("name") or fallback_name),
            description=str(d.get("description", "")),
            created_at=float(d.get("created_at", 0.0) or 0.0),
            events=events,
        )

    def save(self, path: str) -> None:
        """Write atomically: a crash or full disk mid-write can never leave a
        half-written (corrupt) macro behind, the old file stays intact."""
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @classmethod
    def load(cls, path: str) -> Macro:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise MacroFormatError(f"the file is not valid JSON ({exc.msg}, "
                                   f"line {exc.lineno})") from exc
        stem = os.path.splitext(os.path.basename(path))[0]
        return cls.from_dict(data, fallback_name=stem)


class MacroFormatError(ValueError):
    """A macro file exists but its contents are not a valid macro."""
