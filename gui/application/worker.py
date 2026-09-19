# gui/application/worker.py - SimWorker: runs controller.step() off the GUI thread.
from __future__ import annotations

import logging

from PyQt5.QtCore import QObject, QMutex, QThread, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class SimWorker(QObject):
    """QThread worker that executes the sim step outside the GUI thread.

    The 30 ms tick used to run scene + disturbances + tracking synchronously
    in the GUI thread, freezing the UI whenever a step exceeded budget.
    Now MainWindow's timer only *requests* a step (queued signal); this worker
    runs ``controller.step()`` in its own thread and the resulting
    ``snapshotReady`` is delivered back to the GUI thread automatically.

    Coalescing: at most one step is ever in flight — MainWindow tracks a
    pending flag and skips requests until the snapshot returns, so a slow
    worker degrades to lower FPS instead of queueing lag.

    Serialization: ``mutex`` guards step-vs-config races. Config applies and
    session swaps take the same mutex (bounded by a single step).
    """

    requestStep = pyqtSignal()  # GUI thread -> worker thread (queued)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.mutex = QMutex()
        self._thread = QThread(self)
        self.moveToThread(self._thread)
        self.requestStep.connect(self._on_request)
        self._thread.start()

    @pyqtSlot()
    def _on_request(self) -> None:
        self.mutex.lock()
        try:
            self.controller.step()
        except Exception as e:
            log.exception("worker step failed: %s", e)
        finally:
            self.mutex.unlock()

    def request_step(self) -> None:
        """Ask for one step (returns immediately; snapshot arrives later)."""
        if self._thread.isRunning():
            self.requestStep.emit()

    def guard(self):
        """Mutex guard for session swaps / config applies from the GUI thread."""
        return _MutexGuard(self.mutex)

    def shutdown(self, timeout_ms: int = 2000) -> None:
        try:
            self._thread.quit()
            if not self._thread.wait(timeout_ms):
                log.warning("sim worker did not stop in %d ms", timeout_ms)
        except Exception as e:
            log.debug("worker shutdown skipped: %s", e)


class _MutexGuard:
    def __init__(self, mutex: QMutex):
        self._mutex = mutex

    def __enter__(self):
        self._mutex.lock()
        return self

    def __exit__(self, *exc):
        try:
            self._mutex.unlock()
        except Exception:
            pass
        return False


__all__ = ["SimWorker"]
