"""
Reusable building blocks for the pages.

Everything here is layout and presentation only; colours come from the
stylesheet via object names and dynamic properties (see theme.py).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6 import sip
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src.ui import icons

# Spacing scale (px): use these instead of ad-hoc numbers.
S1, S2, S3, S4, S5, S6 = 4, 8, 12, 16, 24, 32


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def set_prop(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property and re-apply the stylesheet to the widget."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def label(text: str = "", name: Optional[str] = None, role: Optional[str] = None,
          wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def button(text: str = "", variant: Optional[str] = None,
           glyph: Optional[str] = None, size: Optional[str] = None,
           tooltip: Optional[str] = None) -> QPushButton:
    """A push button.  variant: primary | success | danger | danger_soft | ghost."""
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        b.setProperty("variant", variant)
    if size:
        b.setProperty("size", size)
    if tooltip:
        b.setToolTip(tooltip)
    if glyph:
        icons.bind(b, glyph, _icon_role(variant), 18 if size == "lg" else 15)
    return b


def _icon_role(variant: Optional[str]) -> str:
    """Icon colour that matches a button variant's text colour."""
    return {"primary": "on_accent", "success": "on_accent", "danger": "#ffffff",
            "danger_soft": "danger", "ghost": "muted"}.get(variant or "", "text")


def set_button_glyph(b: QPushButton, glyph: str, variant: Optional[str]) -> None:
    """Change a button's icon and variant together (e.g. Start → Stop)."""
    set_prop(b, "variant", variant or "")
    icons.bind(b, glyph, _icon_role(variant), 18 if b.property("size") == "lg" else 15)


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def pretty_hotkey(hk: str) -> List[str]:
    """'<ctrl>+<shift>+r' → ['Ctrl', 'Shift', 'R']"""
    if not hk:
        return []
    out = []
    for part in hk.split("+"):
        p = part.strip().strip("<>")
        if not p:
            continue
        nice = {
            "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win",
            "esc": "Esc", "page_up": "PgUp", "page_down": "PgDn",
            "print_screen": "PrtSc", "scroll_lock": "ScrLk",
            "num_lock": "NumLk", "caps_lock": "Caps", "backspace": "Bksp",
            "delete": "Del", "insert": "Ins", "enter": "Enter",
            "space": "Space", "tab": "Tab",
        }.get(p.lower())
        out.append(nice or p.upper())
    return out


# ---------------------------------------------------------------------------
# Info tip
# ---------------------------------------------------------------------------

class _InfoPopup(QFrame):
    """The explanation bubble shared by every InfoTip.

    A plain frameless window rather than QToolTip: Qt animates tooltips open
    (a roll-out that reads as lag), while this appears in a single frame.
    """

    MAX_WIDTH = 300
    _instance: Optional["_InfoPopup"] = None

    @classmethod
    def get(cls) -> "_InfoPopup":
        # Qt may already have destroyed the bubble (it is a top-level window,
        # torn down with the app); make a new one rather than touch a dead one.
        if cls._instance is None or sip.isdeleted(cls._instance):
            cls._instance = cls()
        return cls._instance

    @classmethod
    def hide_if_alive(cls) -> None:
        """Hide the bubble if it exists.  Called from icons' hide/leave
        events, which also run while the app shuts down, after Qt has
        destroyed the bubble."""
        inst = cls._instance
        if inst is not None and not sip.isdeleted(inst):
            inst.hide()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("InfoPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Transparent window so the frame's rounded corners show cleanly.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        self._label = QLabel()
        self._label.setObjectName("InfoPopupText")
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self._label)

    def paintEvent(self, _e) -> None:
        # Painted here: a translucent top-level window gets no stylesheet
        # background, and translucency is what lets the corners be round.
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QPainter, QPen
        from src.ui import theme
        c = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(c["border2"]), 1))
        p.setBrush(QColor(c["surface2"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        p.end()

    def show_for(self, anchor: QWidget, text: str) -> None:
        from PyQt6.QtCore import QPoint
        self._label.setText(text)
        # Width: natural width for short text, capped for long text.
        self._label.setFixedWidth(min(self.MAX_WIDTH,
                                      self._label.fontMetrics().horizontalAdvance(text) + 2))
        self.adjustSize()

        # Below-right of the icon, flipped/clamped to stay on screen.
        top_left = anchor.mapToGlobal(QPoint(0, 0))
        x = top_left.x() - 6
        y = top_left.y() + anchor.height() + 6
        screen = anchor.screen().availableGeometry()
        if x + self.width() > screen.right() - 8:
            x = screen.right() - 8 - self.width()
        if y + self.height() > screen.bottom() - 8:
            y = top_left.y() - self.height() - 6       # above instead
        self.move(max(screen.left() + 8, x), y)
        self.show()
        self.raise_()


class InfoTip(QLabel):
    """A small (i) icon that explains a setting when hovered."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("InfoTip")
        # A little larger than the 14 px glyph, so it is easy to hit.
        self.setFixedSize(20, 20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text = text
        icons.bind(self, icons.G.INFO, "faint", 14)

    def enterEvent(self, e) -> None:
        icons.bind(self, icons.G.INFO, "accent", 14)
        _InfoPopup.get().show_for(self, self._text)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        icons.bind(self, icons.G.INFO, "faint", 14)
        _InfoPopup.hide_if_alive()
        super().leaveEvent(e)

    def hideEvent(self, e) -> None:
        # Switching page while hovering must not leave the bubble behind.
        _InfoPopup.hide_if_alive()
        super().hideEvent(e)


def with_info(widget: QWidget, info: str, stretch: bool = True) -> QHBoxLayout:
    """``widget`` followed by an (i) icon, e.g. for a checkbox."""
    lay = QHBoxLayout()
    lay.setSpacing(6)
    lay.addWidget(widget)
    lay.addWidget(InfoTip(info), 0, Qt.AlignmentFlag.AlignVCenter)
    if stretch:
        lay.addStretch()
    return lay


def label_with_info(text: str, info: str = "", name: str = "FieldLabel"):
    """A field label, with an (i) icon after it when ``info`` is given."""
    if not info:
        return label(text, name)
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lay.addWidget(label(text, name))
    lay.addWidget(InfoTip(info), 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addStretch()
    return w


# ---------------------------------------------------------------------------
# Key chips
# ---------------------------------------------------------------------------

class KeyCombo(QWidget):
    """A hotkey rendered as keyboard-key chips: [Ctrl] [F9]."""

    def __init__(self, hotkey: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(3)
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str) -> None:
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().setParent(None)   # gone now, not at next event loop
        parts = pretty_hotkey(hotkey) or ["—"]
        for p in parts:
            chip = QLabel(p)
            chip.setObjectName("KeyChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._lay.addWidget(chip)


# ---------------------------------------------------------------------------
# Status pill
# ---------------------------------------------------------------------------

class Pill(QLabel):
    """Rounded status label.  tone: idle | ok | accent | warn | danger | dim"""

    def __init__(self, text: str = "", tone: str = "idle", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Pill")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        set_prop(self, "tone", tone)

    def set(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card(QFrame):
    """A page section, in one of two looks:

    * **section** (default when it has a title): a hairline rule with a
      small uppercase title above the content; no box, no background.
    * **panel** (default without a title): a filled block without a border,
      for the few things that deserve emphasis, such as live read-outs.

    ``card.body`` is a QVBoxLayout for content; ``card.actions`` is a
    QHBoxLayout at the right of the title row for small header controls.
    ``glyph`` is accepted for compatibility but no longer drawn: icons in
    front of every section title made the pages look generic.
    """

    def __init__(self, title: str = "", subtitle: str = "",
                 glyph: Optional[str] = None, parent=None,
                 panel: Optional[bool] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        if panel is None:
            panel = not (title or subtitle)
        self.setProperty("variant", "panel" if panel else "section")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(self)
        if panel:
            outer.setContentsMargins(S5 - 4, S4 + 2, S5 - 4, S4 + 2)
        else:
            outer.setContentsMargins(0, S3 + 2, 0, S2)
        outer.setSpacing(S4 if panel else S3 + 2)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(S2)
        if title or subtitle:
            head = QHBoxLayout()
            head.setSpacing(S3)
            txt = QVBoxLayout()
            txt.setSpacing(3)
            self.title_label = label(title.upper(), "SectionTitle")
            txt.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = label(subtitle, "CardSubtitle", wrap=True)
                txt.addWidget(self.subtitle_label)
            head.addLayout(txt, 1)
            head.addLayout(self.actions)
            outer.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(S3)
        outer.addLayout(self.body)

    def grow(self) -> "Card":
        """Let the card take spare vertical space (for lists)."""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return self


# ---------------------------------------------------------------------------
# Form rows
# ---------------------------------------------------------------------------

class FormGrid(QGridLayout):
    """Two-column label | control grid with consistent spacing."""

    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalSpacing(S4)
        self.setVerticalSpacing(S3)
        self.setColumnStretch(1, 1)
        self._row = 0

    def add(self, text: str, widget, hint: str = "", info: str = ""):
        lbl = label_with_info(text, info)
        lbl.setMinimumWidth(110)
        self.addWidget(lbl, self._row, 0, Qt.AlignmentFlag.AlignVCenter)
        if isinstance(widget, QWidget):
            self.addWidget(widget, self._row, 1)
        else:
            self.addLayout(widget, self._row, 1)
        self._row += 1
        if hint:
            h = label(hint, "Hint", wrap=True)
            self.addWidget(h, self._row, 1)
            self._row += 1
        return lbl


def field(title: str, widget, hint: str = "", info: str = "") -> QVBoxLayout:
    """Label stacked above a control (a widget or a layout such as a row of
    controls), with an optional hint below and an (i) explanation."""
    lay = QVBoxLayout()
    lay.setSpacing(6)
    lay.addWidget(label_with_info(title, info))
    if isinstance(widget, QWidget):
        lay.addWidget(widget)
    else:
        lay.addLayout(widget)
    if hint:
        lay.addWidget(label(hint, "Hint", wrap=True))
    return lay


def hrow(*items, spacing: int = S2, stretch_end: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for it in items:
        if isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    if stretch_end:
        lay.addStretch()
    return lay


# ---------------------------------------------------------------------------
# Stat tile
# ---------------------------------------------------------------------------

class StatTile(QFrame):
    def __init__(self, caption: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Stat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S3, S2 + 2, S3, S2 + 2)
        lay.setSpacing(2)
        self.value = label(value, "StatValue")
        self.caption = label(caption, "StatLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set_value(self, v: str) -> None:
        self.value.setText(v)


# ---------------------------------------------------------------------------
# Segmented control
# ---------------------------------------------------------------------------

class Segmented(QFrame):
    """Exclusive row of checkable buttons; ``buttons`` keeps them in order."""

    def __init__(self, options: Sequence[str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: List[QPushButton] = []
        for opt in options:
            b = QPushButton(opt)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons.append(b)
        if self.buttons:
            self.buttons[0].setChecked(True)


# ---------------------------------------------------------------------------
# Responsive grid
# ---------------------------------------------------------------------------

class ResponsiveGrid(QWidget):
    """Lays its children out in as many columns as fit.

    Columns are added when each can be at least ``min_col_width`` wide and
    are capped at ``max_cols``.  Items can span several columns with
    ``add(widget, span=2)``.  Cards in the same row are top-aligned.
    """

    def __init__(self, min_col_width: int = 340, max_cols: int = 2,
                 spacing: int = S4, parent=None) -> None:
        super().__init__(parent)
        self._min = min_col_width
        self._max = max_cols
        self._items: List[tuple] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def add(self, widget: QWidget, span: int = 1) -> QWidget:
        # Ignore the preferred width so columns share space equally.
        sp = widget.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        widget.setSizePolicy(sp)
        self._items.append((widget, span))
        self._relayout(force=True)
        return widget

    def _columns_for(self, width: int) -> int:
        sp = self._grid.horizontalSpacing()
        n = max(1, (width + sp) // (self._min + sp))
        return int(min(self._max, n))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self, force: bool = False) -> None:
        cols = self._columns_for(self.width() or self._min * self._max)
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self._grid.count():
            self._grid.takeAt(0)
        for c in range(self._max):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
            self._grid.setColumnMinimumWidth(c, 0)
        row = col = 0
        for w, span in self._items:
            span = min(span, cols)
            if col + span > cols:
                row += 1
                col = 0
            self._grid.addWidget(w, row, col, 1, span, Qt.AlignmentFlag.AlignTop)
            col += span
            if col >= cols:
                row += 1
                col = 0
        self._grid.setRowStretch(row + 1, 1)


# ---------------------------------------------------------------------------
# "More below" scroll affordance
# ---------------------------------------------------------------------------

class _Fade(QWidget):
    """Gradient from transparent to the page colour, drawn over the bottom
    edge of a scroll area so cut-off content visibly continues."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:
        from PyQt6.QtGui import QColor, QLinearGradient, QPainter
        from src.ui import theme
        bg = QColor(theme.palette()["bg"])
        clear = QColor(bg)
        clear.setAlpha(0)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, clear)
        g.setColorAt(0.75, bg)
        g.setColorAt(1.0, bg)
        p = QPainter(self)
        p.fillRect(self.rect(), g)
        p.end()


class ScrollHint(QObject):
    """Adds a bottom fade and a clickable "More below" pill to a scroll area.

    Both appear only while there is content below the visible part and hide
    once the user reaches the end, so they never cover the last controls.
    """

    FADE_HEIGHT = 56

    def __init__(self, area: QScrollArea) -> None:
        super().__init__(area)
        self._area = area
        self._fade = _Fade(area)
        self._pill = QPushButton("More below", area)
        self._pill.setObjectName("ScrollHint")
        self._pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill.setToolTip("Scroll down for more options")
        icons.bind(self._pill, icons.G.CHEVRON_DOWN, "accent", 12)
        self._pill.clicked.connect(self._scroll_down)

        bar = area.verticalScrollBar()
        bar.valueChanged.connect(self._update)
        bar.rangeChanged.connect(lambda *_: self._update())
        area.installEventFilter(self)
        self._anim = None
        self._update()

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show,
                         QEvent.Type.LayoutRequest):
            self._update()
        return False

    def _update(self) -> None:
        bar = self._area.verticalScrollBar()
        more = bar.maximum() > 0 and bar.value() < bar.maximum() - 4
        vp = self._area.viewport().geometry()
        self._fade.setGeometry(vp.left(), vp.bottom() - self.FADE_HEIGHT + 1,
                               vp.width(), self.FADE_HEIGHT)
        self._pill.adjustSize()
        self._pill.move(vp.left() + (vp.width() - self._pill.width()) // 2,
                        vp.bottom() - self._pill.height() - 10)
        for w in (self._fade, self._pill):
            w.setVisible(more)
            if more:
                w.raise_()

    def _scroll_down(self) -> None:
        bar = self._area.verticalScrollBar()
        target = min(bar.maximum(), bar.value() + int(self._area.viewport().height() * 0.8))
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class Page(QScrollArea):
    """A scrollable page with a title header.

    Content goes into ``page.body`` (a QVBoxLayout).  ``page.header_actions``
    sits to the right of the title.  On very wide windows the content is
    centred and capped at ``max_width`` so lines don't get absurdly long.
    """

    def __init__(self, title: str, subtitle: str = "",
                 max_width: int = 1180, scroll: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if not scroll:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)

        content = QWidget()
        content.setObjectName("PageContent")
        content.setAutoFillBackground(False)
        outer = QHBoxLayout(content)
        outer.setContentsMargins(S6, S5 + 4, S6, S5)
        outer.setSpacing(0)

        column = QWidget()
        column.setMaximumWidth(max_width)
        column.setAutoFillBackground(False)
        outer.addStretch(0)
        outer.addWidget(column, 1)
        outer.addStretch(0)

        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(S5)

        head = QHBoxLayout()
        head.setSpacing(S4)
        txt = QVBoxLayout()
        txt.setSpacing(S1)
        txt.addWidget(label(title, "PageTitle"))
        if subtitle:
            txt.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        head.addLayout(txt, 1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(S2)
        head.addLayout(self.header_actions)
        col.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(S4)
        col.addLayout(self.body, 1)

        self.setWidget(content)
        if scroll:
            self.scroll_hint = ScrollHint(self)

    def fill(self) -> None:
        """Push content to the top (call after adding everything)."""
        self.body.addStretch(1)


def stack(*widgets: QWidget, spacing: int = S4) -> QWidget:
    """Vertical stack of widgets as a single widget (for grid cells)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x)
    return w
