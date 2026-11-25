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
    QPixmap, QPolygonF, QTransform,
)

TILE_TOP, TILE_BOTTOM = "#232733", "#0e0f13"
TILE_EDGE = "#343a49"
GOLD, GOLD_LIGHT = "#e8b64c", "#f6d58a"
KEY, KEY_TOP, KEY_EDGE = "#c9ccd4", "#f3f4f7", "#8d929e"
RECORD = "#f4506b"


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

    p.translate(3 * s, 0)                     # optical centring in the tile

    # Pointer geometry, in the 100-unit grid.  The classic arrow: left edge
    # vertical, right edge at 45 degrees, stem leaving down and to the right.
    tip = QPointF(30, 13)
    head = QPolygonF([tip, QPointF(30, 64), QPointF(65.5, 49.5)])
    round_r = 7.0 if not small else 5.0

    def scaled(poly: QPolygonF) -> QPolygonF:
        return QTransform.fromScale(s, s).map(poly)

    # Head: a rounded triangle = fill + same-colour stroke with round joins.
    head_grad = QLinearGradient(30 * s, 13 * s, 60 * s, 64 * s)
    head_grad.setColorAt(0, QColor(GOLD_LIGHT))
    head_grad.setColorAt(1, QColor(GOLD))
    pen = QPen(QBrush(head_grad), round_r * s)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QBrush(head_grad))
    p.drawPolygon(scaled(head))

    # Stem: a key cap, set apart from the head by a small gap.
    angle = 26.0                                  # degrees from vertical
    p.save()
    p.translate(44.5 * s, 66.0 * s)
    p.rotate(-angle)
    w, h = (14.0, 27.0)
    cap = QRectF(-w / 2 * s, 0, w * s, h * s)
    p.setPen(QPen(QColor(KEY_EDGE), max(0.8, 1.4 * s)) if not small else Qt.PenStyle.NoPen)
    p.setBrush(QColor(KEY))
    p.drawRoundedRect(cap, 4.5 * s, 4.5 * s)
    if not small:
        top = QRectF((-w / 2 + 2.6) * s, 2.2 * s, (w - 5.2) * s, (h - 8) * s)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(KEY_TOP))
        p.drawRoundedRect(top, 3 * s, 3 * s)
    p.restore()

    # Record dot, top right of the tip, with a soft halo at larger sizes.
    centre, r = QPointF(70 * s, 24 * s), (7.0 if not small else 10.0) * s
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
