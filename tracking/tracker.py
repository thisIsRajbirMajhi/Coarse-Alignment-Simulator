# tracking/tracker.py - Continuous tracking — orchestrates isolated phase handlers + smoothing filter

from __future__ import annotations

from tracking.config import TrackerConfig
from tracking.constants import TRACKER_DEFAULTS
from tracking.filter import ExponentialFilter
from tracking.state import LockStatus, LockStateMachine

# Re-export LockStatus for backward compat `from tracking.tracker import LockStatus`
__all__ = ["Tracker", "LockStatus"]

class Tracker:
    """
    Tracker — maintains smoothed estimate + lock status across frames.

    Pipeline per frame:
      detection = detector.detect(frame)  # (x,y) or None — raw input, always runs
      estimate  = tracker.update(detection)  # → smoothed (x,y) or None, updates status

    State machine (LockStatus):
      SEARCHING (None) → ACQUIRED (first hit, probation) → TRACKING (≥3 hits, locked) → LOST (miss≥5, keep estimate) → SEARCHING (miss≥10, discard)

    Filter: y[n]=α·y[n-1]+(1-α)·x[n] — α=smoothing (0..0.95, default 0.5).
    """

    def __init__(self, smoothing: float = TRACKER_DEFAULTS["smoothing"], miss_limit: int = TRACKER_DEFAULTS["miss_limit"], config: TrackerConfig | None = None):
        # Config-driven or legacy direct
        if config is not None:
            cfg = config.validate()
            self.config = cfg
            smoothing = float(cfg.smoothing)
            miss_limit = int(cfg.miss_limit)
            acquire_hits = int(cfg.acquire_hits)
            grace_mult = float(cfg.lost_grace_mult)
        else:
            cfg = TrackerConfig(smoothing=float(smoothing), miss_limit=int(miss_limit)).validate()
            self.config = cfg
            acquire_hits = int(cfg.acquire_hits)
            grace_mult = float(cfg.lost_grace_mult)

        self.smoothing = float(smoothing)
        self.miss_limit = int(miss_limit)
        self.status: LockStatus = LockStatus.SEARCHING
        self.estimated_position: tuple[float, float] | None = None

        # Submodules — filter and state machine
        self._filter = ExponentialFilter(smoothing=float(smoothing))
        self._state = LockStateMachine(miss_limit=int(miss_limit), acquire_hits=int(acquire_hits), lost_grace_mult=float(grace_mult))
        self.status = self._state.status

        # Mirror for backward compat (tests read _consecutive_hits etc.)
        self._consecutive_hits: int = 0
        self._consecutive_misses: int = 0

    # Config bridge — -apply without rebuild

    def apply_config(self, config: TrackerConfig) -> None:
        cfg = config.validate()
        self.config = cfg
        self.smoothing = float(cfg.smoothing)
        self.miss_limit = int(cfg.miss_limit)
        self._filter.set_smoothing(float(cfg.smoothing))
        self._state.set_thresholds(miss_limit=int(cfg.miss_limit), acquire_hits=int(cfg.acquire_hits), grace_mult=float(cfg.lost_grace_mult))

    def to_config(self) -> TrackerConfig:
        return TrackerConfig(smoothing=float(self.smoothing), miss_limit=int(self.miss_limit), acquire_hits=int(self._state.acquire_hits), lost_grace_mult=float(self._state.lost_grace_mult)).validate()

    # Update — per-frame detection (or None) → estimate + status

    def update(self, detection: tuple[float, float] | None) -> tuple[float, float] | None:
        """
        Feed this frame's detection (or None) — returns current best estimate (or None) and updates status.

        Steps:
          1) Filter: if hit, y = α·y_prev + (1-α)·x (or seed if first); if miss, hold.
          2) State: update hit/miss counters and transition per table.
          3) Lifecycle: if LOST→SEARCHING, discard stale estimate (set None).

        Returns estimate for controller/GUI (None when SEARCHING).
        """
        has_det = detection is not None

        # Filter — smoothing (holds on miss)
        if has_det:
            # If state says SEARCHING and estimate is None, filter will seed
            self.estimated_position = self._filter.update(detection)
        else:
            # No detection — filter holds (no update), but we keep last estimate unless state says clear
            self._filter.update(None)

        # State machine — updates status and decides if estimate should be cleared
        new_status = self._state.update(bool(has_det))
        self.status = new_status

        # Sync mirror counters for backward compat
        self._consecutive_hits = int(self._state.hits)
        self._consecutive_misses = int(self._state.misses)

        # Lifecycle: if state says clear (LOST→SEARCHING after grace), discard
        if self._state.should_clear_estimate:
            self.estimated_position = None
            self._filter.reset()
            self._state.should_clear_estimate = False

        # Keep filter in sync when estimate is cleared externally
        if self.estimated_position is None:
            self._filter.reset()

        return self.estimated_position

    # Reset — for GUI _reset()

    def reset(self) -> None:
        self.estimated_position = None
        self._filter.reset()
        self._state.reset()
        self.status = self._state.status
        self._consecutive_hits = 0
        self._consecutive_misses = 0