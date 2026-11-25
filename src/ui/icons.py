"""
Theme-aware icons drawn from the Windows icon font.

Windows 10 ships "Segoe MDL2 Assets" and Windows 11 "Segoe Fluent Icons";
both use the same code points.  Icons are rendered to pixmaps in the current
theme's colours, and every widget that receives one is remembered so the
icon can be redrawn when the theme changes.
"""
from __future__ import annotations

import weakref
from typing import Optional

from PyQt6.QtCore import QRectF, Qt, QSize
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel

from src.ui import theme


class G:
    """Glyph code points (Segoe MDL2 Assets / Segoe Fluent Icons)."""
    RECORD   = "\uE7C8"
    LIBRARY  = "\uE8F1"
    PLAY     = "\uE768"
    STOP     = "\uE71A"
    LINK     = "\uE71B"
    MOUSE    = "\uE962"
    SETTINGS = "\uE713"
    ADD      = "\uE710"
    DELETE   = "\uE74D"
    RENAME   = "\uE70F"
    EXPORT   = "\uE72D"
    CLEAR    = "\uE894"
    FOLDER   = "\uE838"
    KEYBOARD = "\uE765"
    TARGET   = "\uE81D"
    SEARCH   = "\uE721"
    EJECT    = "\uE711"
    SAVE     = "\uE74E"
    UNDO     = "\uE7A7"
    OPEN     = "\uE8E5"
    SPARKLE  = "\uE945"
    CHEVRON_DOWN = "\uE70D"
    REDO     = "\uE7A6"
    CUT      = "\uE8C6"
    COPY     = "\uE8C8"
    PASTE    = "\uE77F"
    ZOOM_IN  = "\uE8A3"
    ZOOM_OUT = "\uE71F"
    FIT      = "\uE9A6"
    EDIT     = "\uE932"
    NEW      = "\uE8A5"
    TIMELINE = "\uE81C"
    HELP     = "\uE897"
    IMPORT   = "\uE896"
    INFO     = "\uE946"


_FAMILY: Optional[str] = None


def _family() -> str:
    global _FAMILY
    if _FAMILY is None:
        fams = set(QFontDatabase.families())
        _FAMILY = next(
            (f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams),
            "",
        )
    return _FAMILY


def _pixmap(glyph: str, color: str, size: int) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    dpr = max(dpr, 1.0)
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    if not _family():
        return pm
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont(_family())
    f.setPixelSize(int(size * 0.92))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return pm


def _color(role: str) -> str:
    """A theme token name, or a literal '#rrggbb' colour."""
    return role if role.startswith("#") else theme.palette()[role]


def make(glyph: str, role: str = "text", size: int = 16,
         checked_role: Optional[str] = None) -> QIcon:
    """Build an icon in the current theme.  ``role`` is a theme token."""
    icon = QIcon()
    icon.addPixmap(_pixmap(glyph, _color(role), size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_pixmap(glyph, _color("disabled"), size), QIcon.Mode.Disabled, QIcon.State.Off)
    if checked_role:
        on = _pixmap(glyph, _color(checked_role), size)
        icon.addPixmap(on, QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(on, QIcon.Mode.Active, QIcon.State.On)
    return icon


# widget → (glyph, role, size, checked_role)
_bound: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def bind(widget, glyph: str, role: str = "text", size: int = 16,
         checked_role: Optional[str] = None) -> None:
    """Give a button (or label) an icon that follows theme changes."""
    _bound[widget] = (glyph, role, size, checked_role)
    _apply(widget, glyph, role, size, checked_role)


def _apply(widget, glyph, role, size, checked_role) -> None:
    if isinstance(widget, QAbstractButton):
        widget.setIcon(make(glyph, role, size, checked_role))
        widget.setIconSize(QSize(size, size))
    elif isinstance(widget, QLabel):
        widget.setPixmap(_pixmap(glyph, _color(role), size))


def refresh_all() -> None:
    """Redraw every bound icon; call after the theme changes."""
    for widget, args in list(_bound.items()):
        try:
            _apply(widget, *args)
        except RuntimeError:      # underlying C++ object already deleted
            pass
