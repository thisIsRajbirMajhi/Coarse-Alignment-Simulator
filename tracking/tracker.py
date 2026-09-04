# tracking/tracker.py - Continuous tracking — orchestrates isolated phase handlers + smoothing + Kalman predictor

from __future__ import annotations

import numpy as np

from tracking.config import TrackerConfig
from tracking.constants import TRACKER_DEFAULTS
from tracking.filter import ExponentialFilter
from tracking.imm import IMMFilter
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
        # Phase 2: IMM with 3 models (still/CV/maneuver) — used when dt provided, more robust to curved/spiral
        self._imm = IMMFilter(qs=(2.0, 12.0, 38.0), meas_var=4.0)

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
        # Kalman/IMM tuning could be exposed via config in future; keep defaults for now
        if hasattr(cfg, "kalman_process_var"):
            try:
                self._kalman.process_var = float(cfg.kalman_process_var)  # type: ignore
                # keep IMM CV model in sync
                if hasattr(self, "_imm"):
                    self._imm.qs = (self._imm.qs[0], float(cfg.kalman_process_var), self._imm.qs[2])  # type: ignore
                    for i, q in enumerate(self._imm.qs):
                        self._imm.filters[i].process_var = float(q)  # type: ignore
            except:
                pass
        if hasattr(cfg, "kalman_meas_var"):
            try:
                self._kalman.meas_var = float(cfg.kalman_meas_var)  # type: ignore
                if hasattr(self, "_imm"):
                    self._imm.meas_var = float(cfg.kalman_meas_var)  # type: ignore
                    for f in self._imm.filters:
                        f.meas_var = float(cfg.kalman_meas_var)  # type: ignore
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
            # IMM path — predicts through dropout, handles curved/maneuver better than single CV
            # Use IMM if available, fallback to single Kalman if IMM not initialized
            imm = getattr(self, "_imm", None)
            use_imm = imm is not None
            if use_imm:
                if has_det and not imm.is_initialized():
                    imm.init_from_measurement(detection)  # type: ignore
                    # keep Kalman in sync for legacy peek
                    try:
                        self._kalman.init_from_measurement(detection)  # type: ignore
                    except Exception:
                        pass
                    self.estimated_position = imm.get_pos()
                    self._filter.estimate = detection  # type: ignore
                elif imm.is_initialized():
                    imm.predict(float(dt))
                    # keep Kalman in sync for get_innovation_cov fallback
                    try:
                        self._kalman.predict(float(dt))
                    except Exception:
                        pass
                    if has_det:
                        imm.update(detection)  # type: ignore
                        try:
                            self._kalman.update(detection)  # type: ignore
                        except Exception:
                            pass
                        self._filter.update(detection)
                    else:
                        self._filter.update(None)
                    kal_pos = imm.get_pos()
                    if kal_pos is not None:
                        self.estimated_position = kal_pos
                else:
                    self._filter.update(None)
            else:
                # Fallback single Kalman (legacy)
                if has_det and not self._kalman.is_initialized():
                    self._kalman.init_from_measurement(detection)  # type: ignore
                    self.estimated_position = self._kalman.get_pos()
                    self._filter.estimate = detection  # type: ignore
                elif self._kalman.is_initialized():
                    self._kalman.predict(float(dt))
                    if has_det:
                        self._kalman.update(detection)  # type: ignore
                        self._filter.update(detection)
                    else:
                        self._filter.update(None)
                    kal_pos = self._kalman.get_pos()
                    if kal_pos is not None:
                        self.estimated_position = kal_pos
                else:
                    self._filter.update(None)
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
            try:
                self._imm.reset()
            except Exception:
                pass
            self._state.should_clear_estimate = False

        # Keep filters in sync when estimate is cleared externally
        if self.estimated_position is None:
            self._filter.reset()
            if self.status == LockStatus.SEARCHING:
                self._kalman.reset()
                try:
                    self._imm.reset()
                except Exception:
                    pass

        return self.estimated_position

    def predict(self, dt: float) -> tuple[float, float] | None:
        """Predict next position via IMM/Kalman (coast) without measurement — for gating."""
        try:
            if hasattr(self, "_imm") and self._imm.is_initialized():
                return self._imm.predict(float(dt))
        except Exception:
            pass
        if self._kalman.is_initialized():
            return self._kalman.predict(float(dt))
        return self.estimated_position

    def get_innovation_cov(self) -> np.ndarray | None:
        """Return 2x2 innovation covariance S for blind gating, or None."""
        try:
            if hasattr(self, "_imm") and self._imm.is_initialized():
                cov = self._imm.get_innovation_cov()
                if cov is not None:
                    return cov
        except Exception:
            pass
        try:
            if hasattr(self._kalman, "get_innovation_cov"):
                return self._kalman.get_innovation_cov()
        except Exception:
            pass
        return None

    def peek_predict(self, dt: float) -> tuple[float, float] | None:
        """
        Non-mutating prediction for gating: returns predicted position without
        advancing state. Used for association gate before update().
        Prefers IMM combined prediction.
        """
        try:
            if hasattr(self, "_imm") and self._imm.is_initialized():
                # IMM peek: combine filtered states without mixing (approx)
                s = self._imm.get_state()
                if s is not None:
                    dt = float(dt)
                    if dt < 1e-6:
                        return (float(s[0]), float(s[1]))
                    # predict combined state
                    return (float(s[0] + s[2] * dt), float(s[1] + s[3] * dt))
        except Exception:
            pass
        try:
            if not self._kalman.is_initialized():
                return self.estimated_position
            x = self._kalman.x.copy() if self._kalman.x is not None else None
            P = self._kalman.P.copy() if self._kalman.P is not None else None
            if x is None or P is None:
                return self.estimated_position
            dt = float(dt)
            if dt < 1e-6:
                return (float(x[0]), float(x[1]))
            F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
            x_pred = F @ x
            return (float(x_pred[0]), float(x_pred[1]))
        except Exception:
            return self.estimated_position

    def get_mode_probs(self) -> np.ndarray | None:
        """Return IMM mode probabilities [still, CV, maneuver] or None."""
        try:
            if hasattr(self, "_imm"):
                return self._imm.get_mode_probs()
        except Exception:
            pass
        return None

    def get_state_vector(self) -> np.ndarray | None:
        """Return IMM/Kalman state [x,y,vx,vy] or None — mirrors Target.get_state_vector()."""
        try:
            if hasattr(self, "_imm") and self._imm.is_initialized():
                sv = self._imm.get_state()
                if sv is not None:
                    return np.array(sv, dtype=np.float64)
        except Exception:
            pass
        if self._kalman.is_initialized():
            sv = self._kalman.get_state_vector()
            if sv is not None:
                return sv
        if self.estimated_position is not None:
            return np.array([self.estimated_position[0], self.estimated_position[1], 0.0, 0.0], dtype=np.float64)
        return None

    def get_velocity(self) -> tuple[float, float] | None:
        try:
            if hasattr(self, "_imm") and self._imm.is_initialized():
                v = self._imm.get_vel()
                if v is not None:
                    return v
        except Exception:
            pass
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
        try:
            self._imm.reset()
        except:
            pass
        self._state.reset()
        self.status = self._state.status
        self._consecutive_hits = 0
        self._consecutive_misses = 0