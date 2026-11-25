"""
Theme engine.

Each theme is a small set of colour tokens.  ``apply_theme()`` turns the
tokens into three things and installs them application-wide:

* a Qt stylesheet (``_TEMPLATE``),
* a QPalette, so widgets the stylesheet does not reach (message boxes,
  context menus, native-ish dialogs) still match,
* a handful of tiny SVG images (switch, chevrons) that a stylesheet cannot
  draw by itself; they are written once per theme to a temp folder.

Widgets opt into styles with object names (``Card``, ``PageTitle`` …) or
dynamic properties (``variant="primary"``, ``tone="danger"`` …), never with
inline colours, so every theme applies everywhere.
"""
from __future__ import annotations

import os
import tempfile
from typing import Dict

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from src import brand
from src.ui.fonts import MONO_STACK, UI_STACK

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
# Token meanings
#   bg            window background (behind the cards)
#   sidebar       navigation rail and status bar
#   surface       cards
#   surface2      raised controls inside cards: buttons, stat tiles
#   input         text fields, lists
#   hover         hover fill
#   border        hairlines between areas
#   border2       control outlines
#   text / muted / faint   three levels of text emphasis
#   accent / accent_hover / on_accent   brand colour and text drawn on it
#   success / danger / warn             status colours

_PALETTES: Dict[str, Dict[str, str]] = {
    "Graphite": {
        "dark": "1",
        "bg": "#111316", "sidebar": "#0c0d10", "surface": "#171a1f",
        "surface2": "#1f232a", "input": "#13161a", "hover": "#252a32",
        "border": "#23272e", "border2": "#323843",
        "text": "#e7e9ed", "muted": "#a8aeb9", "faint": "#898f9a",
        "disabled": "#666e7b",
        "accent": "#4f8cff", "accent_hover": "#6c9fff", "on_accent": "#ffffff",
        "success": "#34c77b", "danger": "#f05656", "warn": "#f2a93b",
    },
    "Midnight": {
        "dark": "1",
        "bg": "#0d1117", "sidebar": "#010409", "surface": "#151b23",
        "surface2": "#1c232d", "input": "#0f141b", "hover": "#232b36",
        "border": "#232a33", "border2": "#353d48",
        "text": "#e6edf3", "muted": "#a7aeb6", "faint": "#888f99",
        "disabled": "#5f6772",
        "accent": "#4493f8", "accent_hover": "#64a6ff", "on_accent": "#ffffff",
        "success": "#3fb950", "danger": "#f85149", "warn": "#d29922",
    },
    # Same tokens as the Bob Terminal site (design-spec: bg #0e0f13,
    # panel #16181f, accent gold #e8b64c, up #2ecc8f, down #f4506b).
    "Terminal": {
        "dark": "1",
        "bg": "#0e0f13", "sidebar": "#16181f", "surface": "#16181f",
        "surface2": "#1d2029", "input": "#111318", "hover": "#252936",
        "border": "#262a35", "border2": "#343a49",
        "text": "#e9eaee", "muted": "#a5abb6", "faint": "#878c97",
        "disabled": "#5f6673",
        "accent": "#e8b64c", "accent_hover": "#f0c66a", "on_accent": "#17130a",
        "success": "#2ecc8f", "danger": "#f4506b", "warn": "#e8b64c",
    },
    "Mocha": {
        "dark": "1",
        "bg": "#1e1e2e", "sidebar": "#181825", "surface": "#24243a",
        "surface2": "#2c2c44", "input": "#1b1b2b", "hover": "#34344e",
        "border": "#2f2f47", "border2": "#45475a",
        "text": "#cdd6f4", "muted": "#b2bad6", "faint": "#949ab3",
        "disabled": "#6c7086",
        "accent": "#cba6f7", "accent_hover": "#d8bcff", "on_accent": "#1e1e2e",
        "success": "#a6e3a1", "danger": "#f38ba8", "warn": "#fab387",
    },
    "Dracula": {
        "dark": "1",
        "bg": "#282a36", "sidebar": "#21222c", "surface": "#2e303e",
        "surface2": "#363948", "input": "#252733", "hover": "#3d4052",
        "border": "#373a4a", "border2": "#4b4f66",
        "text": "#f8f8f2", "muted": "#c6cadb", "faint": "#a0a8c0",
        "disabled": "#7480a8",
        "accent": "#bd93f9", "accent_hover": "#cba8ff", "on_accent": "#21222c",
        "success": "#50fa7b", "danger": "#ff5555", "warn": "#ffb86c",
    },
    "Arctic": {
        "dark": "1",
        "bg": "#2b303b", "sidebar": "#252a33", "surface": "#313744",
        "surface2": "#38404e", "input": "#2a2f3a", "hover": "#404858",
        "border": "#3a4150", "border2": "#4c5568",
        "text": "#eceff4", "muted": "#ced4df", "faint": "#aab1bf",
        "disabled": "#8690a3",
        "accent": "#88c0d0", "accent_hover": "#a0d0de", "on_accent": "#1f242d",
        "success": "#a3be8c", "danger": "#d0707a", "warn": "#ebcb8b",
    },
    "Light": {
        "dark": "0",
        "bg": "#f4f5f7", "sidebar": "#eceef2", "surface": "#ffffff",
        "surface2": "#f4f5f8", "input": "#ffffff", "hover": "#e9ebf0",
        "border": "#e3e6eb", "border2": "#cfd4dc",
        "text": "#1c2130", "muted": "#4b5365", "faint": "#656c7b",
        "disabled": "#8c94a3",
        "accent": "#3b6ef5", "accent_hover": "#2f5fe0", "on_accent": "#ffffff",
        "success": "#1d9a55", "danger": "#d93743", "warn": "#c47a00",
    },
}

# Names used by earlier versions, so an existing settings.json keeps working.
_ALIASES = {"Dark": "Mocha"}

# Terminal matches the Bob Terminal website's palette, so it is the default
# and listed first.
DEFAULT_THEME = "Terminal"
THEME_NAMES   = [DEFAULT_THEME] + [n for n in _PALETTES if n != DEFAULT_THEME]

_current = DEFAULT_THEME


def resolve(name: str | None) -> str:
    """Map any stored theme name to one that exists."""
    name = _ALIASES.get(name or "", name or "")
    return name if name in _PALETTES else DEFAULT_THEME


def palette(name: str | None = None) -> Dict[str, str]:
    """Colour tokens of a theme (the current one by default)."""
    return dict(_PALETTES[resolve(name or _current)])


def current() -> str:
    return _current


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rgba(hex_color: str, alpha: int) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _tokens(name: str) -> Dict[str, str]:
    c = palette(name)
    dark = c["dark"] == "1"
    c.update({
        "font_ui":      UI_STACK,
        "font_mono":    MONO_STACK,
        "accent_soft":  _rgba(c["accent"],  40 if dark else 28),
        "accent_line":  _rgba(c["accent"],  110),
        "sel":          _rgba(c["accent"],  48 if dark else 36),
        "success_soft": _rgba(c["success"], 36 if dark else 30),
        "danger_soft":  _rgba(c["danger"],  38 if dark else 28),
        "danger_line":  _rgba(c["danger"],  110),
        "warn_soft":    _rgba(c["warn"],    36 if dark else 30),
        "warn_line":    _rgba(c["warn"],    100),
        "idle_soft":    _rgba(c["muted"],   34),
    })
    c.update(_write_assets(name, c))
    return c


def _write_assets(name: str, c: Dict[str, str]) -> Dict[str, str]:
    """Write the theme's SVG images and return {token: url-ready path}."""
    folder = os.path.join(tempfile.gettempdir(), brand.DIR_NAME, "ui", name.lower())
    os.makedirs(folder, exist_ok=True)

    def chevron(points: str, color: str) -> str:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
            'viewBox="0 0 10 10"><polyline points="' + points + '" fill="none" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round"/></svg>'
        )

    def switch(track: str, knob: str, on: bool, border: str = "none") -> str:
        cx = 25 if on else 11
        stroke = "" if border == "none" else f' stroke="{border}" stroke-width="1"'
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="22" '
            'viewBox="0 0 36 22">'
            f'<rect x="0.5" y="0.5" width="35" height="21" rx="10.5" fill="{track}"{stroke}/>'
            f'<circle cx="{cx}" cy="11" r="7.5" fill="{knob}"/></svg>'
        )

    files = {
        "img_up":        chevron("2,6.5 5,3.5 8,6.5", c["muted"]),
        "img_down":      chevron("2,3.5 5,6.5 8,3.5", c["muted"]),
        "img_up_dis":    chevron("2,6.5 5,3.5 8,6.5", c["disabled"]),
        "img_down_dis":  chevron("2,3.5 5,6.5 8,3.5", c["disabled"]),
        "img_sw_on":     switch(c["accent"],  c["on_accent"], True),
        "img_sw_off":    switch(c["surface2"], c["muted"], False, c["border2"]),
        "img_sw_on_dis": switch(c["border2"], c["surface"], True),
        "img_sw_off_dis": switch(c["surface"], c["border2"], False, c["border"]),
    }
    out = {}
    for key, svg in files.items():
        path = os.path.join(folder, key + ".svg")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            pass
        out[key] = path.replace("\\", "/")
    return out


def _qpalette(c: Dict[str, str]) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    pairs = {
        R.Window: c["bg"], R.WindowText: c["text"], R.Base: c["input"],
        R.AlternateBase: c["surface2"], R.Text: c["text"], R.Button: c["surface2"],
        R.ButtonText: c["text"], R.BrightText: c["danger"],
        R.Highlight: c["accent"], R.HighlightedText: c["on_accent"],
        R.ToolTipBase: c["surface2"], R.ToolTipText: c["text"],
        R.PlaceholderText: c["faint"], R.Link: c["accent"],
        R.Light: c["hover"], R.Midlight: c["border2"], R.Mid: c["border2"],
        R.Dark: c["border"], R.Shadow: c["sidebar"],
    }
    for role, col in pairs.items():
        p.setColor(role, QColor(col))
    for role in (R.Text, R.WindowText, R.ButtonText):
        p.setColor(G.Disabled, role, QColor(c["disabled"]))
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_stylesheet(theme: str = DEFAULT_THEME) -> str:
    return _TEMPLATE.format(**_tokens(resolve(theme)))


def apply_theme(theme: str | None) -> str:
    """Install a theme on the running QApplication; returns its real name."""
    global _current
    name = resolve(theme)
    _current = name
    app = QApplication.instance()
    if app is not None:
        # Tell Qt (and through it Windows) whether this theme is dark, so the
        # title bar and native frame match the theme instead of the system.
        try:
            from PyQt6.QtCore import Qt
            app.styleHints().setColorScheme(
                Qt.ColorScheme.Dark if _PALETTES[name]["dark"] == "1"
                else Qt.ColorScheme.Light)
        except AttributeError:      # Qt older than 6.8
            pass
        tokens = _tokens(name)
        app.setPalette(_qpalette(tokens))
        app.setStyleSheet(_TEMPLATE.format(**tokens))
    return name


# ---------------------------------------------------------------------------
# Stylesheet template
# ---------------------------------------------------------------------------

_TEMPLATE = """
/* ── Base ──────────────────────────────────────────────────────────── */
QWidget {{
    color: {text};
    font-family: {font_ui};
    font-size: 13px;
}}
QMainWindow, QDialog, QMessageBox {{
    background-color: {bg};
}}
QScrollArea, QScrollArea > QWidget > QWidget#PageContent,
QStackedWidget, QSplitter {{
    background: transparent;
    border: none;
}}

/* ── Sidebar ───────────────────────────────────────────────────────── */
QFrame#Sidebar {{
    background-color: {sidebar};
    border: none;
    border-right: 1px solid {border};
}}
QLabel#BrandName {{
    font-size: 15px;
    font-weight: 700;
}}
QLabel#BrandTag {{
    font-size: 12px;
    color: {muted};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {faint};
    letter-spacing: 0.6px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    padding: 0 12px 0 14px;
    min-height: 38px;
    text-align: left;
    color: {muted};
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background-color: {hover};
    color: {text};
}}
QPushButton#NavButton:checked {{
    background-color: {hover};
    border-left: 2px solid {accent};
    color: {text};
    font-weight: 600;
}}
QPushButton#NavButton[live="true"] {{
    color: {danger};
}}
QFrame#NowLoaded {{
    background: transparent;
    border: none;
    border-top: 1px solid {border2};
    border-radius: 0;
}}
QFrame#NowLoaded:hover {{
    background-color: {hover};
}}
QLabel#NowName {{
    font-size: 14px;
    font-weight: 600;
}}
QProgressBar#NowProgress {{
    background-color: {border2};
    min-height: 4px;
    max-height: 4px;
    border-radius: 2px;
}}
QProgressBar#NowProgress::chunk {{
    border-radius: 2px;
}}
QFrame#TimelineFrame {{
    border: 1px solid {border};
    border-radius: 4px;
    background-color: {input};
}}
QFrame#HotkeyPanel {{
    background: transparent;
    border: none;
    border-top: 1px solid {border2};
    border-radius: 0;
}}

/* ── Page structure ────────────────────────────────────────────────── */
QLabel#PageTitle {{
    font-size: 22px;
    font-weight: 700;
}}
QLabel#PageSubtitle {{
    font-size: 13px;
    color: {muted};
}}
QFrame#Card {{
    background: transparent;
    border: none;
    border-top: 1px solid {border2};
    border-radius: 0;
}}
QFrame#Card[variant="panel"] {{
    background-color: {surface};
    border: none;
    border-radius: 4px;
}}
QLabel#SectionTitle {{
    font-family: {font_mono};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {muted};
}}
QLabel#CardTitle {{
    font-size: 14px;
    font-weight: 600;
}}
QLabel#CardSubtitle {{
    font-size: 12px;
    color: {muted};
}}
QLabel#FieldLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {muted};
}}
QLabel#HotkeyError {{
    color: {danger};
    font-weight: 600;
}}
QLabel#HotkeyName {{
    font-weight: 600;
}}
QLabel#Hint {{
    font-size: 12px;
    color: {faint};
}}
QLabel[role="muted"] {{ color: {muted}; }}
QLabel[role="faint"] {{ color: {faint}; }}
QLabel[role="mono"]  {{ font-family: {font_mono}; }}
QFrame#Divider {{
    background-color: {border};
    border: none;
    min-height: 1px;
    max-height: 1px;
}}

/* Big numeric read-outs */
QLabel#BigValue {{
    font-family: {font_mono};
    font-size: 38px;
    font-weight: 600;
}}
QLabel#BigUnit {{
    font-size: 12px;
    color: {muted};
}}
QLabel#MacroName {{
    font-size: 18px;
    font-weight: 700;
}}
QFrame#Stat {{
    background-color: {surface};
    border: none;
    border-radius: 3px;
}}
QLabel#StatValue {{
    font-family: {font_mono};
    font-size: 18px;
    font-weight: 600;
}}
QLabel#StatLabel {{
    font-size: 12px;
    color: {muted};
}}

/* Keyboard key chip */
QLabel#KeyChip {{
    font-family: {font_mono};
    font-size: 11px;
    font-weight: 600;
    color: {text};
    background-color: {surface2};
    border: 1px solid {border2};
    border-bottom: 2px solid {border2};
    border-radius: 3px;
    padding: 1px 7px;
}}

/* Status pill */
QLabel#Pill {{
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
    background-color: {idle_soft};
    color: {muted};
}}
QLabel#Pill[tone="ok"]     {{ background-color: {success_soft}; color: {success}; }}
QLabel#Pill[tone="accent"] {{ background-color: {accent_soft};  color: {accent};  }}
QLabel#Pill[tone="warn"]   {{ background-color: {warn_soft};    color: {warn};    }}
QLabel#Pill[tone="danger"] {{ background-color: {danger_soft};  color: {danger};  }}
QLabel#Pill[tone="dim"]    {{ background-color: transparent;    color: {danger};  }}

/* Unsaved-changes banner */
QFrame#Banner {{
    background-color: {warn_soft};
    border: 1px solid {warn_line};
    border-radius: 6px;
}}
QLabel#BannerText {{
    color: {warn};
    font-weight: 600;
}}

/* ── Buttons ───────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {surface2};
    color: {text};
    border: 1px solid {border2};
    border-radius: 5px;
    padding: 0 14px;
    min-height: 32px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {hover};
}}
QPushButton:pressed {{
    background-color: {border};
}}
QPushButton:disabled {{
    background-color: {surface};
    color: {disabled};
    border-color: {border};
}}
QPushButton[size="lg"] {{
    min-height: 42px;
    border-radius: 6px;
    padding: 0 22px;
    font-size: 14px;
}}
QPushButton[variant="primary"] {{
    background-color: {accent};
    border: 1px solid {accent};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton[variant="success"] {{
    background-color: {success};
    border: 1px solid {success};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[variant="danger"] {{
    background-color: {danger};
    border: 1px solid {danger};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="success"]:hover,
QPushButton[variant="danger"]:hover {{
    border-color: {text};
}}
QPushButton[variant="danger_soft"] {{
    background-color: transparent;
    border: 1px solid {border2};
    color: {danger};
}}
QPushButton[variant="danger_soft"]:hover {{
    background-color: {danger_soft};
    border-color: {danger_line};
}}
QPushButton[variant="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {muted};
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {hover};
    color: {text};
}}
QPushButton[variant="ghost"]:disabled {{
    background-color: transparent;
    border-color: transparent;
    color: {disabled};
}}
QPushButton[variant="primary"]:disabled,
QPushButton[variant="success"]:disabled,
QPushButton[variant="danger"]:disabled,
QPushButton[variant="danger_soft"]:disabled {{
    background-color: {surface2};
    border-color: {border};
    color: {disabled};
}}

/* Segmented control (exclusive checkable buttons) */
QFrame#Segmented {{
    background-color: {input};
    border: 1px solid {border2};
    border-radius: 5px;
}}
QPushButton#Segment {{
    background: transparent;
    border: none;
    border-radius: 6px;
    min-height: 28px;
    padding: 0 16px;
    color: {muted};
}}
QPushButton#Segment:hover {{
    color: {text};
    background-color: {hover};
}}
QPushButton#Segment:checked {{
    background-color: {accent_soft};
    color: {accent};
    font-weight: 600;
}}

/* ── Inputs ────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {input};
    border: 1px solid {border2};
    border-radius: 5px;
    padding: 0 10px;
    min-height: 32px;
    color: {text};
    selection-background-color: {accent};
    selection-color: {on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {faint};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background-color: {surface};
    color: {disabled};
    border-color: {border};
}}
QLineEdit:read-only {{
    color: {muted};
}}
QLineEdit#Mono {{
    font-family: {font_mono};
}}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{
    border: 1px solid {danger};
}}
QLabel#FieldUnit {{
    color: {muted};
    background: transparent;
    font-size: 12px;
}}
QComboBox#UnitPicker {{
    min-width: 84px;
}}
QPushButton#UnlimitedToggle {{
    color: {muted};
    padding: 0 12px;
}}
QPushButton#UnlimitedToggle:checked {{
    background-color: {accent_soft};
    border-color: {accent_line};
    color: {accent};
    font-weight: 600;
}}
QSpinBox, QDoubleSpinBox {{
    font-family: {font_mono};
    padding-right: 26px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    border-left: 1px solid {border};
    border-top-right-radius: 5px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border: none;
    border-left: 1px solid {border};
    border-bottom-right-radius: 5px;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {hover};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({img_up});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({img_down});
    width: 10px;
    height: 10px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
    image: url({img_up_dis});
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
    image: url({img_down_dis});
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url({img_down});
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {surface};
    border: 1px solid {border2};
    border-radius: 5px;
    padding: 4px;
    outline: 0;
    selection-background-color: {sel};
    selection-color: {text};
}}

/* Switch-style check boxes */
QCheckBox {{
    spacing: 10px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 36px;
    height: 22px;
    image: url({img_sw_off});
}}
QCheckBox::indicator:checked {{
    image: url({img_sw_on});
}}
QCheckBox::indicator:disabled {{
    image: url({img_sw_off_dis});
}}
QCheckBox::indicator:checked:disabled {{
    image: url({img_sw_on_dis});
}}
QCheckBox:disabled {{
    color: {disabled};
}}

QRadioButton {{
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 5px;
    border: 2px solid {border2};
    background-color: {input};
}}
QRadioButton::indicator:checked {{
    border: 4px solid {accent};
    background-color: {on_accent};
}}

/* ── Slider ────────────────────────────────────────────────────────── */
QSlider {{
    min-height: 24px;
    background: transparent;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {border2};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background-color: {accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: {accent};
    border: 3px solid {surface};
    width: 12px;
    height: 12px;
    margin: -7px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    background-color: {accent_hover};
}}
QSlider::sub-page:horizontal:disabled {{
    background-color: {disabled};
}}
QSlider::handle:horizontal:disabled {{
    background-color: {disabled};
}}

/* ── Lists and trees ───────────────────────────────────────────────── */
QListWidget, QTreeWidget {{
    background-color: {input};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    min-height: 32px;
    padding: 0 10px;
    border-radius: 6px;
    margin: 1px 0;
}}
QTreeWidget::item {{
    min-height: 32px;
    padding: 0 6px;
    border: none;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {hover};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {sel};
    color: {text};
}}
QHeaderView {{
    background: transparent;
    border: none;
}}
QHeaderView::section {{
    background-color: transparent;
    color: {faint};
    border: none;
    border-bottom: 1px solid {border};
    padding: 6px 6px 8px 6px;
    font-size: 11px;
    font-weight: 600;
}}

/* ── Scroll bars ───────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {faint};
    min-height: 32px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {muted};
}}

/* "More below" pill shown over the bottom of scrollable pages */
QPushButton#ScrollHint {{
    background-color: {surface2};
    border: 1px solid {accent_line};
    color: {accent};
    border-radius: 13px;
    min-height: 26px;
    padding: 0 14px 0 10px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#ScrollHint:hover {{
    background-color: {accent_soft};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: {border2};
    min-width: 32px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {faint};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    border: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}

/* ── Progress bar ──────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {surface2};
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    color: transparent;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 4px;
}}

/* ── Text edit ─────────────────────────────────────────────────────── */
QTextEdit {{
    background-color: {input};
    border: 1px solid {border};
    border-radius: 5px;
    color: {muted};
    padding: 6px 8px;
}}

/* ── Splitter ──────────────────────────────────────────────────────── */
QSplitter::handle {{
    background: transparent;
}}

/* ── Menus and tooltips ────────────────────────────────────────────── */
QMenu {{
    background-color: {surface};
    border: 1px solid {border2};
    border-radius: 5px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {sel};
}}
QMenu::item:disabled {{
    color: {disabled};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 6px;
}}
QLabel#InfoPopupText {{
    color: {text};
    font-size: 12px;
    background: transparent;
}}
QToolTip {{
    background-color: {surface2};
    color: {text};
    border: 1px solid {border2};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ── Status bar ────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {sidebar};
    color: {muted};
    border-top: 1px solid {border};
    font-size: 12px;
    min-height: 26px;
    padding-left: 12px;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    color: {muted};
    font-size: 12px;
    padding: 0 10px;
}}
QStatusBar QLabel#Copyright {{
    color: {faint};
    font-size: 12px;
    padding: 0 14px;
}}
"""
