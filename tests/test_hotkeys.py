"""Global hotkey parsing and matching (Windows key semantics simulated)."""
import unittest

from pynput.keyboard import Key, KeyCode

from tests import support  # noqa: F401
from src.core.hotkey_manager import HotkeyManager, hotkey_error, parse, same_hotkey

# What pynput's Windows listener really delivers for these keys:
CTRL_R = [Key.ctrl_l, KeyCode(char="\x12", vk=82)]   # Ctrl changes the char
SHIFT_1 = [Key.shift, KeyCode(char="!", vk=49)]      # Shift changes the char
F9 = [Key.f9]


def _fires(spec, presses, repeat=0, injected=False):
    hits = []
    m = HotkeyManager()
    m._combos = {parse(spec): lambda: hits.append(1)}
    for k in presses:
        m._on_press(k, injected)
    for _ in range(repeat):                  # keyboard auto-repeat
        m._on_press(presses[-1], injected)
    for k in reversed(presses):
        m._on_release(k, injected)
    return len(hits)


class Matching(unittest.TestCase):
    def test_modifier_combos_fire_despite_changed_characters(self):
        self.assertEqual(_fires("<ctrl>+r", CTRL_R), 1)
        self.assertEqual(_fires("<shift>+1", SHIFT_1), 1)
        self.assertEqual(_fires("<f9>", F9), 1)

    def test_modifiers_must_match_exactly(self):
        self.assertEqual(_fires("<f9>", [Key.ctrl_r, Key.f9]), 0)
        self.assertEqual(_fires("<ctrl>+r", [KeyCode(char="r", vk=82)]), 0)

    def test_auto_repeat_fires_once(self):
        self.assertEqual(_fires("<f9>", F9, repeat=5), 1)

    def test_simulated_input_never_fires(self):
        self.assertEqual(_fires("<f9>", F9, injected=True), 0)

    def test_one_bad_hotkey_does_not_disable_the_others(self):
        support.stub_global_input()
        m = HotkeyManager()
        m.set_bindings({"<f9>": lambda: None, "<ctrl>+<nope>": lambda: None})
        self.assertEqual(len(m._combos), 1)
        self.assertEqual(len(m.errors), 1)


class Validation(unittest.TestCase):
    def test_errors(self):
        for bad in ("", "<ctrl>", "<nope>", "ab", "<f9>+<f10>", "<ctrl>++r"):
            with self.subTest(bad=bad):
                self.assertIsNotNone(hotkey_error(bad))
        for good in ("<f9>", "<ctrl>+r", "<ctrl>+<shift>+1", "<pause>", "<cmd>+<f12>"):
            with self.subTest(good=good):
                self.assertIsNone(hotkey_error(good))

    def test_same_hotkey_ignores_spelling(self):
        self.assertTrue(same_hotkey("<ctrl>+r", "<CTRL>+R"))
        self.assertTrue(same_hotkey("<ctrl_l>+r", "<ctrl>+r"))
        self.assertFalse(same_hotkey("<f9>", "<ctrl>+<f9>"))


if __name__ == "__main__":
    unittest.main()
