"""
Shared test setup.

Importing this module first guarantees that tests can never touch the real
macros or settings: ``AMT_HOME`` is pointed at a fresh temporary folder
before any AMT module reads it.  It also offers fakes for pynput's mouse and
keyboard controllers, so playback tests never move the real cursor.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

_HOME = tempfile.mkdtemp(prefix="amt-tests-")
os.environ["AMT_HOME"] = _HOME
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_app = None


def qapp():
    """The single QApplication, styled exactly like the real app."""
    global _app
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance()
    if _app is None:
        import main as appmain
        _app = QApplication([])
        appmain.setup_app(_app)
    return _app


def pump(times: int = 5) -> None:
    for _ in range(times):
        qapp().processEvents()


def flush_deletes() -> None:
    """Actually destroy widgets scheduled with deleteLater()."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def fresh_dir(name: str) -> str:
    path = tempfile.mkdtemp(prefix=f"{name}-", dir=_HOME)
    return path


class FakeMouse:
    """Records what pynput's mouse Controller would have done."""

    def __init__(self) -> None:
        self.position = (0, 0)
        self.log = []

    def __setattr__(self, name, value):
        if name == "position" and hasattr(self, "log"):
            self.log.append(("move", tuple(value)))
        object.__setattr__(self, name, value)

    def press(self, button):
        self.log.append(("press", button, self.position))

    def release(self, button):
        self.log.append(("release", button, self.position))

    def scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))


class FakeKeyboard:
    def __init__(self) -> None:
        self.log = []

    def press(self, key):
        self.log.append(("press", key))

    def release(self, key):
        self.log.append(("release", key))


def stub_global_input() -> None:
    """Stop UI tests from installing real system-wide input hooks.

    Recording and hotkey listening are exercised through their callbacks
    instead; real hooks in a test run would capture the developer's typing.
    """
    from src.core.hotkey_manager import HotkeyManager
    from src.core.recorder import Recorder
    Recorder._start_listeners = lambda self: None
    Recorder._stop_listeners = lambda self: None

    def _no_listener_restart(self):
        from src.core import hotkey_manager as hm
        self.stop()
        self.errors, self._combos = [], {}
        for hk, cb in self._bindings.items():
            try:
                self._combos[hm.parse(hk)] = cb
            except ValueError as exc:
                self.errors.append(f"{hk}: {exc}")
    HotkeyManager._restart = _no_listener_restart
