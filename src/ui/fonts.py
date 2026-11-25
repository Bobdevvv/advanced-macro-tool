"""
Bundled fonts.

Inter (interface text) and JetBrains Mono (numbers, hotkeys, timings) ship in
assets/fonts and are registered with Qt at start-up, so the app looks the same
on every machine.  If the files are missing, the CSS-style stacks below fall
back to fonts that come with Windows.
"""
from __future__ import annotations

import os

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from src import app_paths

UI_FAMILY   = "Inter"
MONO_FAMILY = "JetBrains Mono"

# Used verbatim in the stylesheet.
UI_STACK   = f'"{UI_FAMILY}", "Segoe UI", sans-serif'
MONO_STACK = f'"{MONO_FAMILY}", "Cascadia Mono", Consolas, monospace'


def _font_dir() -> str:
    return os.path.join(app_paths.resource_dir(), "assets", "fonts")


def install_fonts(app: QApplication) -> None:
    """Register the bundled fonts and make Inter the application default."""
    folder = _font_dir()
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, name))

    font = QFont(UI_FAMILY if UI_FAMILY in QFontDatabase.families() else "Segoe UI")
    font.setPixelSize(13)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
