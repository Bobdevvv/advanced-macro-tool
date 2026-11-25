"""
The AMT logo: a mouse pointer assembled from the things the app works with.

* the arrow head is a rounded **play** triangle (replay),
* the stem is a **keyboard key**, with its key top,
* a red **record** dot sits beside the tip,

on a dark tile in the Terminal theme's colours.  Drawn with QPainter so the
same code makes the window icon, the .ico file (scripts/make_icon.py), the
sidebar mark and the README image at any size.  Small sizes drop the detail
that would only turn into blur.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import (
    QBrush, QColor, QImage, QLinearGradient, QPainter, QPen,
    QPixmap, QPolygonF,
)

TILE_TOP, TILE_BOTTOM = "#232733", "#0e0f13"
TILE_EDGE = "#343a49"
GOLD, GOLD_LIGHT = "#e8b64c", "#f6d58a"
KEY, KEY_TOP, KEY_EDGE = "#c9ccd4", "#f3f4f7", "#8d929e"
RECORD = "#f4506b"

# Pointer geometry in the 100 x 100 design grid.
AXIS_TILT = 22.5                     # degrees; = the head's half-angle
HEAD_H = 50.0                        # tip to base, along the axis
HEAD_HALF_W = HEAD_H * math.tan(math.radians(AXIS_TILT))
KEY_W, KEY_H, KEY_GAP = 14.0, 25.0, 2.5
TIP = QPointF(30, 12)


def paint(p: QPainter, size: float, tile: bool = True) -> None:
    """Draw the logo into the square (0, 0, size, size)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    small = size < 40
    s = size / 100.0                          # design grid is 100 x 100

    if tile:
        inset = max(0.5, 2.5 * s)
        rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
        grad = QLinearGradient(0, 0, 0, size)
        grad.setColorAt(0, QColor(TILE_TOP))
        grad.setColorAt(1, QColor(TILE_BOTTOM))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(TILE_EDGE), max(1.0, 1.2 * s)) if not small else Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 21 * s, 21 * s)

    # The pointer is built on one axis: tip at the origin, pointing up, the
    # head symmetric about the axis and the key centred on it.  Tilting the
    # axis by the head's half-angle (22.5 degrees) gives the classic pointer
    # silhouette: left edge vertical, right edge at 45 degrees.
    p.save()
    p.translate(TIP.x() * s, TIP.y() * s)
    p.rotate(-AXIS_TILT)
    p.scale(s, s)                             # from here on: 100-unit grid

    round_r = 7.0 if not small else 5.0
    head = QPolygonF([QPointF(0, 0), QPointF(-HEAD_HALF_W, HEAD_H),
                      QPointF(HEAD_HALF_W, HEAD_H)])
    # Head: a rounded triangle = fill + same-colour stroke with round joins.
    head_grad = QLinearGradient(0, 0, 0, HEAD_H)
    head_grad.setColorAt(0, QColor(GOLD_LIGHT))
    head_grad.setColorAt(1, QColor(GOLD))
    pen = QPen(QBrush(head_grad), round_r)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QBrush(head_grad))
    p.drawPolygon(head)

    # Stem: a key cap on the axis, set apart from the head by a small gap.
    top_y = HEAD_H + round_r / 2 + KEY_GAP
    cap = QRectF(-KEY_W / 2, top_y, KEY_W, KEY_H)
    p.setPen(QPen(QColor(KEY_EDGE), max(0.8 / s, 1.4)) if not small else Qt.PenStyle.NoPen)
    p.setBrush(QColor(KEY))
    p.drawRoundedRect(cap, 4.5, 4.5)
    if not small:
        top = QRectF(-KEY_W / 2 + 2.6, top_y + 2.2, KEY_W - 5.2, KEY_H - 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(KEY_TOP))
        p.drawRoundedRect(top, 3, 3)
    p.restore()

    # Record dot, top right of the tip, with a soft halo at larger sizes.
    centre, r = QPointF(68 * s, 24 * s), (7.0 if not small else 10.0) * s
    if not small:
        halo = QColor(RECORD)
        halo.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(centre, r * 1.45, r * 1.45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(RECORD))
    p.drawEllipse(centre, r, r)
    p.restore()


def image(size: int, tile: bool = True) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint(p, size, tile)
    p.end()
    return img


def pixmap(size: int, dpr: float = 1.0, tile: bool = True) -> QPixmap:
    """A crisp pixmap for a widget of ``size`` logical pixels."""
    px = max(1, int(math.ceil(size * dpr)))
    pm = QPixmap.fromImage(image(px, tile))
    pm.setDevicePixelRatio(dpr)
    return pm


class LogoMark(QWidget):
    """The logo as a widget; painted live, so it is sharp at any display scale."""

    def __init__(self, size: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint(p, self.width())
        p.end()
