# local_terminal/estimator.py - Module 8: Track State Estimator (§19).
from __future__ import annotations

from local_terminal.core.models import CandidateTrack, TargetState

VEL_CLAMP = 2000.0  # px/s — shared spike clamp for all velocity paths
VEL_BLEND = 0.2  # EMA blend for velocity (single constant everywhere)


def update_track_velocity(track: CandidateTrack, meas_x: float, meas_y: float,
                          dt: float, cam_vx: float = 0.0, cam_vy: float = 0.0,
                          alpha: float = VEL_BLEND) -> tuple[float, float]:
    """Single shared per-track velocity update (own-ship compensated).

    Used by both the system hit loop (pre-tracking estimates feeding the
    reacquisition coast) and TrackStateEstimator (filtered output), so the
    two can no longer diverge on different smoothing constants.
    Returns (vx, vy) and mirrors into track.est_vx/est_vy.
    """
    dt = max(1e-3, float(dt))
    prev_ex = float(getattr(track, "est_x", 0.0) or 0.0)
    prev_ey = float(getattr(track, "est_y", 0.0) or 0.0)
    if not (prev_ex or prev_ey):
        track.est_vx, track.est_vy = 0.0, 0.0
        return 0.0, 0.0
    inst_vx = (float(meas_x) - prev_ex) / dt + float(cam_vx)
    inst_vy = (float(meas_y) - prev_ey) / dt + float(cam_vy)
    inst_vx = max(-VEL_CLAMP, min(VEL_CLAMP, inst_vx))
    inst_vy = max(-VEL_CLAMP, min(VEL_CLAMP, inst_vy))
    vx = alpha * inst_vx + (1.0 - alpha) * float(getattr(track, "est_vx", 0.0) or 0.0)
    vy = alpha * inst_vy + (1.0 - alpha) * float(getattr(track, "est_vy", 0.0) or 0.0)
    track.est_vx, track.est_vy = vx, vy
    return vx, vy


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
            # velocity from filtered delta + own-ship compensation (shared math)
            cvx, cvy = (float(camera_vel[0]), float(camera_vel[1])) if camera_vel else (0.0, 0.0)
            inst_vx = (self._fx - prev_fx) / dt + cvx
            inst_vy = (self._fy - prev_fy) / dt + cvy
            inst_vx = max(-VEL_CLAMP, min(VEL_CLAMP, inst_vx))
            inst_vy = max(-VEL_CLAMP, min(VEL_CLAMP, inst_vy))
            self._vx = VEL_BLEND * inst_vx + (1 - VEL_BLEND) * self._vx
            self._vy = VEL_BLEND * inst_vy + (1 - VEL_BLEND) * self._vy
            self._ax = VEL_BLEND * (self._vx - prev_vx) / dt + (1 - VEL_BLEND) * self._ax
            self._ay = VEL_BLEND * (self._vy - prev_vy) / dt + (1 - VEL_BLEND) * self._ay
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
