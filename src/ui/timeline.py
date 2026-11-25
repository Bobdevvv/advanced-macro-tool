"""
The macro timeline: a zoomable, scrollable view of a macro's actions.

Layout (top to bottom): a time ruler, then three tracks, Keyboard (held keys
as labelled bars, overlapping keys stacked in lanes), Clicks & scroll, and
Mouse movement.  Track names sit in a fixed column on the left so they stay
visible while the timeline scrolls.

The view does not edit anything itself.  It reports what the user did
(``playhead_moved``, ``range_move_requested`` …) and the Composer page turns
that into an edit, so every change goes through one place with undo.

Mouse:
* click the ruler or empty space ............ move the playhead
* drag across the ruler or empty space ....... select a stretch of time
* click an action ........................... select it (Ctrl adds/removes)
* drag selected actions ..................... move them in time
* drag inside a selected stretch ............ move that stretch elsewhere
* Ctrl + wheel ............................... zoom around the pointer
* Shift + wheel .............................. scroll sideways
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QWidget,
)

from src.core import editing as ed
from src.models.macro import MacroEvent
from src.ui import theme
from src.ui.fonts import MONO_FAMILY, UI_FAMILY

RULER_H = 28
LANE_H = 24
LANE_GAP = 3
TRACK_GAP = 10
KEY_LANES = 4
LEFT_PAD = 12
RIGHT_PAD = 60
LABEL_W = 96
DRAG_THRESHOLD = 4
MIN_PPS, MAX_PPS = 4.0, 4000.0

# Distances between ruler labels, in seconds.
_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120,
          300, 600, 1800, 3600, 7200, 21600, 43200, 86400)


@dataclass
class _Track:
    key: str
    title: str
    top: float
    height: float
    lanes: int


def fmt_time(t: float, step: float = 0.1) -> str:
    """Ruler / status time: 1.25 → '1.25 s', 75 → '1:15', 3700 → '1:01:40'."""
    if t < 60:
        decimals = 2 if step < 0.1 else (1 if step < 1 else 0)
        return f"{t:.{decimals}f} s"
    h, rem = divmod(int(round(t)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class TimelineCanvas(QWidget):
    playhead_moved = pyqtSignal(float)
    selection_changed = pyqtSignal()
    range_move_requested = pyqtSignal(float, float, float)      # a, b, to
    gestures_shift_requested = pyqtSignal(list, float)          # gestures, dt
    macro_dropped = pyqtSignal(str, float)                      # filename, time
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.events: List[MacroEvent] = []
        self.gestures: List[ed.Gesture] = []
        self.selected: Set[int] = set()              # indices into gestures
        self.range: Optional[Tuple[float, float]] = None
        self.playhead = 0.0
        self.pps = 100.0                             # pixels per second

        self._rects: List[Tuple[QRectF, int]] = []
        self._lanes: dict = {}
        self._room: dict = {}          # key gesture -> seconds until the next one in its lane
        self._drag = None                            # current drag state
        self._drop_t: Optional[float] = None
        self._tracks = self._layout_tracks(1)
        self._fit_width = 600

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_events(self, events: Sequence[MacroEvent], keep_selection: bool = False) -> None:
        self.events = list(events)
        self.gestures = ed.gestures(self.events)
        if not keep_selection:
            self.selected.clear()
        else:
            self.selected = {i for i in self.selected if i < len(self.gestures)}
        self._assign_lanes()
        self._resize()
        self.update()

    def duration(self) -> float:
        return ed.duration(self.events)

    def selected_gestures(self) -> List[ed.Gesture]:
        return [self.gestures[i] for i in sorted(self.selected)]

    def clear_selection(self) -> None:
        if self.selected or self.range:
            self.selected.clear()
            self.range = None
            self.update()
            self.selection_changed.emit()

    def select_range(self, a: float, b: float) -> None:
        a, b = sorted((max(0.0, a), max(0.0, b)))
        self.range = (a, b) if b - a > 1e-6 else None
        self.selected.clear()
        self.update()
        self.selection_changed.emit()

    def set_playhead(self, t: float, emit: bool = True) -> None:
        self.playhead = max(0.0, t)
        self.update()
        if emit:
            self.playhead_moved.emit(self.playhead)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _layout_tracks(self, key_lanes: int) -> List[_Track]:
        y = RULER_H + 8
        out = []
        for key, title, lanes in (("keys", "Keyboard", key_lanes),
                                  ("clicks", "Clicks & scroll", 1),
                                  ("moves", "Mouse movement", 1)):
            h = lanes * LANE_H + (lanes - 1) * LANE_GAP
            out.append(_Track(key, title, y, h, lanes))
            y += h + TRACK_GAP
        return out

    def tracks(self) -> List[_Track]:
        return self._tracks

    def _assign_lanes(self) -> None:
        """Stack overlapping key holds (Ctrl under C) into separate lanes."""
        lane_end = [-1.0] * KEY_LANES
        last_in_lane: dict = {}
        self._lanes, self._room = {}, {}
        for i, g in enumerate(self.gestures):
            if g.track != "keys":
                continue
            lane = next((n for n, end in enumerate(lane_end) if g.start > end + 1e-9),
                        KEY_LANES - 1)
            lane_end[lane] = max(lane_end[lane], g.end)
            self._lanes[i] = lane
            if lane in last_in_lane:
                prev = last_in_lane[lane]
                self._room[prev] = g.start - self.gestures[prev].start
            last_in_lane[lane] = i
        used = (max(self._lanes.values()) + 1) if self._lanes else 1
        self._tracks = self._layout_tracks(used)

    def total_height(self) -> int:
        last = self._tracks[-1]
        return int(last.top + last.height + 12)

    def x_of(self, t: float) -> float:
        return LEFT_PAD + t * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, (x - LEFT_PAD) / self.pps)

    def _resize(self) -> None:
        w = int(self.x_of(self.duration()) + RIGHT_PAD)
        self.setFixedSize(max(w, self._fit_width), self.total_height())

    def set_view_width(self, w: int) -> None:
        self._fit_width = max(200, w)
        self._resize()

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.total_height())

    def set_zoom(self, pps: float, anchor_t: Optional[float] = None) -> None:
        self.pps = min(MAX_PPS, max(MIN_PPS, pps))
        self._resize()
        self.update()
        # Always a *time* to keep in view (never the zoom level itself).
        self.zoom_changed.emit(self.playhead if anchor_t is None else anchor_t)

    def fit(self) -> None:
        span = max(self.duration(), 1.0)
        self.set_zoom((self._fit_width - LEFT_PAD - RIGHT_PAD) / span, anchor_t=0.0)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, e) -> None:
        c = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QRectF(e.rect())
        p.fillRect(clip, QColor(c["input"]))
        self._rects = []

        # Track backgrounds
        for tr in self._tracks:
            band = QRectF(clip.left(), tr.top - 4, clip.width(), tr.height + 8)
            p.fillRect(band, QColor(c["surface"]))
        self._paint_ruler(p, clip, c)
        self._paint_range(p, c)

        t0, t1 = self.t_of(clip.left() - 40), self.t_of(clip.right() + 40)
        for i, g in enumerate(self.gestures):
            if g.end < t0 or g.start > t1:
                continue
            self._paint_gesture(p, i, g, c)

        self._paint_drag_preview(p, c)
        self._paint_playhead(p, c)
        p.end()

    def _paint_ruler(self, p: QPainter, clip: QRectF, c) -> None:
        p.fillRect(QRectF(clip.left(), 0, clip.width(), RULER_H), QColor(c["surface2"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(QPointF(clip.left(), RULER_H), QPointF(clip.right(), RULER_H))
        step = next((s for s in _STEPS if s * self.pps >= 80), _STEPS[-1])
        f = QFont(MONO_FAMILY)
        f.setPixelSize(10)
        p.setFont(f)
        start = math.floor(self.t_of(clip.left()) / step) * step
        t = start
        while self.x_of(t) <= clip.right() + step * self.pps:
            x = self.x_of(t)
            p.setPen(QPen(QColor(c["border2"]), 1))
            p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
            p.setPen(QPen(QColor(c["border"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, RULER_H), QPointF(x, self.height()))
            p.setPen(QColor(c["muted"]))
            p.drawText(QPointF(x + 4, RULER_H - 11), fmt_time(t, step))
            half = x + step * self.pps / 2
            p.setPen(QPen(QColor(c["border2"]), 1))
            p.drawLine(QPointF(half, RULER_H - 4), QPointF(half, RULER_H))
            t += step

    def _paint_range(self, p: QPainter, c) -> None:
        if not self.range:
            return
        a, b = self.range
        r = QRectF(self.x_of(a), 0, max(2.0, (b - a) * self.pps), self.height())
        fill = QColor(c["accent"])
        fill.setAlpha(34)
        p.fillRect(r, fill)
        p.setPen(QPen(QColor(c["accent"]), 1.5))
        p.drawLine(r.topLeft(), r.bottomLeft())
        p.drawLine(r.topRight(), r.bottomRight())

    def _gesture_rect(self, i: int, g: ed.Gesture) -> QRectF:
        tr = next(t for t in self._tracks if t.key == g.track)
        lane = self._lanes.get(i, 0) if g.track == "keys" else 0
        y = tr.top + lane * (LANE_H + LANE_GAP)
        x0, x1 = self.x_of(g.start), self.x_of(g.end)
        h = LANE_H
        if g.kind == "move":
            y, h = y + 6, LANE_H - 12
        min_w = 8 if g.kind != "click" else 12
        w = max(min_w, x1 - x0)
        if g.kind == "key":
            # Widen short key presses just enough to show their label, as
            # long as that does not run into the next key in the same lane.
            room = self._room.get(i, float("inf")) * self.pps - 3
            w = max(w, min(self._label_w(g.label) + 10, room))
        return QRectF(x0, y, w, h)

    def _label_w(self, text: str) -> int:
        f = QFont(UI_FAMILY)
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        return QFontMetrics(f).horizontalAdvance(text)

    def _paint_gesture(self, p: QPainter, i: int, g: ed.Gesture, c) -> None:
        r = self._gesture_rect(i, g)
        drag = self._drag
        if drag and drag["kind"] == "gestures" and i in self.selected and drag.get("moved"):
            r = r.translated(drag["dt"] * self.pps, 0)
        self._rects.append((r, i))
        sel = i in self.selected
        base = {"key": c["accent"], "click": c["success"], "scroll": c["warn"],
                "move": c["muted"]}[g.kind]
        fill = QColor(base)
        fill.setAlpha(200 if sel else (90 if g.kind == "move" else 150))
        p.setBrush(fill)
        p.setPen(QPen(QColor(c["text"] if sel else base), 2 if sel else 1))
        radius = 4 if g.kind != "click" else r.height() / 2
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        label = g.label if g.kind == "key" else {"click": (g.label[:1] or "L"),
                                                   "scroll": "↕", "move": ""}[g.kind]
        if label:
            f = QFont(UI_FAMILY)
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            fm = QFontMetrics(f)
            if fm.horizontalAdvance(label) + 8 <= r.width() or g.kind != "key":
                p.setPen(QColor(c["on_accent"] if g.kind == "key" else c["bg"]))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_drag_preview(self, p: QPainter, c) -> None:
        d = self._drag
        target = None
        if d and d["kind"] == "range" and d.get("moved"):
            target = d["to"]
        elif self._drop_t is not None:
            target = self._drop_t
        if target is None:
            return
        x = self.x_of(target)
        p.setPen(QPen(QColor(c["accent"]), 2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x, RULER_H), QPointF(x, self.height()))
        if d and d["kind"] == "range":
            a, b = self.range
            ghost = QRectF(x, RULER_H + 2, (b - a) * self.pps, self.height() - RULER_H - 4)
            col = QColor(c["accent"])
            col.setAlpha(26)
            p.fillRect(ghost, col)

    def _paint_playhead(self, p: QPainter, c) -> None:
        x = self.x_of(self.playhead)
        col = QColor(c["danger"])
        p.setPen(QPen(col, 1.5))
        p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, self.height()))
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(x - 5, RULER_H - 12), QPointF(x + 5, RULER_H - 12),
                                 QPointF(x, RULER_H - 5)]))

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def _hit(self, pos: QPointF) -> Optional[int]:
        for r, i in reversed(self._rects):
            if r.adjusted(-2, -3, 2, 3).contains(pos):
                return i
        return None

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        pos = e.position()
        t = self.t_of(pos.x())
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        hit = self._hit(pos) if pos.y() > RULER_H else None
        if hit is not None:
            if ctrl:
                self.selected ^= {hit}
            elif hit not in self.selected:
                self.selected = {hit}
            self.range = None
            self._drag = {"kind": "gestures", "x0": pos.x(), "dt": 0.0, "moved": False}
            self.selection_changed.emit()
        elif self.range and self.range[0] <= t <= self.range[1] and pos.y() > RULER_H:
            self._drag = {"kind": "range", "x0": pos.x(), "to": t, "moved": False}
        else:
            self._drag = {"kind": "select", "x0": pos.x(), "t0": t, "moved": False}
        self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        d = self._drag
        if d is None:
            hover = self._hit(pos) if pos.y() > RULER_H else None
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover is not None
                           else Qt.CursorShape.IBeamCursor)
            if hover is not None:
                g = self.gestures[hover]
                self.setToolTip(_describe(g, self.events))
            else:
                self.setToolTip("Click: place the playhead · drag: select time · "
                                "Ctrl+scroll: zoom · Shift+scroll: scroll sideways")
            return
        if abs(pos.x() - d["x0"]) >= DRAG_THRESHOLD:
            d["moved"] = True
        if not d["moved"]:
            return
        if d["kind"] == "gestures":
            d["dt"] = (pos.x() - d["x0"]) / self.pps
        elif d["kind"] == "range":
            d["to"] = self.t_of(pos.x())
        else:
            a, b = sorted((d["t0"], self.t_of(pos.x())))
            self.range = (a, b)
            self.selected.clear()
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        d, self._drag = self._drag, None
        if d is None:
            return
        if d["kind"] == "gestures" and d["moved"] and abs(d["dt"]) > 1e-6:
            self.gestures_shift_requested.emit(self.selected_gestures(), d["dt"])
        elif d["kind"] == "range" and d["moved"]:
            a, b = self.range
            self.range_move_requested.emit(a, b, d["to"])
        elif d["kind"] == "select":
            if d["moved"]:
                self.selection_changed.emit()
            else:
                self.selected.clear()
                self.range = None
                self.set_playhead(d["t0"])
                self.selection_changed.emit()
        elif d["kind"] == "range" and not d["moved"]:
            self.set_playhead(self.t_of(e.position().x()))
        self.update()

    def wheelEvent(self, e) -> None:
        mods = e.modifiers()
        dy = e.angleDelta().y()
        if mods & Qt.KeyboardModifier.ControlModifier and dy:
            anchor = self.t_of(e.position().x())
            self.set_zoom(self.pps * (1.25 if dy > 0 else 0.8), anchor)
            e.accept()
        else:
            e.ignore()          # the parent scroll area / page handles it

    # ------------------------------------------------------------------
    # Drop a library macro onto the timeline
    # ------------------------------------------------------------------

    def _drop_source_ok(self, e) -> bool:
        src = e.source()
        return isinstance(src, QAbstractItemView) and src.objectName() == "ComposerLibrary"

    def dragEnterEvent(self, e) -> None:
        if self._drop_source_ok(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:
        if self._drop_source_ok(e):
            self._drop_t = self.t_of(e.position().x())
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self._drop_t = None
        self.update()

    def dropEvent(self, e) -> None:
        t = self.t_of(e.position().x())
        self._drop_t = None
        self.update()
        src = e.source()
        item = src.currentItem() if src is not None else None
        if item is not None:
            fname = item.data(Qt.ItemDataRole.UserRole)
            if fname:
                e.setDropAction(Qt.DropAction.CopyAction)
                e.accept()
                self.macro_dropped.emit(fname, t)
                return
        e.ignore()


def _describe(g: ed.Gesture, events: Sequence[MacroEvent]) -> str:
    span = g.end - g.start
    if g.kind == "key":
        return f"{g.label} key, held {span:.2f} s (at {fmt_time(g.start, 0.01)})"
    if g.kind == "click":
        e = events[g.indices[0]]
        return f"{g.label} at ({e.x}, {e.y}), held {span:.2f} s"
    if g.kind == "scroll":
        return f"Scroll, {len(g.indices)} steps"
    return f"Mouse movement, {len(g.indices)} points over {span:.2f} s"


class _TrackLabels(QWidget):
    """Fixed column with track names, aligned with the canvas tracks."""

    def __init__(self, canvas: TimelineCanvas) -> None:
        super().__init__()
        self.canvas = canvas
        self.setFixedWidth(LABEL_W)

    def paintEvent(self, _e) -> None:
        c = theme.palette()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(c["surface2"]))
        f = QFont(UI_FAMILY)
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        for tr in self.canvas.tracks():
            p.setPen(QColor(c["muted"]))
            r = QRectF(10, tr.top, LABEL_W - 14, tr.height)
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                       | Qt.TextFlag.TextWordWrap, tr.title)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()


class TimelineView(QFrame):
    """Track labels + horizontally scrolling canvas, in a bordered frame."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TimelineFrame")
        self.canvas = TimelineCanvas()
        self.labels = _TrackLabels(self.canvas)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        lay.addWidget(self.labels)
        lay.addWidget(self.scroll, 1)
        self.canvas.zoom_changed.connect(self._keep_anchor)
        self._sync_height()

    def _sync_height(self) -> None:
        h = self.canvas.total_height() + 16      # room for the scroll bar
        self.setFixedHeight(h + 2)
        self.labels.update()

    def refresh(self) -> None:
        self._sync_height()
        self.canvas.set_view_width(self.scroll.viewport().width())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.canvas.set_view_width(self.scroll.viewport().width())

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier or e.angleDelta().x():
            bar = self.scroll.horizontalScrollBar()
            delta = e.angleDelta().x() or e.angleDelta().y()
            bar.setValue(bar.value() - delta)
            e.accept()
        else:
            e.ignore()

    def _keep_anchor(self, anchor_t: float) -> None:
        # After zooming keep the time under the pointer (or the playhead)
        # roughly where it was.
        bar = self.scroll.horizontalScrollBar()
        x = self.canvas.x_of(anchor_t)
        bar.setValue(int(x - self.scroll.viewport().width() / 2))
        self._sync_height()

    def ensure_visible(self, t: float) -> None:
        self.scroll.ensureVisible(int(self.canvas.x_of(t)), 10, 60, 0)
