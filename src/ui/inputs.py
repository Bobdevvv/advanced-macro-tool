"""
Typing-friendly numeric inputs.

Qt's spin boxes put units and special values ("∞ no limit", "0.100 s") inside
the editable text, which makes them awkward to type into.  These widgets keep
the text purely numeric and show the unit beside it instead:

* ``NumberEdit``   — a number with a fixed unit label ("%", "px", "×").
* ``DurationEdit`` — a number plus a unit picker (ms, seconds … days).
  Typing a unit letter after the number switches the picker: ``1m`` → 1 minute,
  ``5h`` → 5 hours, ``250ms`` → 250 milliseconds.
* ``CountEdit``    — a whole number plus a "No limit" toggle (value 0).

All of them accept a comma or a dot as the decimal separator, step with the
Up/Down keys or the mouse wheel (while focused), and fall back to the last
valid value if the text is left invalid.
"""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QToolTip, QWidget,
)

from src.ui.widgets import set_prop


def _fmt(v: float, decimals: int) -> str:
    """Format without trailing zeros: 1.50 → '1.5', 2.0 → '2'."""
    if decimals <= 0:
        return str(int(round(v)))
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return s or "0"


def _parse_number(text: str) -> Optional[float]:
    t = text.strip().replace(",", ".").replace(" ", "")
    if t in ("", ".", "-"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------------
# NumberEdit
# ---------------------------------------------------------------------------

class NumberEdit(QLineEdit):
    """A line edit for one number, with an optional unit label inside it."""

    valueChanged = pyqtSignal(float)

    def __init__(self, minimum: float = 0, maximum: float = 1e9,
                 decimals: int = 0, unit: str = "", value: float = 0,
                 parent=None) -> None:
        super().__init__(parent)
        self._min, self._max, self._dec = minimum, maximum, decimals
        self._value = float(value)
        self.setObjectName("Mono")
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(90)

        self._unit = QLabel(unit, self)
        self._unit.setObjectName("FieldUnit")
        self._unit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._unit.setVisible(bool(unit))

        self.textEdited.connect(self._on_edited)
        self.editingFinished.connect(self._normalise)
        self._show(self._value)

    # -- public API -----------------------------------------------------

    def value(self) -> float:
        return int(round(self._value)) if self._dec == 0 else self._value

    def setValue(self, v: float) -> None:          # noqa: N802 (Qt naming)
        v = self._clamp(v)
        changed = v != self._value
        self._value = v
        self._show(v)
        if changed:
            self.valueChanged.emit(self._value)

    def setRange(self, minimum: float, maximum: float) -> None:  # noqa: N802
        self._min, self._max = minimum, maximum
        self.setValue(self._value)

    def setUnit(self, unit: str) -> None:          # noqa: N802
        self._unit.setText(unit)
        self._unit.setVisible(bool(unit))
        self._place_unit()

    def setDecimals(self, decimals: int) -> None:  # noqa: N802
        self._dec = decimals

    # -- internals ------------------------------------------------------

    def _clamp(self, v: float) -> float:
        v = max(self._min, min(self._max, v))
        return round(v) if self._dec == 0 else round(v, self._dec)

    def _show(self, v: float) -> None:
        self.setText(_fmt(v, self._dec))
        set_prop(self, "invalid", "false")

    def _on_edited(self, text: str) -> None:
        v = _parse_number(self.number_text(text))
        ok = v is not None and self._min <= v <= self._max
        set_prop(self, "invalid", "false" if ok else "true")
        if ok:
            v = self._clamp(v)
            if v != self._value:
                self._value = v
                self.valueChanged.emit(v)

    def number_text(self, text: str) -> str:
        """The numeric part of the text (subclasses may strip extras)."""
        return text

    def _normalise(self) -> None:
        v = _parse_number(self.number_text(self.text()))
        if v is not None:
            self.setValue(v)
        else:
            self._show(self._value)

    def _step(self, direction: int) -> None:
        # Step by the last shown decimal place, so 0.25 steps by 0.01.
        txt = self.number_text(self.text()).replace(",", ".")
        places = len(txt.split(".")[1]) if "." in txt else 0
        step = 10 ** -min(places, self._dec) if self._dec else 1
        self.setValue(self._value + direction * step)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Up:
            self._step(+1)
        elif e.key() == Qt.Key.Key_Down:
            self._step(-1)
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e) -> None:
        if self.hasFocus():
            self._step(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
        else:
            e.ignore()          # let the page scroll

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_unit()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._place_unit()

    def _place_unit(self) -> None:
        # isHidden(), not isVisible(): a field on a page that is not on screen
        # yet is "invisible" but still has to position its unit label.
        if self._unit.isHidden():
            self.setTextMargins(0, 0, 0, 0)
            return
        self._unit.adjustSize()
        w = self._unit.width()
        self._unit.move(self.width() - w - 10, (self.height() - self._unit.height()) // 2)
        self.setTextMargins(0, 0, w + 6, 0)


# ---------------------------------------------------------------------------
# DurationEdit
# ---------------------------------------------------------------------------

# (label shown in the picker, seconds per unit, typed aliases)
_UNITS: List[Tuple[str, float, Tuple[str, ...]]] = [
    ("ms",      0.001, ("ms", "msec", "millis", "millisecond", "milliseconds")),
    ("seconds", 1,     ("s", "sec", "secs", "second", "seconds")),
    ("minutes", 60,    ("m", "min", "mins", "minute", "minutes")),
    ("hours",   3600,  ("h", "hr", "hrs", "hour", "hours")),
    ("days",    86400, ("d", "day", "days")),
]

_SHORT = {"ms": "ms", "seconds": "s", "minutes": "min", "hours": "h", "days": "d"}


def format_duration(seconds: float) -> str:
    """Compact, readable duration: 0.25 → '250 ms', 90 → '1.5 min'."""
    if seconds <= 0:
        return "0 s"
    label, per = _UNITS[0][0], _UNITS[0][1]
    for lbl, sec, _a in _UNITS:
        if seconds >= sec:
            label, per = lbl, sec
    return f"{_fmt(seconds / per, 2)} {_SHORT[label]}"


_TRAILING_UNIT = re.compile(r"^\s*([0-9]*[.,]?[0-9]*)\s*([a-zA-Z]+)\s*$")


def _unit_for_alias(alias: str) -> Optional[int]:
    a = alias.lower()
    for i, (_lbl, _sec, aliases) in enumerate(_UNITS):
        if a in aliases:
            return i
    return None


class _DurationNumber(NumberEdit):
    """NumberEdit that tolerates a trailing unit word while typing."""

    unit_typed = pyqtSignal(int)        # index into _UNITS

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        # Unit letters typed since editing started; read when editing ends,
        # after the letters have been stripped from the text.
        self.typed_unit: Optional[int] = None

    @staticmethod
    def _typed(text: str) -> Optional[int]:
        m = _TRAILING_UNIT.match(text)
        return _unit_for_alias(m.group(2)) if m else None

    def number_text(self, text: str) -> str:
        if self._typed(text) is not None:
            return _TRAILING_UNIT.match(text).group(1)
        return text

    def _on_edited(self, text: str) -> None:
        idx = self._typed(text)
        self.typed_unit = idx
        if idx is not None:
            # Switch the picker now; the letters stay until editing ends,
            # so "1m" can still grow into "1ms".
            self.unit_typed.emit(idx)
        super()._on_edited(text)


class DurationEdit(QWidget):
    """A time span: number + unit picker.  ``seconds()`` is the value."""

    valueChanged = pyqtSignal(float)    # seconds

    def __init__(self, minimum: float = 0.0, maximum: float = 86400.0,
                 seconds: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.number = _DurationNumber(0, 1e12, decimals=3)
        self.number.setToolTip(
            "Type a number, optionally followed by a unit:\n"
            "250ms · 1.5s · 2m · 1h · 1d"
        )
        self.unit = QComboBox()
        self.unit.setObjectName("UnitPicker")
        self.unit.setCursor(Qt.CursorShape.PointingHandCursor)
        for i, (label, sec, _a) in enumerate(_UNITS):
            if sec <= max(maximum, 0.001) or i == 0:
                self.unit.addItem(label, i)
        lay.addWidget(self.number, 1)
        lay.addWidget(self.unit)

        self.number.valueChanged.connect(self._emit)
        self.number.unit_typed.connect(self._select_unit)
        self.number.editingFinished.connect(self._finish)
        self.unit.currentIndexChanged.connect(self._on_unit_picked)

        self._seconds = -1.0
        self.setSeconds(seconds)

    # -- public API -----------------------------------------------------

    def seconds(self) -> float:
        return self._seconds

    def value(self) -> float:
        return self._seconds

    def setSeconds(self, s: float) -> None:        # noqa: N802
        s = max(self._min, min(self._max, float(s)))
        idx = self._best_unit(s)
        self.number.blockSignals(True)
        self.unit.blockSignals(True)
        self._set_unit_index(idx)
        self.number.setValue(s / _UNITS[idx][1])
        self.unit.blockSignals(False)
        self.number.blockSignals(False)
        self._emit()

    setValue = setSeconds

    # -- internals ------------------------------------------------------

    def _unit_index(self) -> int:
        return int(self.unit.currentData())

    def _set_unit_index(self, idx: int) -> None:
        pos = self.unit.findData(idx)
        if pos < 0:                      # unit not offered (range too small)
            pos = self.unit.count() - 1
        self.unit.setCurrentIndex(pos)

    def _best_unit(self, s: float) -> int:
        """Largest offered unit that shows the value as a tidy number."""
        best = 1 if self.unit.findData(1) >= 0 else 0
        if s == 0:
            return best
        for i in range(self.unit.count()):
            idx = int(self.unit.itemData(i))
            v = s / _UNITS[idx][1]
            if v >= 1 and abs(v - round(v, 3)) < 1e-9:
                best = idx
        return best

    def _select_unit(self, idx: int) -> None:
        # Units this field does not offer (e.g. minutes where the maximum is
        # 10 s) are resolved in _finish, when the user presses Enter.
        if self.unit.findData(idx) >= 0 and idx != self._unit_index():
            self.unit.blockSignals(True)
            self._set_unit_index(idx)
            self.unit.blockSignals(False)
            self._emit()

    def _on_unit_picked(self, _pos: int) -> None:
        # Keep the typed number; it now means a different amount of time.
        self._finish()

    def _finish(self) -> None:
        """Resolve what was typed into number + picker, clamped to range.

        Runs on Enter / focus-out and when a unit is picked.  The picker
        always ends up showing the unit the value is really in.
        """
        typed = self.number.typed_unit
        self.number.typed_unit = None
        unit = typed if typed is not None else self._unit_index()
        s = self.number.value() * _UNITS[unit][1]
        clamped = max(self._min, min(self._max, s))
        if clamped != s or self.unit.findData(unit) < 0:
            self.setSeconds(clamped)
            if clamped != s:
                QToolTip.showText(
                    self.mapToGlobal(QPoint(0, self.height())),
                    f"Allowed: {format_duration(self._min)} to "
                    f"{format_duration(self._max)}",
                    self,
                )
            return
        if unit != self._unit_index():
            self.unit.blockSignals(True)
            self._set_unit_index(unit)
            self.unit.blockSignals(False)
        self._emit()

    def _emit(self, *_args) -> None:
        s = self.number.value() * _UNITS[self._unit_index()][1]
        s = max(self._min, min(self._max, s))
        if s != self._seconds:
            self._seconds = s
            self.valueChanged.emit(s)


# ---------------------------------------------------------------------------
# CountEdit
# ---------------------------------------------------------------------------

class CountEdit(QWidget):
    """A whole number with a "No limit" toggle; ``value()`` is 0 for no limit."""

    valueChanged = pyqtSignal(int)

    def __init__(self, unit: str = "", unlimited_text: str = "No limit",
                 maximum: int = 9_999_999, value: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._unit_text = unit
        self.number = NumberEdit(1, maximum, decimals=0, unit=unit, value=max(1, value))
        self.number.setToolTip("Type a number. 0 means no limit.")
        self.toggle = QPushButton(f"∞  {unlimited_text}")
        self.toggle.setObjectName("UnlimitedToggle")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("Repeat without a limit until stopped")
        lay.addWidget(self.number, 1)
        lay.addWidget(self.toggle)

        # Typing 0 is a shortcut for "no limit".
        self.number.textEdited.connect(self._maybe_zero)
        self.number.valueChanged.connect(lambda *_: self._emit())
        self.toggle.toggled.connect(self._on_toggle)
        self._last = -1
        self.setValue(value)

    def value(self) -> int:
        return 0 if self.toggle.isChecked() else int(self.number.value())

    def setValue(self, v: int) -> None:            # noqa: N802
        self.toggle.blockSignals(True)
        self.toggle.setChecked(v == 0)
        self.toggle.blockSignals(False)
        if v > 0:
            self.number.setValue(v)
        self._sync()
        self._emit()

    def _maybe_zero(self, text: str) -> None:
        if text.strip() == "0" or text.strip() in ("∞", "inf"):
            self.number.setText("")
            self.toggle.setChecked(True)

    def _on_toggle(self, on: bool) -> None:
        self._sync()
        if not on:
            self.number.setFocus()
            self.number.selectAll()
        self._emit()

    def _sync(self) -> None:
        on = self.toggle.isChecked()
        self.number.setEnabled(not on)
        if on:
            self.number.setText("∞")
            self.number.setUnit("")
        else:
            self.number.setText(_fmt(self.number.value(), 0))
            self.number.setUnit(self._unit_text)

    def _emit(self) -> None:
        v = self.value()
        if v != self._last:
            self._last = v
            self.valueChanged.emit(v)
