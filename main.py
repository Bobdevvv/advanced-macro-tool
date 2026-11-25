import sys
import os

# Ensure src is importable when run as a script or frozen exe
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtCore import QEvent, QLockFile, QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from src import app_paths, brand
from src.ui import errors
from src.ui.fonts import install_fonts
from src.ui.main_window import MainWindow


def setup_app(app: QApplication) -> None:
    """Style and fonts shared by the app and the screenshot tooling."""
    app.setApplicationName(brand.APP_NAME)
    app.setOrganizationName(brand.AUTHOR)
    app.setApplicationVersion(brand.VERSION)
    app.setWindowIcon(QIcon(app_paths.icon_file()))
    # Fusion renders stylesheets consistently; the native style leaks through.
    app.setStyle("Fusion")
    # Windows' tooltip roll-out animation makes tooltips feel laggy.
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateTooltip, False)
    app.setEffectEnabled(Qt.UIEffect.UI_FadeTooltip, False)
    install_fonts(app)


def _set_cloaked(window, cloaked: bool) -> bool:
    """Hide/reveal a window via DWM cloaking (Windows only).

    A cloaked window is fully created, laid out and painted but not drawn on
    screen.  Showing it cloaked and uncloaking after the first themed frame
    avoids the white flash Windows otherwise shows before that frame.
    """
    try:
        import ctypes
        DWMWA_CLOAK = 13
        value = ctypes.c_int(1 if cloaked else 0)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(window.winId()), DWMWA_CLOAK, ctypes.byref(value), ctypes.sizeof(value))
        return hr == 0
    except Exception:
        return False


class _RevealAfterFirstPaint(QObject):
    """Uncloaks the window once its first frame has been painted."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._done = False
        window.installEventFilter(self)
        QTimer.singleShot(1500, self._reveal)     # safety net

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint and not self._done:
            # Let this paint (and its children's) finish, then show.
            QTimer.singleShot(0, self._reveal)
        return False

    def _reveal(self) -> None:
        if self._done:
            return
        self._done = True
        self._window.removeEventFilter(self)
        _set_cloaked(self._window, False)


def main() -> None:
    # Before anything reads or creates the data folder.
    app_paths.migrate_legacy_home()
    # Use the exact Windows scale factor (125 %, 150 % …) instead of rounding,
    # so the UI is sharp and correctly sized on every display.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    setup_app(app)
    errors.install(app)            # unexpected errors: log + message, no crash

    # One instance only: two copies would both react to every global hotkey.
    lock = QLockFile(os.path.join(app_paths.home(), "amt.lock"))
    lock.setStaleLockTime(0)       # a crashed instance's lock is detected by PID
    if not lock.tryLock(100):
        QMessageBox.information(
            None, brand.APP_SHORT,
            f"{brand.APP_NAME} is already running.\n\n"
            "Look for its window on the taskbar.")
        sys.exit(0)

    window = MainWindow()          # applies the saved theme before any paint
    if _set_cloaked(window, True):
        _RevealAfterFirstPaint(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
