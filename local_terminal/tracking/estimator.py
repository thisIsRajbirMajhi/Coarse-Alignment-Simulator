# local_terminal/estimator.py - Module 8: Track State Estimator (§19).
from __future__ import annotations

from local_terminal.core.models import CandidateTrack, TargetState


class TrackStateEstimator:
    """Maintains MEASUREMENT / FILTERED / PREDICTED distinctly (§19)."""

    def __init__(self, smoothing: float = 0.2, prediction_horizon: float = 0.15):
        self.smoothing = float(smoothing)
        self.prediction_horizon = float(prediction_horizon)
        self._fx, self._fy = 0.0, 0.0
        self._vx, self._vy = 0.0, 0.0
        self._ax, self._ay = 0.0, 0.0
        self._init = False

    def reset(self) -> None:
        self._fx = self._fy = self._vx = self._vy = self._ax = self._ay = 0.0
        self._init = False

    def update(self, track: CandidateTrack | None, dt: float,
               timestamp: float, camera_vel: tuple[float, float] | None = None) -> TargetState:
        dt = max(1e-4, min(float(dt), 0.2))
        if track is None:
            return TargetState(valid=False, timestamp=float(timestamp))
        mx, my = float(track.meas_x), float(track.meas_y)
        if not self._init:
            self._fx, self._fy = mx, my
            self._vx = self._vy = self._ax = self._ay = 0.0
            self._init = True
        else:
            alpha = max(0.01, min(1.0, 1.0 - self.smoothing))
            prev_fx, prev_fy = self._fx, self._fy
            prev_vx, prev_vy = self._vx, self._vy
            self._fx = alpha * mx + (1 - alpha) * self._fx
            self._fy = alpha * my + (1 - alpha) * self._fy
            # velocity from filtered delta + own-ship compensation
            cvx, cvy = (float(camera_vel[0]), float(camera_vel[1])) if camera_vel else (0.0, 0.0)
            inst_vx = (self._fx - prev_fx) / dt + cvx
            inst_vy = (self._fy - prev_fy) / dt + cvy
            inst_vx = max(-2000.0, min(2000.0, inst_vx))
            inst_vy = max(-2000.0, min(2000.0, inst_vy))
            av = 0.2
            self._vx = av * inst_vx + (1 - av) * self._vx
            self._vy = av * inst_vy + (1 - av) * self._vy
            self._ax = av * (self._vx - prev_vx) / dt + (1 - av) * self._ax
            self._ay = av * (self._vy - prev_vy) / dt + (1 - av) * self._ay
        # Acceleration-aware prediction with adaptive horizon: under hard
        # maneuvers (reversals) the lead shrinks instead of overshooting.
        try:
            import math as _math
            _a = _math.hypot(self._ax, self._ay)
            _h0 = max(0.0, float(self.prediction_horizon))
            _h = _h0 / (1.0 + _a / 800.0)
            _h = max(0.0, min(_h0, _h))
        except Exception:
            _h = max(0.0, float(self.prediction_horizon))
        px = self._fx + self._vx * _h + 0.5 * self._ax * _h * _h
        py = self._fy + self._vy * _h + 0.5 * self._ay * _h * _h
        # mirror into track estimate
        track.est_x, track.est_y = self._fx, self._fy
        track.est_vx, track.est_vy = self._vx, self._vy
        track.est_ax, track.est_ay = self._ax, self._ay
        return TargetState(valid=True, observation_id=track.observation_id,
                           measured_x=mx, measured_y=my,
                           filtered_x=self._fx, filtered_y=self._fy,
                           predicted_x=px, predicted_y=py,
                           velocity_x=self._vx, velocity_y=self._vy,
                           acceleration_x=self._ax, acceleration_y=self._ay,
                           confidence=float(track.confidence), snr=float(track.meas_snr),
                           signature_score=float(track.signature.overall_score),
                           centroid_x=self._fx, centroid_y=self._fy,
                           timestamp=float(timestamp))
