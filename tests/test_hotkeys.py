"""Global hotkey parsing and matching (Windows key semantics simulated)."""
import unittest

import ctypes

from tests import support  # noqa: F401
from src.core.hotkey_manager import HotkeyManager, hotkey_error, parse, same_hotkey

# Windows virtual key codes, as the keyboard hook reports them.
LCTRL, RCTRL, LSHIFT, LALT = 0xA2, 0xA3, 0xA0, 0xA4
R, A, ONE = 0x52, 0x41, 0x31
F7, F9, F10 = 0x76, 0x78, 0x79


def _manager(*specs):
    hits = []
    m = HotkeyManager()
    m._combos = {parse(s): (lambda s=s: hits.append(s)) for s in specs}
    m._is_down = lambda vk: True             # no real keyboard to ask
    m._send_mask = lambda: hits.append("mask")
    return m, hits


def _press(m, keys, repeat=0, injected=False):
    """Press ``keys`` in order (held together), then release in reverse.
    Returns, per event, whether the key was kept from other programs."""
    blocked = [m.handle_key(vk, True, injected) for vk in keys]
    blocked += [m.handle_key(keys[-1], True, injected) for _ in range(repeat)]
    blocked += [m.handle_key(vk, False, injected) for vk in reversed(keys)]
    return blocked


def _fires(spec, keys, repeat=0, injected=False):
    m, hits = _manager(spec)
    _press(m, keys, repeat, injected)
    return len([h for h in hits if h != "mask"])


class Matching(unittest.TestCase):
    def test_modifier_combos_fire(self):
        self.assertEqual(_fires("<ctrl>+r", [LCTRL, R]), 1)
        self.assertEqual(_fires("<ctrl>+r", [RCTRL, R]), 1)
        self.assertEqual(_fires("<ctrl>+<shift>+1", [LCTRL, LSHIFT, ONE]), 1)
        self.assertEqual(_fires("<f9>", [F9]), 1)

    def test_modifiers_must_match_exactly(self):
        self.assertEqual(_fires("<f9>", [RCTRL, F9]), 0)
        self.assertEqual(_fires("<ctrl>+r", [R]), 0)

    def test_auto_repeat_fires_once(self):
        self.assertEqual(_fires("<f9>", [F9], repeat=5), 1)

    def test_simulated_input_never_fires(self):
        self.assertEqual(_fires("<f9>", [F9], injected=True), 0)

    def test_simulated_modifiers_do_not_change_what_matches(self):
        # A macro holding Ctrl must not stop F8 from stopping it.
        m, hits = _manager("<f9>")
        m.handle_key(LCTRL, True, True)            # injected Ctrl down
        m.handle_key(F9, True, False)
        self.assertEqual(hits, ["<f9>"])

    def test_a_missed_modifier_release_does_not_stick(self):
        # Windows can swallow a key-up (a UAC prompt, Ctrl+Alt+Del); the
        # manager checks the real key state before trusting its own record.
        m, hits = _manager("<f9>")
        m.handle_key(LCTRL, True, False)           # Ctrl down, its up is lost
        m._is_down = lambda vk: vk != LCTRL
        m.handle_key(F9, True, False)
        self.assertEqual(hits, ["<f9>"])


class Blocking(unittest.TestCase):
    """A hotkey belongs to AMT: other programs must not also act on it (F7
    toggles caret browsing in browsers, F10 opens menu bars)."""

    def test_a_hotkey_is_kept_from_other_programs_down_repeat_and_up(self):
        m, _ = _manager("<f7>")
        self.assertEqual(_press(m, [F7], repeat=3), [True] * 5)

    def test_other_combinations_of_the_same_key_pass_through(self):
        m, hits = _manager("<f7>")
        self.assertEqual(_press(m, [LCTRL, F7]), [False] * 4)
        self.assertEqual(hits, [])

    def test_unbound_keys_and_modifiers_are_never_blocked(self):
        m, _ = _manager("<ctrl>+r")
        self.assertEqual(_press(m, [A]), [False, False])
        blocked = _press(m, [LCTRL, R])
        self.assertEqual(blocked, [False, True, True, False])   # Ctrl itself passes

    def test_simulated_input_is_never_blocked(self):
        m, _ = _manager("<f7>")
        self.assertEqual(_press(m, [F7], injected=True), [False, False])

    def test_paused_while_binding_a_new_hotkey(self):
        m, hits = _manager("<f7>")
        m.pause()
        self.assertEqual(_press(m, [F7]), [False, False])
        m.resume()
        self.assertEqual(_press(m, [F7]), [True, True])
        self.assertEqual(hits, ["<f7>"])

    def test_alt_and_win_combos_mask_the_modifier_tap(self):
        # Blocking the R of Alt+R leaves the app a lone Alt tap, which opens
        # its menu bar (a lone Win tap opens Start); a neutral key masks it.
        m, hits = _manager("<alt>+r", "<f7>")
        _press(m, [LALT, R])
        self.assertEqual(sorted(hits), ["<alt>+r", "mask"])
        hits.clear()
        _press(m, [F7])
        self.assertEqual(hits, ["<f7>"])

    def test_through_pynputs_real_filter(self):
        # The same path the Windows hook takes, without installing a hook.
        from pynput import keyboard
        from pynput._util.win32 import SystemHook
        m, hits = _manager("<f7>")
        kl = keyboard.Listener(win32_event_filter=m._filter)
        m._listener = kl
        Struct = kl._KBDLLHOOKSTRUCT

        def event(vk, msg, flags=0):
            data = Struct(vk, 0, flags, 0, None)
            return kl._convert(SystemHook.HC_ACTION, msg, ctypes.pointer(data))

        with self.assertRaises(SystemHook.SuppressException):
            event(F7, 0x0100)                            # WM_KEYDOWN: kept
        self.assertEqual(hits, ["<f7>"])
        self.assertIsNone(event(A, 0x0100))              # passes, unhandled
        self.assertIsNone(event(F7, 0x0101, flags=0x10))  # injected: passes
        with self.assertRaises(SystemHook.SuppressException):
            event(F7, 0x0101)                            # WM_KEYUP: kept
        self.assertIsNone(event(F10, 0x0104))            # WM_SYSKEYDOWN, unbound

    def test_one_bad_hotkey_does_not_disable_the_others(self):
        support.stub_global_input()
        m = HotkeyManager()
        m.set_bindings({"<f9>": lambda: None, "<ctrl>+<nope>": lambda: None})
        self.assertEqual(len(m._combos), 1)
        self.assertEqual(len(m.errors), 1)


class Validation(unittest.TestCase):
    def test_typing_keys_need_ctrl_alt_or_win(self):
        # A hotkey is kept from other programs, so "r" alone would make it
        # impossible to type an r anywhere.
        for bad in ("r", "1", "<shift>+r", "<space>", "<enter>", "<tab>", ";"):
            with self.subTest(bad=bad):
                self.assertIn("Ctrl", hotkey_error(bad) or "")
        for good in ("<ctrl>+r", "<alt>+1", "<cmd>+<space>", "<f7>", "<shift>+<f7>",
                     "<pause>", "<ctrl>+<shift>+1"):
            with self.subTest(good=good):
                self.assertIsNone(hotkey_error(good))

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
