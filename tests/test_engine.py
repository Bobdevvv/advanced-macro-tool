"""Playback, clicker, recorder clean-up, composer and humaniser (no Qt)."""
import threading
import time
import unittest

from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from tests import support
from src.core.autoclicker import AutoClicker
from src.core.humanizer import Humanizer
from src.core.player import Player, _str_to_key
from src.core.recorder import clean_edges
from src.models.macro import Macro, MacroEvent as E


def _player():
    p = Player()
    p._mouse, p._keyboard = support.FakeMouse(), support.FakeKeyboard()
    return p


def _run(p, macro, timeout=5.0):
    done = threading.Event()
    p.on_finish = done.set
    p.play(macro)
    if not done.wait(timeout):
        raise AssertionError("player did not finish")


class KeyNames(unittest.TestCase):
    def test_known_names(self):
        self.assertEqual(_str_to_key("a"), KeyCode.from_char("a"))
        self.assertEqual(_str_to_key("Key.f9"), Key.f9)
        self.assertEqual(_str_to_key("vk:65"), KeyCode.from_vk(65))

    def test_unknown_names_are_skipped_not_guessed(self):
        for s in ("Key.bogus", "vk:x", "", None, "weird"):
            with self.subTest(s=s):
                self.assertIsNone(_str_to_key(s))


class Playback(unittest.TestCase):
    def test_click_goes_to_its_recorded_position(self):
        p = _player()
        _run(p, Macro("m", [E("mouse_click", 0.0, x=40, y=-30, button="left", pressed=True),
                            E("mouse_click", 0.01, x=40, y=-30, button="left", pressed=False)]))
        self.assertIn(("move", (40, -30)), p._mouse.log)
        self.assertIn(("press", Button.left, (40, -30)), p._mouse.log)

    def test_unknown_key_is_not_typed(self):
        p = _player()
        _run(p, Macro("m", [E("key_press", 0.0, key="Key.bogus"),
                            E("key_release", 0.01, key="Key.bogus")]))
        self.assertEqual(p._keyboard.log, [])

    def test_stop_releases_held_keys_and_buttons(self):
        p = _player()
        started = threading.Event()
        p.on_event = lambda i, n: started.set()
        done = threading.Event()
        p.on_finish = done.set
        p.play(Macro("m", [E("key_press", 0.0, key="a"),
                           E("mouse_click", 0.0, x=1, y=1, button="left", pressed=True),
                           E("key_release", 30.0, key="a")]))
        self.assertTrue(started.wait(2))
        p.stop()
        self.assertTrue(done.wait(2), "stop must end a long wait at once")
        self.assertIn(("release", KeyCode.from_char("a")), p._keyboard.log)
        self.assertTrue(any(e[0] == "release" for e in p._mouse.log))

    def test_error_mid_playback_still_finishes_and_releases(self):
        p = _player()
        calls = []

        def boom(i, n):
            if i == 1:
                raise RuntimeError("synthetic failure")
        p.on_event = boom
        finished = threading.Event()
        p.on_finish = lambda: (calls.append("finish"), finished.set())
        old_hook = threading.excepthook
        threading.excepthook = lambda args: calls.append("reported")
        try:
            p.play(Macro("m", [E("key_press", 0.0, key="a"), E("key_release", 0.1, key="a")]))
            self.assertTrue(finished.wait(2))
            time.sleep(0.05)
        finally:
            threading.excepthook = old_hook
        self.assertIn("finish", calls)
        self.assertIn("reported", calls)
        self.assertIn(("release", KeyCode.from_char("a")), p._keyboard.log)


class Clicker(unittest.TestCase):
    def _clicker(self, **kw):
        c = AutoClicker()
        c._mouse = support.FakeMouse()
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_stops_at_limit_and_reports(self):
        c = self._clicker(interval=0.01, hold_duration=0.001, click_limit=3)
        done = threading.Event()
        c.on_stop = done.set
        c.start()
        self.assertTrue(done.wait(2))
        self.assertEqual(c.clicks_done, 3)

    def test_fixed_point_may_be_negative(self):
        c = self._clicker(interval=0.01, hold_duration=0.001, click_limit=1,
                          use_fixed_pos=True, fixed_x=-1035, fixed_y=40)
        done = threading.Event()
        c.on_stop = done.set
        c.start()
        self.assertTrue(done.wait(2))
        self.assertIn(("move", (-1035, 40)), c._mouse.log)

    def test_button_never_left_held_on_error(self):
        c = self._clicker(interval=0.01, hold_duration=0.001)
        c.on_click = lambda n: (_ for _ in ()).throw(RuntimeError("x"))
        done = threading.Event()
        c.on_stop = done.set
        old_hook = threading.excepthook
        threading.excepthook = lambda args: None
        try:
            c.start()
            self.assertTrue(done.wait(2))
        finally:
            threading.excepthook = old_hook
        presses = sum(1 for e in c._mouse.log if e[0] == "press")
        releases = sum(1 for e in c._mouse.log if e[0] == "release")
        self.assertEqual(presses, releases)


class RecordingEdges(unittest.TestCase):
    def test_orphan_release_from_start_button_is_dropped(self):
        ev = [E("mouse_click", 0.0, x=5, y=5, button="left", pressed=False),
              E("key_press", 0.1, key="a")]
        self.assertEqual([e.type for e in clean_edges(ev, False)], ["key_press"])

    def test_stop_button_click_is_dropped(self):
        ev = [E("mouse_click", 0.1, x=1, y=1, button="left", pressed=True),
              E("mouse_click", 0.2, x=1, y=1, button="left", pressed=False),
              E("key_press", 0.3, key="a"),
              E("mouse_move", 0.4, x=9, y=9),
              E("mouse_click", 0.5, x=9, y=9, button="left", pressed=True),
              E("mouse_click", 0.6, x=9, y=9, button="left", pressed=False)]
        out = clean_edges(ev, True)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[-1].type, "mouse_move")

    def test_hotkey_stop_keeps_the_last_click(self):
        ev = [E("mouse_click", 0.1, x=1, y=1, button="left", pressed=True),
              E("mouse_click", 0.2, x=1, y=1, button="left", pressed=False)]
        self.assertEqual(len(clean_edges(ev, False)), 2)


class RecorderInput(unittest.TestCase):
    def test_only_real_user_input_is_recorded(self):
        from src.core.recorder import Recorder
        r = Recorder()
        r._start_listeners = lambda: None
        r._stop_listeners = lambda: None
        r.start("t")
        r._on_key_press(KeyCode.from_char("a"), False)
        r._on_key_press(KeyCode.from_char("b"), True)           # simulated
        r._on_click(1, 1, Button.left, True, True)              # simulated
        r._on_move(50, 50, True)                                # simulated
        m = r.stop()
        self.assertEqual([e.key for e in m.events], ["a"])

    def test_injected_flag_reaches_the_recorder_through_pynput(self):
        """Guards the assumption above end to end: call pynput's listeners
        exactly as its Windows backend does (``on_press(key, injected)``,
        ``on_click(x, y, button, pressed, injected)``)."""
        from pynput import keyboard, mouse
        from src.core.recorder import Recorder
        r = Recorder()
        r._start_listeners = lambda: None
        r._stop_listeners = lambda: None
        r.start("t")
        kl = keyboard.Listener(on_press=r._on_key_press)
        ml = mouse.Listener(on_click=r._on_click)
        kl.on_press(KeyCode.from_char("x"), True)
        kl.on_press(KeyCode.from_char("y"), False)
        ml.on_click(5, 5, Button.left, True, True)
        ml.on_click(6, 6, Button.left, True, False)
        events = r.stop().events
        self.assertEqual([e.key for e in events if e.type == "key_press"], ["y"])
        self.assertEqual([(e.x, e.y) for e in events if e.type == "mouse_click"], [(6, 6)])

    def test_injected_flag_reaches_the_hotkey_matcher_through_pynput(self):
        from pynput import keyboard
        from src.core.hotkey_manager import HotkeyManager, parse
        hits = []
        m = HotkeyManager()
        m._combos = {parse("<f9>"): lambda: hits.append(1)}
        kl = keyboard.Listener(on_press=m._on_press, on_release=m._on_release)
        kl.on_press(Key.f9, True)
        kl.on_release(Key.f9, True)
        self.assertEqual(hits, [])
        kl.on_press(Key.f9, False)
        self.assertEqual(hits, [1])


class Humanise(unittest.TestCase):
    def setUp(self):
        self.events = [E("mouse_move", 0.0, x=0, y=0), E("mouse_move", 0.5, x=200, y=0),
                       E("mouse_click", 1.0, x=300, y=100, button="left", pressed=True),
                       E("mouse_click", 1.1, x=300, y=100, button="left", pressed=False),
                       E("mouse_move", 2.0, x=0, y=300)]

    def test_clicks_keep_their_exact_positions(self):
        h = Humanizer()
        h.mouse_noise = 5
        out = h.apply(self.events)
        clicks = [(e.x, e.y) for e in out if e.type == "mouse_click"]
        self.assertEqual(clicks, [(300, 100), (300, 100)])

    def test_output_is_in_time_order_and_non_negative(self):
        out = Humanizer().apply(self.events)
        ts = [e.timestamp for e in out]
        self.assertEqual(ts, sorted(ts))
        self.assertGreaterEqual(min(ts), 0.0)

    def test_zero_noise_path_ends_on_target(self):
        h = Humanizer()
        h.mouse_noise = 0
        out = h.apply(self.events)
        moves_before_click = [e for e in out if e.type == "mouse_move" and e.timestamp <= 1.0]
        self.assertEqual((moves_before_click[-1].x, moves_before_click[-1].y), (300, 100))


if __name__ == "__main__":
    unittest.main()
