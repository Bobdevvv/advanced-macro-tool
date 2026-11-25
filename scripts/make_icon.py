"""
Write the logo files from src/ui/logo.py:

* assets/amt.ico   the exe, window and taskbar icon, every size Windows uses
* assets/amt.png   256 px, for the README

    python scripts/make_icon.py

The .ico is written by hand (PNG-compressed entries, supported since Windows
Vista) so every size is drawn at that size rather than scaled from one bitmap.
"""
from __future__ import annotations

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICO = os.path.join(ROOT, "assets", "amt.ico")
PNG = os.path.join(ROOT, "assets", "amt.png")


def png_bytes(img) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(images: dict, path: str) -> None:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)            # reserved, type=icon, count
    entries, blobs = b"", b""
    offset = 6 + 16 * count
    for size, png in images.items():
        dim = 0 if size >= 256 else size                 # 0 means 256 in ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def main() -> None:
    _app = QApplication.instance() or QApplication([])  # noqa: F841  (QImage text needs it)
    from src.ui import logo
    write_ico({s: png_bytes(logo.image(s)) for s in SIZES}, ICO)
    logo.image(256).save(PNG)
    print("wrote", ICO)
    print("wrote", PNG)


if __name__ == "__main__":
    main()
