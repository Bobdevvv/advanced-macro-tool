"""The editor's operations: integrity first, then each edit's arithmetic."""
import unittest

from tests import support  # noqa: F401
from src.core import editing as ed
from src.core.editing import Clip, EditError
from src.models.macro import MacroEvent as E


def kp(t, k="a", vk=0x41):
    return E("key_press", t, key=k, vk=vk)


def kr(t, k="a", vk=0x41):
    return E("key_release", t, key=k, vk=vk)


def cp(t, x=1, y=1):
    return E("mouse_click", t, x=x, y=y, button="left", pressed=True)


def cr(t, x=1, y=1):
    return E("mouse_click", t, x=x, y=y, button="left", pressed=False)


def balanced(events):
    """True if every release has a press before it and nothing stays held."""
    held = {}
    for e in events:
        ident = ed._identity(e)
        if ident is None:
            continue
        if ed._is_press(e):
            held[ident] = held.get(ident, 0) + 1
        elif ed._is_release(e):
            if not held.get(ident):
                return False
            held[ident] = 0
    return not any(held.values())


def times(events):
    return [round(e.timestamp, 6) for e in events]


class Integrity(unittest.TestCase):
    def test_normalize_drops_orphans_and_closes_presses(self):
        out = ed.normalize([kr(0.1), kp(0.2), cp(0.3)])
        self.assertTrue(balanced(out))
        self.assertEqual([e.type for e in out][:2], ["key_press", "mouse_click"])

    def test_old_ctrl_c_recordings_pair_up(self):
        press = E("key_press", 0.0, key="\x03")
        release = E("key_release", 0.1, key="c")
        self.assertEqual(ed.key_identity(press), ed.key_identity(release))
        self.assertTrue(balanced(ed.normalize([press, release])))

    def test_every_operation_keeps_macros_balanced(self):
        ev = [kp(0.0, "Key.ctrl_l", None), kp(0.5), kp(0.6), kp(0.7), kr(1.5),
              kr(2.0, "Key.ctrl_l", None), cp(2.5), cr(2.6),
              E("mouse_move", 2.8, x=5, y=5), kp(3.0, "b", 0x42), kr(3.2, "b", 0x42)]
        for a in (0.0, 0.3, 0.55, 1.0, 2.55, 3.1):
            for b in (a + 0.2, a + 1.0, 4.0):
                with self.subTest(a=a, b=b):
                    out, clip = ed.cut_range(ev, a, b)
                    self.assertTrue(balanced(out), "cut")
                    self.assertTrue(balanced(clip.events), "clip")
                    self.assertTrue(balanced(ed.paste(out, clip, a / 2)), "paste")
                    self.assertTrue(balanced(ed.move_range(ev, a, b, 3.9)), "move")
        for g in ed.gestures(ev):
            self.assertTrue(balanced(ed.delete_gestures(ev, [g])))
            self.assertTrue(balanced(ed.shift_gestures(ev, [g], -10)))


class Gestures(unittest.TestCase):
    def test_hold_with_repeats_is_one_gesture(self):
        gs = ed.gestures([kp(0.0), kp(0.1), kp(0.2), kr(0.5)])
        self.assertEqual(len(gs), 1)
        self.assertEqual((gs[0].kind, gs[0].start, gs[0].end, gs[0].label),
                         ("key", 0.0, 0.5, "A"))
        self.assertEqual(gs[0].indices, [0, 1, 2, 3])

    def test_shortcut_shows_two_overlapping_keys(self):
        gs = ed.gestures([kp(0.0, "Key.ctrl_l", None), kp(0.1, "vk:67", 67),
                          kr(0.2, "vk:67", 67), kr(0.3, "Key.ctrl_l", None)])
        self.assertEqual([g.label for g in gs], ["Ctrl", "C"])

    def test_clicks_scrolls_and_moves_group_sensibly(self):
        ev = [E("mouse_move", 0.0, x=0, y=0), E("mouse_move", 0.1, x=5, y=5),
              cp(0.2), cr(0.3), E("mouse_move", 0.4, x=9, y=9),
              E("mouse_scroll", 1.0, dx=0, dy=-1), E("mouse_scroll", 1.1, dx=0, dy=-1),
              E("mouse_scroll", 3.0, dx=0, dy=1)]
        kinds = [g.kind for g in ed.gestures(ev)]
        self.assertEqual(kinds.count("move"), 2)        # split by the click
        self.assertEqual(kinds.count("click"), 1)
        self.assertEqual(kinds.count("scroll"), 2)      # split by the pause


class Ranges(unittest.TestCase):
    def setUp(self):
        self.ev = [kp(1.0), kr(1.1), kp(2.0, "b", 0x42), kr(2.1, "b", 0x42),
                   kp(3.0, "c", 0x43), kr(3.1, "c", 0x43)]

    def test_cut_closes_the_gap(self):
        out, clip = ed.cut_range(self.ev, 1.5, 2.5)
        self.assertEqual(times(out), [1.0, 1.1, 2.0, 2.1])
        self.assertEqual(clip.length, 1.0)
        self.assertEqual(times(clip.events), [0.5, 0.6])

    def test_paste_pushes_later_events(self):
        clip = ed.copy_range(self.ev, 1.5, 2.5)
        out = ed.paste(self.ev, clip, 1.0)
        self.assertEqual(times(out)[:2], [1.5, 1.6])
        self.assertEqual(len(out), 8)
        self.assertEqual(ed.duration(out), 4.1)

    def test_move_section_earlier_and_later(self):
        later = ed.move_range(self.ev, 0.5, 1.5, 3.5)        # "a" to after "c"
        self.assertEqual([e.key for e in later if e.type == "key_press"], ["b", "c", "a"])
        earlier = ed.move_range(self.ev, 2.5, 3.5, 0.5)      # "c" to the front
        self.assertEqual([e.key for e in earlier if e.type == "key_press"], ["c", "a", "b"])

    def test_cutting_the_end_of_a_hold_releases_at_the_cut(self):
        ev = [kp(0.0), kr(2.0), kp(3.0, "b", 0x42), kr(3.1, "b", 0x42)]
        out, _ = ed.cut_range(ev, 1.0, 2.5)
        a_release = [e for e in out if e.type == "key_release" and e.key == "a"][0]
        self.assertEqual(a_release.timestamp, 1.0)

    def test_cutting_the_middle_of_a_hold_shortens_it(self):
        ev = [kp(0.0), kp(0.5), kp(1.0), kp(1.5), kr(2.0)]
        out, _ = ed.cut_range(ev, 0.75, 1.25)
        self.assertEqual(sum(e.type == "key_release" for e in out), 1)
        self.assertEqual(out[-1].timestamp, 1.5)

    def test_empty_range_is_refused(self):
        with self.assertRaises(EditError):
            ed.cut_range(self.ev, 1.0, 1.0)

    def test_insert_wait(self):
        out = ed.insert_gap(self.ev, 2.0, 5.0)
        self.assertEqual(times(out), [1.0, 1.1, 7.0, 7.1, 8.0, 8.1])


class GestureEdits(unittest.TestCase):
    def test_delete_and_shift_whole_gestures(self):
        ev = [kp(0.0), kp(0.1), kr(0.2), cp(1.0), cr(1.1)]
        g_key, g_click = ed.gestures(ev)
        self.assertEqual([e.type for e in ed.delete_gestures(ev, [g_key])],
                         ["mouse_click", "mouse_click"])
        moved = ed.shift_gestures(ev, [g_click], -5.0)        # clamped at 0
        self.assertEqual(times(moved)[:2], [0.0, 0.0])

    def test_hold_length_and_click_position(self):
        ev = [kp(0.0), kp(0.4), kp(0.8), kr(1.0), cp(2.0), cr(2.1)]
        g_key, g_click = ed.gestures(ev)
        shorter = ed.set_gesture_length(ev, g_key, 0.5)
        self.assertEqual(times([e for e in shorter if e.type.startswith("key")]), [0.0, 0.4, 0.5])
        moved = ed.set_click_position(ev, g_click, -1035, 40)
        self.assertEqual({(e.x, e.y) for e in moved if e.type == "mouse_click"}, {(-1035, 40)})


class Optimising(unittest.TestCase):
    def test_shorten_pauses_including_the_start(self):
        ev = [kp(5.0), kr(5.1), kp(9.0, "b", 0x42), kr(9.1, "b", 0x42)]
        out = ed.shorten_pauses(ev, 1.0, 0.5)
        self.assertEqual(times(out), [0.5, 0.6, 1.1, 1.2])

    def test_shorten_only_inside_a_range(self):
        ev = [kp(5.0), kr(5.1), kp(9.0, "b", 0x42), kr(9.1, "b", 0x42)]
        out = ed.shorten_pauses(ev, 1.0, 0.5, a=5.05, b=6.0)
        self.assertEqual(times(out), [5.0, 5.1, 5.6, 5.7])

    def test_shorten_rejects_nonsense(self):
        with self.assertRaises(EditError):
            ed.shorten_pauses([], 1.0, 2.0)

    def test_remove_mouse_moves(self):
        ev = [E("mouse_move", 0.0, x=0, y=0), cp(0.5), cr(0.6), E("mouse_move", 1.0, x=1, y=1)]
        self.assertEqual([e.type for e in ed.remove_mouse_moves(ev)], ["mouse_click"] * 2)
        self.assertEqual(len(ed.remove_mouse_moves(ev, 0.8, 2.0)), 3)


class Building(unittest.TestCase):
    def test_key_combo(self):
        clip = ed.key_combo_events("<ctrl>+c")
        self.assertEqual([(e.type, e.key) for e in clip.events],
                         [("key_press", "Key.ctrl_l"), ("key_press", "c"),
                          ("key_release", "c"), ("key_release", "Key.ctrl_l")])
        self.assertEqual(clip.events[1].vk, 0x43)
        self.assertTrue(balanced(clip.events))
        self.assertEqual(ed.key_combo_events("<f9>").events[0].key, "Key.f9")
        with self.assertRaises(EditError):
            ed.key_combo_events("<nope>")

    def test_text(self):
        clip = ed.text_events("Hi!\n")
        self.assertEqual([e.key for e in clip.events if e.type == "key_press"],
                         ["H", "i", "!", "Key.enter"])
        self.assertTrue(balanced(clip.events))
        with self.assertRaises(EditError):
            ed.text_events("")

    def test_repeat_and_limits(self):
        clip = Clip([kp(0.0), kr(0.1)], 1.0)
        self.assertEqual(times(ed.repeat(clip, 3).events), [0.0, 0.1, 1.0, 1.1, 2.0, 2.1])
        with self.assertRaises(EditError):
            ed.repeat(Clip([kp(0.0)] * 1000, 1.0), 10_000)


if __name__ == "__main__":
    unittest.main()
