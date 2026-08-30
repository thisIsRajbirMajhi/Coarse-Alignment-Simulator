"""
Tracking module.

Owns continuity across frames: takes each new detection (or None) and
maintains a smoothed position estimate + lock status. This is where
reacquisition-after-loss logic lives, separate from raw per-frame
detection.

Status machine:
  SEARCHING -> ACQUIRED   (first successful detection)
  ACQUIRED  -> TRACKING   (a couple more consecutive detections, confirms lock)
  TRACKING  -> LOST       (detection missing for miss_limit consecutive frames)
  LOST      -> SEARCHING  (after a short grace period with no detection)
"""

from enum import Enum


class LockStatus(Enum):
    SEARCHING = "searching"
    ACQUIRED = "acquired"
    TRACKING = "tracking"
    LOST = "lost"


class Tracker:
    def __init__(self, smoothing: float = 0.5, miss_limit: int = 5):
        self.status = LockStatus.SEARCHING
        self.estimated_position: tuple[float, float] | None = None
        self.smoothing = smoothing  # 0 = no smoothing (snap to detection), 1 = ignore new detections
        self.miss_limit = miss_limit
        self._consecutive_hits = 0
        self._consecutive_misses = 0

    def update(self, detection: tuple[float, float] | None) -> tuple[float, float] | None:
        """Feed in this frame's detection (or None); return the current
        best position estimate (or None) and update self.status."""
        if detection is not None:
            self._consecutive_hits += 1
            self._consecutive_misses = 0

            if self.estimated_position is None:
                self.estimated_position = detection
            else:
                ex, ey = self.estimated_position
                dx, dy = detection
                self.estimated_position = (
                    self.smoothing * ex + (1 - self.smoothing) * dx,
                    self.smoothing * ey + (1 - self.smoothing) * dy,
                )

            if self.status == LockStatus.SEARCHING:
                self.status = LockStatus.ACQUIRED
            elif self.status == LockStatus.ACQUIRED and self._consecutive_hits >= 3:
                self.status = LockStatus.TRACKING
            elif self.status == LockStatus.LOST:
                self.status = LockStatus.ACQUIRED

        else:
            self._consecutive_hits = 0
            self._consecutive_misses += 1

            if self.status in (LockStatus.ACQUIRED, LockStatus.TRACKING):
                if self._consecutive_misses >= self.miss_limit:
                    self.status = LockStatus.LOST
            elif self.status == LockStatus.LOST:
                if self._consecutive_misses >= self.miss_limit * 2:
                    self.status = LockStatus.SEARCHING
                    self.estimated_position = None

        return self.estimated_position
