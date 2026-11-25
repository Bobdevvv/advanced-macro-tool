"""Keyboard shortcuts and held keys, end to end.

Recording is fed exactly what pynput's Windows listener delivers (including
the control characters letters report while Ctrl is held), saved to a real
file, loaded back and played into a fake keyboard.  The last step checks the
Windows input event pynput would send, so "Ctrl+C plays as Ctrl+C" is tested
all the way to SendInput's parameters.
"""
import os
import threading
import time
import unittest
import unittest.mock

from pynput.keyboard import Key, KeyCode

from tests import support
from src.core.player import Player, _event_key, _str_to_key
from src.core.recorder import Recorder
from src.models.macro import Macro, MacroEvent as E

# What pynput's Windows listener reports for these keys:
CTRL = Key.ctrl_l
C_WITH_CTRL = KeyCode(char="\x03", vk=0x43)   # Ctrl changes C's character
V_WITH_CTRL = KeyCode(char="\x16", vk=0x56)
A_KEY = KeyCode(char="a", vk=0x41)


class _TimedKeyboard(support.FakeKeyboard):
    def __init__(self):
        super().__init__()
        self.t0 = time.perf_counter()

    def press(self, key):
        self.log.append(("press", key, time.perf_counter() - self.t0))

    def release(self, key):
        self.log.append(("release", key, time.perf_counter() - self.t0))


def _record(feed):
    """Run ``feed(recorder)`` as a recording; return the saved+reloaded macro."""
    r = Recorder()
    r._start_listeners = lambda: None
    r._stop_listeners = lambda: None
    r.start("t")
    feed(r)
    macro = r.stop()
    path = os.path.join(support.fresh_dir("kbd"), "t.json")
    macro.save(path)
    return Macro.load(path)


def _play(macro):
    p = Player()
    p._mouse, p._keyboard = support.FakeMouse(), _TimedKeyboard()
    done = threading.Event()
    p.on_finish = done.set
    p.play(macro)
    if not done.wait(5):
        raise AssertionError("playback did not finish")
    return p._keyboard.log


def _windows_vk(key):
    """The wVk pynput would put in the SendInput event for this key."""
    return key._parameters(True)["wVk"]


class Shortcuts(unittest.TestCase):
    def _copy_paste(self, r):
        for key in (CTRL, C_WITH_CTRL):
            r._on_key_press(key)
        for key in (C_WITH_CTRL, CTRL):
            r._on_key_release(key)
        for key in (CTRL, V_WITH_CTRL):
            r._on_key_press(key)
        for key in (V_WITH_CTRL, CTRL):
            r._on_key_release(key)

    def test_ctrl_c_ctrl_v_replay_as_the_real_keys(self):
        log = _play(_record(self._copy_paste))
        presses = [k for kind, k, _t in log if kind == "press"]
        self.assertEqual(presses, [Key.ctrl_l, KeyCode.from_vk(0x43),
                                   Key.ctrl_l, KeyCode.from_vk(0x56)])
        # What Windows receives: the C and V keys, not virtual key 3
        # (Ctrl+Break) and 22, which the control characters used to become.
        self.assertEqual([_windows_vk(k) for k in presses[1::2]], [0x43, 0x56])

    def test_saved_file_is_readable(self):
        m = _record(self._copy_paste)
        keys = [e.key for e in m.events if e.type == "key_press"]
        self.assertEqual(keys, ["Key.ctrl_l", "vk:67", "Key.ctrl_l", "vk:86"])

    def test_shift_and_numbers_replay_by_physical_key(self):
        shift_1 = KeyCode(char="!", vk=0x31)
        m = _record(lambda r: (r._on_key_press(Key.shift), r._on_key_press(shift_1),
                               r._on_key_release(shift_1), r._on_key_release(Key.shift)))
        presses = [k for kind, k, _t in _play(m) if kind == "press"]
        self.assertEqual(presses, [Key.shift, KeyCode.from_vk(0x31)])

    def test_recordings_from_older_versions_are_repaired(self):
        """Old files stored the control character; it must replay as the letter."""
        old = Macro("old", [E("key_press", 0.0, key="Key.ctrl_l"),
                            E("key_press", 0.01, key="\x03"),
                            E("key_release", 0.02, key="\x03"),
                            E("key_release", 0.03, key="Key.ctrl_l")])
        presses = [k for kind, k, _t in _play(old) if kind == "press"]
        self.assertEqual(presses[1], KeyCode.from_vk(0x43))
        self.assertEqual(_windows_vk(_str_to_key("\x16")), 0x56)

    def test_unprintable_characters_without_a_letter_are_skipped(self):
        self.assertIsNone(_str_to_key("\x1b"))
        self.assertIsNone(_event_key(E("key_press", 0, key="\x7f")))


class HeldKeys(unittest.TestCase):
    """A held key is a press, Windows' auto-repeat presses, then one release."""

    def _hold_a(self, r, seconds=0.4, repeats=8):
        r._on_key_press(A_KEY)
        for _ in range(repeats):                    # auto-repeat while held
            time.sleep(seconds / (repeats + 1))
            r._on_key_press(A_KEY)
        time.sleep(seconds / (repeats + 1))
        r._on_key_release(A_KEY)

    def test_hold_is_recorded_as_press_and_hold_not_a_click(self):
        m = _record(self._hold_a)
        kinds = [e.type for e in m.events]
        self.assertEqual(kinds, ["key_press"] * 9 + ["key_release"])
        self.assertGreaterEqual(m.events[-1].timestamp - m.events[0].timestamp, 0.35)

    def test_playback_holds_for_the_recorded_time(self):
        log = _play(_record(self._hold_a))
        first_press = log[0][2]
        release = [t for kind, _k, t in log if kind == "release"][0]
        self.assertGreaterEqual(release - first_press, 0.33)   # held, not tapped
        self.assertEqual(sum(1 for kind, *_ in log if kind == "press"), 9)
        self.assertEqual(sum(1 for kind, *_ in log if kind == "release"), 1)


class TypingRhythm(unittest.TestCase):
    """Humanised typing: natural variation, but the keys stay the keys."""

    def typed(self):
        ev, t = [], 0.0
        for ch in "hello world":
            ev += [E("key_press", t, key=ch), E("key_release", t + 0.08, key=ch)]
            t += 0.15
        return ev

    def keys(self, events):
        return [(e.type, e.key) for e in events if e.type.startswith("key")]

    def test_zero_leaves_typing_exactly_as_recorded(self):
        from src.core.humanizer import vary_typing
        ev = self.typed()
        self.assertEqual(vary_typing(ev, 0), ev)

    def test_order_never_changes_and_rhythm_varies(self):
        from src.core.humanizer import vary_typing
        ev = self.typed()
        runs = [vary_typing(ev, 0.3) for _ in range(5)]
        for out in runs:
            self.assertEqual(self.keys(out), self.keys(ev))      # same keys, same order
            ts = [e.timestamp for e in out]
            self.assertEqual(ts, sorted(ts))
        holds = {round(r[1].timestamp - r[0].timestamp, 4) for r in runs}
        gaps = {round(r[2].timestamp - r[1].timestamp, 4) for r in runs}
        self.assertGreater(len(holds), 1, "hold times should vary between runs")
        self.assertGreater(len(gaps), 1, "gaps between keys should vary between runs")

    def test_shortcut_stays_a_shortcut(self):
        from src.core.humanizer import vary_typing
        ev = [E("key_press", 0.0, key="Key.ctrl_l"), E("key_press", 0.05, key="c", vk=67),
              E("key_release", 0.1, key="c", vk=67), E("key_release", 0.12, key="Key.ctrl_l")]
        for _ in range(50):
            out = vary_typing(ev, 0.5)
            self.assertEqual(self.keys(out), self.keys(ev))      # Ctrl down before C …

    def test_typing_never_runs_past_the_next_click_and_mouse_stays(self):
        from src.core.humanizer import vary_typing
        ev = self.typed()
        click_t = ev[-1].timestamp + 0.01
        ev += [E("mouse_click", click_t, x=5, y=5, button="left", pressed=True),
               E("mouse_click", click_t + 0.1, x=5, y=5, button="left", pressed=False)]
        for _ in range(50):
            out = vary_typing(ev, 0.6)
            last_key = max(e.timestamp for e in out if e.type.startswith("key"))
            self.assertLess(last_key, click_t)
            clicks = [e for e in out if e.type == "mouse_click"]
            self.assertEqual([c.timestamp for c in clicks], [click_t, click_t + 0.1])

    def test_player_applies_it_when_humanising(self):
        p = Player()
        p.humanize = True
        p.humanizer.typing_variation = 0.3
        p.humanizer.timing_jitter = 0
        p._mouse, p._keyboard = support.FakeMouse(), _TimedKeyboard()
        ev = self.typed()
        with unittest.mock.patch("src.core.humanizer.vary_typing",
                                 wraps=__import__("src.core.humanizer", fromlist=["x"]).vary_typing) as vt:
            done = threading.Event()
            p.on_finish = done.set
            p.play(Macro("m", ev))
            self.assertTrue(done.wait(5))
        self.assertTrue(vt.called)
        self.assertEqual(vt.call_args.args[1], 0.3)


if __name__ == "__main__":
    unittest.main()
