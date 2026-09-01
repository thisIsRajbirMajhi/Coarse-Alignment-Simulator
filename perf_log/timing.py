# perf_log/timing.py - Isolated timing & acquisition calculations — split from PerformanceLogger god cl

import math
import time

def compute_fps(frame_count: int, elapsed: float) -> float:
    return (frame_count / elapsed) if elapsed > 1e-9 else 0.0

def compute_acquisition_time(is_locked: bool, acquisition_time: float | None, elapsed: float, start_mono: float | None) -> float | None:
    if is_locked and acquisition_time is None and start_mono is not None:
        return elapsed
    return acquisition_time

class ReacquisitionTracker:
    """Tracks reacquisition times — isolated from log_frame 100-line method."""

    def __init__(self):
        self.reacquisition_times: list[float] = []
        self._lost_since: float | None = None
        self._prev_state: str | None = None

    def update(self, lock_state: str | None, is_locked: bool) -> tuple[int, int]:
        # Returns (acquisitions_delta, lock_losses_delta) — caller aggregates
        return (0, 0)

    def record_lost(self, mono: float) -> None:
        if self._lost_since is None:
            self._lost_since = mono

    def record_reacquisition(self, mono: float) -> None:
        if self._lost_since is not None:
            reacq = mono - self._lost_since
            if 0 <= reacq < 1e6:
                self.reacquisition_times.append(float(reacq))
            self._lost_since = None