"""Background task runner so OCR never blocks the UI."""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from belgeocr.ocr import Cancelled


class WorkerSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()


class Worker(QRunnable):
    """Runs ``fn(*args, progress=..., cancel=..., **kwargs)`` in a thread pool."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()
        self._cancel = threading.Event()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = self.fn(
                *self.args,
                progress=lambda i, n, msg: self.signals.progress.emit(i, n, msg),
                cancel=self._cancel.is_set,
                **self.kwargs,
            )
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            traceback.print_exc()
            self.signals.error.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.finished.emit(result)
