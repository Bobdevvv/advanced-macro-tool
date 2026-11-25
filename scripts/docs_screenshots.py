"""
Regenerate every screenshot in docs/images.

    python scripts/docs_screenshots.py

Runs AMT in a temporary AMT_HOME with hand-made demo macros, so no real
macro, setting or file path ever ends up in a published image, and puts each
page in the state its caption in docs/GUIDE.md describes.  Pages longer than
the window get a second, scrolled screenshot ("…-lower.png") so the guide
can show everything, not just the top of the page.

Review the images before committing them: they are published.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import support  # noqa: E402  (isolated AMT_HOME first)

from PyQt6.QtCore import QLocale  # noqa: E402

# English number formatting in published images, whatever this PC uses.
QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
support.qapp()
support.stub_global_input()

from src import app_paths  # noqa: E402
from src.models.macro import Macro, MacroEvent as E  # noqa: E402
from src.storage.macro_store import MacroStore  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402

# AMT_SCREENSHOT_DIR lets the test suite run this into a temporary folder.
OUT = os.environ.get("AMT_SCREENSHOT_DIR") or os.path.join(ROOT, "docs", "images")
SIZE = (1180, 760)


# ---------------------------------------------------------------------------
# Demo macros (written by hand; nothing here came from a real keyboard)
# ---------------------------------------------------------------------------

def _typed(t: float, text: str, step: float = 0.12):
    ev = []
    for ch in text:
        vk = ord(ch.upper()) if ch.isalnum() else None
        ev += [E("key_press", t, key=ch, vk=vk), E("key_release", t + 0.06, key=ch, vk=vk)]
        t += step
    return ev, t


def seed() -> float:
    """Create the demo library; returns the end time of the typed text."""
    store = MacroStore(app_paths.default_macro_dir())
    for f in store.list_files():
        store.delete(f)
    ev = [E("mouse_move", 0.3 + i * 0.03, x=200 + i * 12, y=300 - i * 4) for i in range(30)]
    ev += [E("mouse_click", 1.4, x=560, y=180, button="left", pressed=True),
           E("mouse_click", 1.5, x=560, y=180, button="left", pressed=False)]
    typed, t = _typed(1.9, "ACME-1042")
    ev += typed
    ev += [E("key_press", t + 0.4, key="Key.ctrl_l"), E("key_press", t + 0.5, key="vk:67", vk=67),
           E("key_release", t + 0.6, key="vk:67", vk=67), E("key_release", t + 0.7, key="Key.ctrl_l")]
    ev += [E("mouse_move", t + 4.2 + i * 0.03, x=560 + i * 10, y=180 + i * 9) for i in range(20)]
    ev += [E("mouse_click", t + 5.0, x=760, y=360, button="left", pressed=True),
           E("mouse_click", t + 5.1, x=760, y=360, button="left", pressed=False),
           E("mouse_scroll", t + 5.6, x=760, y=360, dx=0, dy=-1),
           E("mouse_scroll", t + 5.7, x=760, y=360, dx=0, dy=-1),
           E("key_press", t + 6.4, key="Key.enter"), E("key_release", t + 6.5, key="Key.enter")]
    store.save(Macro("Fill order form", ev, description="Fills in an order and submits it."))
    store.save(Macro("Open daily report", _typed(0.5, "report")[0]))
    store.save(Macro("Export to CSV", _typed(0.2, "csv")[0]))
    store.save(Macro("Close all windows", [E("key_press", 0.2, key="Key.alt_l"),
                                           E("key_press", 0.3, key="Key.f4"),
                                           E("key_release", 0.4, key="Key.f4"),
                                           E("key_release", 0.5, key="Key.alt_l")]))
    return t


# ---------------------------------------------------------------------------

def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    t_end = seed()
    w = MainWindow()
    w.resize(*SIZE)
    w.show()

    def shot(name: str) -> None:
        # Clear hover highlights left by wherever the real cursor happens to
        # be, without moving it: a hovered row looks like a second selection.
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QAbstractItemView
        for view in w.findChildren(QAbstractItemView):
            support.qapp().sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
        support.pump(10)
        path = os.path.join(OUT, name + ".png")
        w.grab().save(path)
        print("wrote", path)

    def to_bottom(scroll_area) -> None:
        bar = scroll_area.verticalScrollBar()
        support.pump(5)
        bar.setValue(bar.maximum())

    # -- Record, while recording --------------------------------------
    w._go_to(0)
    rec = w.tab_rec
    rec.trigger_start()
    rec._poll_timer.stop()
    rec.lbl_events.setText("342")
    rec.lbl_elapsed.setText("00:08.6")
    shot("record")
    rec._pulse_timer.stop()
    rec.trigger_stop()

    # -- Player & Library, playing at 40 % ----------------------------
    w._go_to(1)
    lib = w.tab_lib_play
    for i in range(lib.tree.topLevelItemCount()):
        if lib.tree.topLevelItem(i).text(0) == "Fill order form":
            lib.tree.setCurrentItem(lib.tree.topLevelItem(i))
    lib.chk_humanize.setChecked(True)
    w._on_player_started()
    lib.update_progress(32, 80)
    w.now_loaded.set_progress(40)
    shot("player-library")
    to_bottom(lib.splitter.widget(0))                 # the player column
    shot("player-library-lower")
    w._on_player_finished()

    # -- Composer -------------------------------------------------------
    w._go_to(2)
    comp = w.tab_comp
    comp.open_file("Fill order form.json")
    canvas = comp.timeline.canvas
    canvas.set_playhead(1.4)
    canvas.select_range(t_end + 3.6, t_end + 4.15)
    shot("composer")
    # Lower part: a click selected (so its fields show), a library macro
    # selected, and an example key combination ready to insert.
    canvas.range = None
    canvas.selected = {next(i for i, g in enumerate(canvas.gestures) if g.kind == "click")}
    canvas.selection_changed.emit()
    comp.list_avail.setCurrentRow(0)
    comp.ins_keys.setText("<ctrl>+c")
    comp.ins_text.setText("Order received")
    to_bottom(comp)
    shot("composer-lower")
    comp.timeline.canvas.clear_selection()
    comp.verticalScrollBar().setValue(0)

    # -- Auto Click, running --------------------------------------------
    w._go_to(3)
    auto = w.tab_auto
    auto.set_running(True)
    auto.update_count(1284)
    auto.spin_limit.setValue(5000)
    shot("autoclick")
    auto.chk_fixed.setChecked(True)
    auto.spin_x.setValue(640)
    auto.spin_y.setValue(360)
    to_bottom(auto)
    shot("autoclick-lower")
    auto.set_running(False)
    auto.update_count(0)
    auto.chk_fixed.setChecked(False)
    auto.verticalScrollBar().setValue(0)

    # -- Settings ---------------------------------------------------------
    w._go_to(4)
    shot("settings")
    to_bottom(w.tab_cfg)
    shot("settings-lower")
    w.tab_cfg.verticalScrollBar().setValue(0)

    # -- Narrow window ------------------------------------------------------
    w.resize(780, 560)
    w._go_to(3)
    shot("compact")

    comp._new(confirm=False)
    w._hotkeys.stop()
    w.close()


if __name__ == "__main__":
    main()
