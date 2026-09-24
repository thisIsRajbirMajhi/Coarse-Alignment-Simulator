# local_terminal/tracker.py - V2 2D constant-velocity Kalman tracker (Plan V2 §12).
#
# State x = [x, y, vx, vy]^T in FOV pixels. Deterministic, numpy-based.
# R adapts to SNR (§12.3); Mahalanobis gate drives association (§11.4).

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanConfig:
    process_noise_q: float = 8.0
    measurement_noise_r_base: float = 4.0
    r_scale_low_snr: float = 6.0
    r_scale_high_snr: float = 0.5
    coast_growth_px_per_frame: float = 2.0
    coast_margin_cap_px: float = 30.0

    def validate(self) -> "KalmanConfig":
        self.process_noise_q = float(max(1e-6, self.process_noise_q))
        self.measurement_noise_r_base = float(max(1e-6, self.measurement_noise_r_base))
        self.r_scale_low_snr = float(max(1.0, self.r_scale_low_snr))
        self.r_scale_high_snr = float(min(1.0, max(1e-3, self.r_scale_high_snr)))
        self.coast_growth_px_per_frame = float(max(0.0, self.coast_growth_px_per_frame))
        self.coast_margin_cap_px = float(max(1.0, self.coast_margin_cap_px))
        return self


def r_for_snr(snr_db: float, cfg: KalmanConfig) -> float:
    s = float(snr_db)
    lo, hi = 6.0, 25.0
    if s <= lo:
        scale = cfg.r_scale_low_snr
    elif s >= hi:
        scale = cfg.r_scale_high_snr
    else:
        frac = (s - lo) / (hi - lo)
        scale = cfg.r_scale_low_snr + frac * (cfg.r_scale_high_snr - cfg.r_scale_low_snr)
    return float(cfg.measurement_noise_r_base * scale)


class KalmanFilter2D:
    def __init__(self, config: KalmanConfig | None = None):
        self.config = (config or KalmanConfig()).validate()
        self.x = np.zeros((4, 1), dtype=float)
        self.P = np.eye(4, dtype=float) * 100.0
        self._initialised = False

    def reset(self) -> None:
        self.x = np.zeros((4, 1), dtype=float)
        self.P = np.eye(4, dtype=float) * 100.0
        self._initialised = False

    def initialise(self, x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> None:
        self.x = np.array([[float(x)], [float(y)], [float(vx)], [float(vy)]], dtype=float)
        # If velocity provided (reacq), keep moderate velocity uncertainty; else high
        vel_var = 25.0 if (abs(float(vx)) < 1e-6 and abs(float(vy)) < 1e-6) else 12.0
        self.P = np.diag([4.0, 4.0, vel_var, vel_var])
        self._initialised = True

    def shift(self, dx: float, dy: float) -> None:
        self.x[0, 0] += float(dx)
        self.x[1, 0] += float(dy)

    def _matrices(self, dt: float):
        dt = max(float(dt), 1e-6)
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
        q = self.config.process_noise_q
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        Q = q * np.array([[dt4 / 4, 0, dt3 / 2, 0], [0, dt4 / 4, 0, dt3 / 2], [dt3 / 2, 0, dt2, 0], [0, dt3 / 2, 0, dt2]], dtype=float)
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        return F, Q, H

    def predict(self, dt: float) -> tuple[float, float]:
        F, Q, _ = self._matrices(dt)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        return float(self.x[0, 0]), float(self.x[1, 0])

    def update(self, zx: float, zy: float, r_var: float) -> tuple[float, float]:
        _, _, H = self._matrices(1.0 / 30.0)
        R = np.eye(2) * max(float(r_var), 1e-6)
        z = np.array([[float(zx)], [float(zy)]], dtype=float)
        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        # Adaptive: large innovation ( >3sigma) indicates maneuver -> inflate P slightly to adapt faster
        try:
            nis = float(y.T @ np.linalg.inv(S) @ y)
            if nis > 9.0:  # chi2 2dof 99% ~9.21
                # Mild process noise boost for next predict by inflating velocity covariance
                self.P[2,2] *= 1.35
                self.P[3,3] *= 1.35
        except Exception:
            pass
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            K = self.P @ H.T / (np.trace(S) / 2.0 + 1e-6)
        self.x = self.x + K @ y
        I = np.eye(4)
        self.P = (I - K @ H) @ self.P
        # Enforce positive diagonal (numeric safety)
        try:
            for i in range(4):
                if self.P[i,i] < 1e-4:
                    self.P[i,i] = 1e-4
        except Exception:
            pass
        self._initialised = True
        return float(self.x[0, 0]), float(self.x[1, 0])

    def gate_var(self, r_var: float) -> float:
        """Legacy scalar gate var (deprecated) — kept for backward compat. Prefer innovation_cov()."""
        return float(max(self.P[0, 0], self.P[1, 1]) + max(float(r_var), 1e-6))

    def innovation_cov(self, r_var: float) -> np.ndarray:
        """Full 2x2 innovation covariance S = H P H^T + R  (BUG-05 fix)."""
        _, _, H = self._matrices(1.0 / 30.0)
        R = np.eye(2) * max(float(r_var), 1e-6)
        try:
            S = H @ self.P @ H.T + R
        except Exception:
            # Fallback to scalar-based diagonal
            v = self.gate_var(r_var)
            S = np.eye(2) * v
        # Ensure positive definite
        try:
            S[0, 0] = max(float(S[0, 0]), 1e-6)
            S[1, 1] = max(float(S[1, 1]), 1e-6)
        except Exception:
            pass
        return S

    def mahalanobis_d2(self, zx: float, zy: float, r_var: float) -> float:
        """Legacy scalar Mahalanobis (dx²+dy²)/var. Kept for compat; use mahalanobis_d2_full for 2D."""
        dx = float(zx) - float(self.x[0, 0])
        dy = float(zy) - float(self.x[1, 0])
        return (dx * dx + dy * dy) / self.gate_var(r_var)

    def mahalanobis_d2_full(self, zx: float, zy: float, r_var: float) -> float:
        """Full 2D Mahalanobis d² = νᵀ S⁻¹ ν with S = HPHᵀ + R (BUG-05)."""
        dx = float(zx) - float(self.x[0, 0])
        dy = float(zy) - float(self.x[1, 0])
        y = np.array([[dx], [dy]], dtype=float)
        S = self.innovation_cov(r_var)
        try:
            invS = np.linalg.inv(S)
            d2 = float((y.T @ invS @ y).item())
        except np.linalg.LinAlgError:
            # Fallback to scalar
            d2 = (dx*dx + dy*dy) / max(float(np.trace(S)/2.0), 1e-6)
        return float(d2)

    def normalized_innovation_squared(self, zx: float, zy: float, r_var: float) -> float:
        """Alias for mahalanobis_d2_full — NIS for innovation monitoring."""
        return self.mahalanobis_d2_full(zx, zy, r_var)

    @property
    def position(self) -> tuple[float, float]:
        return float(self.x[0, 0]), float(self.x[1, 0])

    @property
    def velocity(self) -> tuple[float, float]:
        return float(self.x[2, 0]), float(self.x[3, 0])

    @property
    def uncertainty_px(self) -> float:
        return float(max(0.0, (max(self.P[0, 0], 0.0) + max(self.P[1, 1], 0.0)) ** 0.5))


class KalmanTracker:
    def __init__(self, config: KalmanConfig | None = None):
        self.config = (config or KalmanConfig()).validate()
        self.kf = KalmanFilter2D(self.config)
        self.active_tid: str | None = None
        self.misses: int = 0
        self.last_meas_t: float = 0.0
        self.last_beacon_t: float | None = None
        self.p_rx_w: float = 0.0
        self.status: str = "LOST"
        self._dt: float = 1.0 / 30.0

    def reset(self) -> None:
        self.kf.reset()
        self.active_tid = None
        self.misses = 0
        self.p_rx_w = 0.0
        self.status = "LOST"
        self.last_beacon_t = None

    def lock(self, tid: str, x: float, y: float, t: float, p_rx_w: float = 0.0, vx: float | None = None, vy: float | None = None) -> None:
        self.active_tid = str(tid)
        # Preserve prior velocity if available (reacq): avoids zero-velocity lag for maneuvering targets
        if vx is None or vy is None:
            try:
                pvx, pvy = self.kf.velocity
                # Only preserve if previously initialized and not absurd
                if self.kf._initialised and abs(pvx) < 500 and abs(pvy) < 500:
                    vx = float(pvx) * 0.7  # decay slightly, target may have turned
                    vy = float(pvy) * 0.7
                else:
                    vx, vy = 0.0, 0.0
            except Exception:
                vx, vy = 0.0, 0.0
        self.kf.initialise(float(x), float(y), float(vx), float(vy))
        self.misses = 0
        self.last_meas_t = float(t)
        self.p_rx_w = float(p_rx_w)
        self.status = "TRACKING"

    def step(self, obs, dt: float, t: float, origin_shift: tuple[float, float] = (0.0, 0.0)):
        from src.local_terminal.models import TargetTrack as _TT
        self._dt = max(float(dt), 1e-6)
        self.kf.shift(-float(origin_shift[0]), -float(origin_shift[1]))
        if obs is not None:
            r = r_for_snr(float(getattr(obs, "snr_db", 6.0)), self.config)
            self.kf.predict(self._dt)
            self.kf.update(float(obs.fov_x), float(obs.fov_y), r)
            self.misses = 0
            self.last_meas_t = float(t)
            self.p_rx_w = float(getattr(obs, "p_rx_w", 0.0) or 0.0)
            if getattr(obs, "timestamp_s", 0.0):
                self.last_beacon_t = float(obs.timestamp_s)
            self.status = "TRACKING"
        else:
            self.kf.predict(self._dt)
            self.misses += 1
            self.status = "COASTING"
        margin = min(float(self.misses) * self.config.coast_growth_px_per_frame, self.config.coast_margin_cap_px)
        unc = float(self.kf.uncertainty_px) + (margin if self.misses else 0.0)
        x, y = self.kf.position
        vx, vy = self.kf.velocity
        return _TT(terminal_id=self.active_tid or "", x=float(x), y=float(y), vx=float(vx), vy=float(vy), uncertainty_px=float(unc), last_measurement_time_s=float(self.last_meas_t), last_beacon_time_s=self.last_beacon_t, p_rx_w=float(self.p_rx_w), misses=int(self.misses), status=self.status).validate()

    def effective_uncertainty_px(self) -> float:
        margin = min(float(self.misses) * self.config.coast_growth_px_per_frame, self.config.coast_margin_cap_px)
        return float(self.kf.uncertainty_px) + (margin if self.misses else 0.0)

    def gate_pred_var(self) -> float:
        """Legacy scalar gate var (coast margin added). For full 2D use gate_innovation_cov()."""
        margin = min(float(self.misses) * self.config.coast_growth_px_per_frame, self.config.coast_margin_cap_px)
        return float(max(self.kf.P[0, 0], self.kf.P[1, 1]) + margin * margin)

    def gate_innovation_cov(self, r_var: float) -> np.ndarray:
        """Full 2x2 innovation covariance with coast margin (BUG-05): S = HPHᵀ + R + margin²·I."""
        S = self.kf.innovation_cov(r_var)
        try:
            margin = min(float(self.misses) * self.config.coast_growth_px_per_frame, self.config.coast_margin_cap_px)
            if margin > 1e-6:
                S = S + np.eye(2) * (margin * margin)
        except Exception:
            pass
        return S

    def mahalanobis_d2_full(self, zx: float, zy: float, r_var: float) -> float:
        """Full 2D Mahalanobis via Kalman filter (includes coast margin)."""
        dx = float(zx) - float(self.kf.x[0, 0])
        dy = float(zy) - float(self.kf.x[1, 0])
        y = np.array([[dx], [dy]], dtype=float)
        S = self.gate_innovation_cov(r_var)
        try:
            invS = np.linalg.inv(S)
            return float((y.T @ invS @ y).item())
        except np.linalg.LinAlgError:
            return float((dx*dx + dy*dy) / max(float(np.trace(S)/2.0), 1e-6))

    def predict_with_ai(self) -> tuple[float, float]:
        """AI residual wrapper: KF position + 0.3*Δ from Temporal-MLP (NIS>16 ignored by caller)."""
        try:
            from src.local_terminal.ai.predictor import TemporalMLPPredictor as _Pred
            # Use singleton stored on tracker if available, else heuristic
            pred = getattr(self, "_ai_predictor", None)
            if pred is None:
                pred = _Pred()
                self._ai_predictor = pred
            # Push current state
            x, y = self.kf.position
            vx, vy = self.kf.velocity
            pred.push(float(x), float(y), float(vx), float(vy))
            return pred.predict_with_ai(self.kf.position, self.kf.velocity)
        except Exception:
            x, y = self.kf.position
            return (float(x), float(y))

    def error_px(self, fov_w: float = 640.0, fov_h: float = 480.0):
        if self.active_tid is None or self.status == "LOST":
            return None
        x, y = self.kf.position
        return (float(x) - fov_w / 2.0, float(y) - fov_h / 2.0)

    def snapshot(self):
        from types import SimpleNamespace
        return SimpleNamespace(locked=bool(self.status == "TRACKING" and self.active_tid is not None), misses=int(self.misses), fov_x=float(self.kf.position[0]), fov_y=float(self.kf.position[1]), terminal_id=self.active_tid, loss_count=0)

    def autonomy_telemetry(self) -> dict:
        x, y = self.kf.position
        vx, vy = self.kf.velocity
        locked = self.status == "TRACKING" and self.active_tid is not None
        return {"autonomy": {"state": "LOCKED" if locked else "SEARCHING", "active_target_id": self.active_tid, "candidates": []}, "locked": bool(locked), "misses": int(self.misses), "target_loss_count": 0, "velocity_px_s": [round(float(vx), 3), round(float(vy), 3)], "uncertainty_px": round(float(self.effective_uncertainty_px()), 3), "predicted_fov": [round(float(x), 2), round(float(y), 2)]}


__all__ = ["KalmanConfig", "KalmanFilter2D", "KalmanTracker", "r_for_snr"]
