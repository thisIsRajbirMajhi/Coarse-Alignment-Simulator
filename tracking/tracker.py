# tracking/tracker.py - Continuous tracking — orchestrates isolated phase handlers + smoothing + Kalman predictor

from __future__ import annotations

import numpy as np

from tracking.config import TrackerConfig
from tracking.constants import TRACKER_DEFAULTS
from tracking.filter import ExponentialFilter
from tracking.kalman import KalmanFilter
from tracking.state import LockStatus, LockStateMachine

# Re-export LockStatus for backward compat `from tracking.tracker import LockStatus`
__all__ = ["Tracker", "LockStatus"]

class Tracker:
    """
    Tracker — maintains smoothed estimate + lock status + Kalman prediction.

    Pipeline per frame (legacy, no dt):
      detection = detector.detect(frame)  # (x,y) or None
      estimate  = tracker.update(detection)  # → exponential smoothed (x,y)

    With dt (robust, handles occlusion):
      estimate = tracker.update(detection, dt=dt)  # Kalman predict+update
      # On miss (detection=None) Kalman coasts with velocity, so estimate
      # continues moving during brief occlusion / dropout instead of freezing.

    State machine (LockStatus):
      SEARCHING (None) → ACQUIRED (first hit) → TRACKING (≥3 hits) → LOST (miss≥5, keep estimate) → SEARCHING (miss≥10, discard)

    Filters:
      - Exponential: y[n]=α·y[n-1]+(1-α)·x[n] — legacy, used when dt is None (tests)
      - Kalman (constant-velocity): state [x,y,vx,vy], predicts through dropout
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

        # Submodules — filter, state machine, and Kalman predictor
        self._filter = ExponentialFilter(smoothing=float(smoothing))
        self._state = LockStateMachine(miss_limit=int(miss_limit), acquire_hits=int(acquire_hits), lost_grace_mult=float(grace_mult))
        self.status = self._state.status
        # Kalman predictor for occlusion handling — seeded on first hit, coasts on miss (H4 fixed 40→12)
        self._kalman = KalmanFilter(process_var=12.0, meas_var=4.0)

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
        # Kalman tuning could be exposed via config in future; keep defaults for now
        if hasattr(cfg, "kalman_process_var"):
            try:
                self._kalman.process_var = float(cfg.kalman_process_var)  # type: ignore
            except:
                pass
        if hasattr(cfg, "kalman_meas_var"):
            try:
                self._kalman.meas_var = float(cfg.kalman_meas_var)  # type: ignore
            except:
                pass

    def to_config(self) -> TrackerConfig:
        return TrackerConfig(smoothing=float(self.smoothing), miss_limit=int(self.miss_limit), acquire_hits=int(self._state.acquire_hits), lost_grace_mult=float(self._state.lost_grace_mult)).validate()

    # Update — per-frame detection (or None) → estimate + status

    def update(self, detection: tuple[float, float] | None, dt: float | None = None) -> tuple[float, float] | None:
        """
        Feed this frame's detection (or None) — returns current best estimate.

        Modes:
          - dt is None (legacy, tests): exponential smoothing y=α·y_prev+(1-α)·x, holds on miss.
          - dt is float (robust): Kalman constant-velocity predict(dt)+update(z).
            On miss, Kalman coasts with velocity → handles occlusion/dropout.
            On hit, Kalman corrects and provides velocity for next coast.

        Steps (dt path):
          1) Kalman predict(dt) if already initialized
          2) If hit: Kalman update(z); else: keep predicted state
          3) State machine + lifecycle same as legacy
        Returns estimate for controller/GUI (None when SEARCHING).
        """
        # validate detection tuple
        if detection is not None:
            try:
                if not (isinstance(detection, (tuple, list)) and len(detection) == 2):
                    has_det = False
                    detection = None
                else:
                    float(detection[0]); float(detection[1])
                    has_det = True
            except Exception:
                has_det = False
                detection = None
        else:
            has_det = False

        # Filter path selection
        if dt is not None and dt > 1e-9:
            # Kalman path — predicts through dropout
            # Seed Kalman on first hit if not yet initialized
            if has_det and not self._kalman.is_initialized():
                # Seed with detection, zero velocity initially
                self._kalman.init_from_measurement(detection)  # type: ignore
                self.estimated_position = self._kalman.get_pos()
                # Also seed exponential filter for consistency
                self._filter.estimate = detection  # type: ignore
            elif self._kalman.is_initialized():
                # Predict forward
                self._kalman.predict(float(dt))
                if has_det:
                    self._kalman.update(detection)  # type: ignore
                    self._filter.update(detection)
                else:
                    self._filter.update(None)
                # Kalman position is the estimate (coasted or corrected)
                kal_pos = self._kalman.get_pos()
                if kal_pos is not None:
                    self.estimated_position = kal_pos
                # If kalman not yet initialized and no hit, hold previous estimate
                # (estimated_position stays as last)
            else:
                # No kalman yet and no hit — no estimate
                self._filter.update(None)
                # estimated_position stays None or last
        else:
            # Legacy exponential path (tests, no dt)
            if has_det:
                self.estimated_position = self._filter.update(detection)
            else:
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
            self._kalman.reset()
            self._state.should_clear_estimate = False

        # Keep filters in sync when estimate is cleared externally
        if self.estimated_position is None:
            self._filter.reset()
            # Do not reset Kalman here if we are in SEARCHING but expect reacquisition?
            # Keep Kalman reset only on clear; otherwise hold for prediction
            if self.status == LockStatus.SEARCHING:
                self._kalman.reset()

        return self.estimated_position

    def predict(self, dt: float) -> tuple[float, float] | None:
        """Predict next position via Kalman (coast) without measurement — for gating."""
        if self._kalman.is_initialized():
            return self._kalman.predict(float(dt))
        return self.estimated_position

    def get_state_vector(self) -> np.ndarray | None:
        """Return Kalman state [x,y,vx,vy] or None — mirrors Target.get_state_vector()."""
        if self._kalman.is_initialized():
            sv = self._kalman.get_state_vector()
            if sv is not None:
                return sv
        # Fallback: derive from exponential estimate (vel 0)
        if self.estimated_position is not None:
            return np.array([self.estimated_position[0], self.estimated_position[1], 0.0, 0.0], dtype=np.float64)
        return None

    def get_velocity(self) -> tuple[float, float] | None:
        if self._kalman.is_initialized():
            return self._kalman.get_vel()
        return None

    # Reset — for GUI _reset()

    def reset(self) -> None:
        self.estimated_position = None
        self._filter.reset()
        try:
            self._kalman.reset()
        except:
            pass
        self._state.reset()
        self.status = self._state.status
        self._consecutive_hits = 0
        self._consecutive_misses = 0