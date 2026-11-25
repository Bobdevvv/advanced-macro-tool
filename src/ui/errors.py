"""
Last line of defence against unexpected errors.

PyQt6 aborts the whole process when an exception escapes a slot, and an
exception in a worker thread would otherwise vanish silently.  ``install``
routes both to one handler that

* writes the traceback to ``logs/amt.log`` (rotated, a few hundred KB),
* shows a short, non-technical message on the UI thread,
* and lets the app keep running.

The log holds error locations only: tracebacks, never macro contents or
typed keys.  Callers that expect a failure (a file that cannot be written)
should still catch it themselves and show a specific message; this is for
the failures nobody expected.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from src import app_paths

log = logging.getLogger("amt")


class _Reporter(QObject):
    """Lives on the UI thread; worker threads report through its signal."""
    report = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.report.connect(self._show)
        self._showing = False

    def _show(self, summary: str, where: str) -> None:
        if self._showing:            # never stack dialogs in an error loop
            return
        self._showing = True
        try:
            box = QMessageBox(QApplication.activeWindow())
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Something went wrong")
            box.setText("AMT ran into an unexpected problem and stopped that "
                        "action. Everything else keeps working.")
            box.setInformativeText(summary)
            box.setDetailedText(
                f"{where}\n\nThe full details were written to:\n"
                f"{os.path.join(app_paths.log_dir(), 'amt.log')}")
            box.exec()
        finally:
            self._showing = False


_reporter: Optional[_Reporter] = None


def _setup_logging() -> None:
    if log.handlers:
        return
    try:
        handler = RotatingFileHandler(
            os.path.join(app_paths.log_dir(), "amt.log"), maxBytes=256_000,
            backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def report(exc_type, exc, tb, context: str = "") -> None:
    """Log an exception and tell the user, from any thread."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("Unhandled error%s\n%s", f" in {context}" if context else "", text)
    summary = f"{exc_type.__name__}: {exc}" if str(exc) else exc_type.__name__
    frames = traceback.extract_tb(tb)
    where = (f"{os.path.basename(frames[-1].filename)}, line "
             f"{frames[-1].lineno}" if frames else "unknown location")
    if _reporter is not None:
        _reporter.report.emit(summary, where)    # queued to the UI thread
    else:
        sys.__stderr__.write(text)


def install(app: QApplication) -> None:
    """Install the handlers.  Call once, after the QApplication exists."""
    global _reporter
    _setup_logging()
    _reporter = _Reporter()
    _reporter.moveToThread(app.thread())

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        report(exc_type, exc, tb)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        report(args.exc_type, args.exc_value, args.exc_traceback,
               context=f"thread '{args.thread.name if args.thread else '?'}'")

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    log.info("AMT started")
