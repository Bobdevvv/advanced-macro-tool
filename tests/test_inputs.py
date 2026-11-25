"""Number, duration and count fields, as a user types into them."""
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QStackedWidget, QWidget, QVBoxLayout

from tests import support
from src.ui.inputs import CountEdit, DurationEdit, NumberEdit, format_duration

support.qapp()


def type_into(edit, text, enter=True):
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, text)
    if enter:
        QTest.keyClick(edit, Qt.Key.Key_Return)
    support.pump(2)


class Durations(unittest.TestCase):
    def setUp(self):
        self.d = DurationEdit(0, 7 * 86400, seconds=0)
        self.d.show()

    def tearDown(self):
        self.d.close()

    def check(self, text, number, unit, seconds, field=None):
        f = field or self.d
        type_into(f.number, text)
        self.assertEqual((f.number.text(), f.unit.currentText(), f.seconds()),
                         (number, unit, seconds), text)

    def test_unit_letters(self):
        self.check("1m", "1", "minutes", 60)
        self.check("5h", "5", "hours", 18000)
        self.check("250ms", "250", "ms", 0.25)       # "m" grows into "ms"
        self.check("1,5s", "1.5", "seconds", 1.5)    # comma decimal
        self.check("2d", "2", "days", 172800)
        self.check("3", "3", "days", 259200)         # bare number keeps unit

    def test_out_of_range_clamps_and_updates_picker(self):
        small = DurationEdit(0, 10, seconds=0)
        small.show()
        self.check("1m", "10", "seconds", 10, field=small)   # minutes not offered
        self.check("30d", "10", "seconds", 10, field=small)
        lo = DurationEdit(0.01, 86400, seconds=1)
        lo.show()
        self.check("1ms", "10", "ms", 0.01, field=lo)

    def test_invalid_text_reverts(self):
        type_into(self.d.number, "2s")
        type_into(self.d.number, "abc", enter=False)
        self.assertEqual(self.d.number.property("invalid"), "true")
        QTest.keyClick(self.d.number, Qt.Key.Key_Return)
        self.assertEqual(self.d.number.text(), "2")

    def test_picking_a_unit_keeps_the_number(self):
        type_into(self.d.number, "7s")
        self.d.unit.setCurrentIndex(self.d.unit.findText("minutes"))
        self.assertEqual(self.d.seconds(), 420)

    def test_loaded_values_use_a_tidy_unit(self):
        self.d.setSeconds(0.1)
        self.assertEqual((self.d.number.text(), self.d.unit.currentText()), ("100", "ms"))

    def test_format(self):
        self.assertEqual(format_duration(3600), "1 h")
        self.assertEqual(format_duration(0.25), "250 ms")
        self.assertEqual(format_duration(90), "1.5 min")


class Counts(unittest.TestCase):
    def test_zero_means_no_limit_and_back(self):
        c = CountEdit(unit="times", value=1)
        c.show()
        type_into(c.number, "25")
        self.assertEqual(c.value(), 25)
        type_into(c.number, "0", enter=False)
        self.assertEqual(c.value(), 0)
        self.assertTrue(c.toggle.isChecked())
        c.toggle.click()
        self.assertEqual(c.value(), 25)


class UnitLabel(unittest.TestCase):
    def test_unit_is_placed_even_if_built_on_a_hidden_page(self):
        """Regression: the % sign stuck in the top-left corner when the field
        was created on a page that was not on screen yet."""
        stack = QStackedWidget()
        stack.resize(500, 300)
        first, second = QWidget(), QWidget()
        lay = QVBoxLayout(second)
        field = NumberEdit(0, 80, decimals=1, unit="%", value=25)
        lay.addWidget(field)
        stack.addWidget(first)
        stack.addWidget(second)
        stack.show()
        support.pump()
        stack.setCurrentIndex(1)
        support.pump()
        u = field._unit
        self.assertGreater(u.x(), field.width() // 2)
        self.assertLessEqual(abs(u.y() + u.height() / 2 - field.height() / 2), 2)
        self.assertGreater(field.textMargins().right(), 0)
        stack.close()

    def test_up_down_keys_step(self):
        n = NumberEdit(0, 30, 1, "%", 5)
        n.show()
        n.setFocus()
        QTest.keyClick(n, Qt.Key.Key_Up)
        self.assertEqual(n.value(), 6)


if __name__ == "__main__":
    unittest.main()
