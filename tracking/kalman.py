# tracking/kalman — constant-velocity state estimation with dropout bridging
#
# State: [x, y, vx, vy]^T ; Measurement: [cx, cy]^T (position only).
# Velocity is inferred, used for predictive pointing / feed-forward / reacq.
# Fusion rule:
#   detection present -> predict + update
#   missing          -> predict only (coast 1-2 frames without LOST)

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.config_base import BaseValidatedConfig, clip_field

KALMAN_LIMITS = {
    "process_noise": (0.1, 500.0),
    "measurement_noise": (0.1, 200.0),
    "max_coast": (1, 30),
}

KALMAN_DEFAULTS = {
    "process_noise": 8.0,
    "measurement_noise": 9.0,
    "max_coast": 10,
}


@dataclass
class KalmanConfig(BaseValidatedConfig):
    LIMITS = KALMAN_LIMITS
    DEFAULTS = KALMAN_DEFAULTS

    process_noise: float = KALMAN_DEFAULTS["process_noise"]
    measurement_noise: float = KALMAN_DEFAULTS["measurement_noise"]
    max_coast: int = KALMAN_DEFAULTS["max_coast"]

    def validate(self) -> "KalmanConfig":
        self.process_noise = float(clip_field(self.process_noise, *self.LIMITS["process_noise"]))
        self.measurement_noise = float(clip_field(self.measurement_noise, *self.LIMITS["measurement_noise"]))
        self.max_coast = int(clip_field(int(self.max_coast), *self.LIMITS["max_coast"]))
        return self


class KalmanTracker:
    """4-state constant-velocity filter with adaptive Q/R + covariance export.

    Backward compatible: position/velocity/state/predict/update/step/stale
    behave as before. New: per-update meas_var, Mahalanobis gating helpers,
    maneuver-adaptive Q boost, lock-quality and non-mutating peek.
    """

    def __init__(self, config: KalmanConfig | None = None):
        self.config = (config or KalmanConfig()).validate()
        self.x = np.zeros(4, dtype=float)  # [x, y, vx, vy]
        self.P = np.eye(4, dtype=float) * 100.0
        self.initialized = False
        self.coast_count = 0
        self.last_dt = 1 / 30
        self._q_boost = 1.0  # transient maneuver factor, decays on update
        self.last_residual: tuple[float, float] = (0.0, 0.0)
        self.last_m_dist2: float = 0.0
        self.last_meas_var: float = float(self.config.measurement_noise)

    def reset(self, x: float = 0.0, y: float = 0.0, vx: float = 0.0, vy: float = 0.0) -> None:
        self.x[:] = (float(x), float(y), float(vx), float(vy))
        self.P = np.eye(4, dtype=float) * 100.0
        self.initialized = True
        self.coast_count = 0
        self._q_boost = 1.0

    @property
    def position(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> tuple[float, float]:
        return float(self.x[2]), float(self.x[3])

    @property
    def state(self) -> tuple[float, float, float, float]:
        return float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])

    def _transition(self, dt: float) -> np.ndarray:
        return np.array(
            [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1, 0],
             [0, 0, 0, 1]],
            dtype=float,
        )

    def _process_noise(self, dt: float) -> np.ndarray:
        q = float(self.config.process_noise) * float(self._q_boost)
        return q * np.array(
            [[dt**4 / 4, 0, dt**3 / 2, 0],
             [0, dt**4 / 4, 0, dt**3 / 2],
             [dt**3 / 2, 0, dt**2, 0],
             [0, dt**3 / 2, 0, dt**2]],
            dtype=float,
        )

    def predict(self, dt: float | None = None) -> tuple[float, float, float, float]:
        dt = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
        self.last_dt = dt
        F = self._transition(dt)
        Q = self._process_noise(dt)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        return self.state

    def peek_predict(self, dt: float | None = None) -> tuple[tuple[float, float], np.ndarray]:
        """Non-mutating prediction: returns (predicted_xy, cov_xy_2x2)."""
        try:
            dtc = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
            F = self._transition(dtc)
            Q = self._process_noise(dtc)
            xp = F @ self.x
            Pp = F @ self.P @ F.T + Q
            return ((float(xp[0]), float(xp[1])), np.array([[Pp[0, 0], Pp[0, 1]], [Pp[1, 0], Pp[1, 1]]]))
        except Exception:
            return (self.position, self.cov_xy)

    def innovation_covariance(self, meas_var: float | None = None) -> np.ndarray:
        r = float(meas_var) if meas_var is not None else float(self.last_meas_var)
        r = float(np.clip(r, 0.5, 100.0))
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        return H @ self.P @ H.T + np.eye(2) * r

    def mahalanobis(self, cx: float, cy: float, meas_var: float | None = None) -> float:
        try:
            r = float(meas_var) if meas_var is not None else float(self.last_meas_var)
            S = self.innovation_covariance(r)
            res = np.array([float(cx) - self.x[0], float(cy) - self.x[1]])
            det = float(S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0])
            if not np.isfinite(det) or det < 1e-6:
                return float(res @ res) / max(1.0, r)
            inv = np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]]) / det
            d2 = float(res @ inv @ res)
            return d2 if np.isfinite(d2) else 1e9
        except Exception:
            return 1e9

    def report_residual(self, m_dist2: float) -> None:
        """Maneuver adaptation: boost Q after large normalized residuals."""
        try:
            m = float(m_dist2)
            if m > 9.21:
                self._q_boost = min(8.0, self._q_boost * 1.6)
            elif m > 4.0:
                self._q_boost = min(4.0, self._q_boost * 1.15)
            else:
                self._q_boost = max(1.0, self._q_boost * 0.9)
        except Exception:
            pass

    def update(self, cx: float, cy: float, dt: float | None = None, meas_var: float | None = None) -> tuple[float, float, float, float]:
        if not self.initialized:
            self.reset(cx, cy)
            if meas_var is not None:
                try:
                    self.last_meas_var = float(np.clip(float(meas_var), 0.5, 100.0))
                except Exception:
                    pass
            return self.state
        # Predict to measurement time first (fusion rule)
        self.predict(dt)
        z = np.array([float(cx), float(cy)], dtype=float)
        if not np.all(np.isfinite(z)):
            self.coast_count += 1
            return self.state
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        r = float(meas_var) if meas_var is not None else float(self.config.measurement_noise)
        r = float(np.clip(r, 0.5, 100.0))
        self.last_meas_var = r
        R = np.eye(2, dtype=float) * r
        y_res = z - H @ self.x
        S = H @ self.P @ H.T + R
        try:
            det = float(S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0])
            if np.isfinite(det) and det > 1e-9:
                inv = np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]]) / det
                self.last_m_dist2 = float(y_res @ inv @ y_res)
            else:
                self.last_m_dist2 = float(y_res @ y_res) / max(1.0, r)
        except Exception:
            self.last_m_dist2 = 0.0
        self.last_residual = (float(y_res[0]), float(y_res[1]))
        self.report_residual(self.last_m_dist2)
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            self.coast_count += 1
            return self.state
        self.x = self.x + K @ y_res
        # Joseph form (numerically stable vs (I-KH)P)
        I_KH = np.eye(4) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T
        self.coast_count = 0
        return self.state

    def step(
        self, measurement: tuple[float, float] | None, dt: float | None = None, meas_var: float | None = None
    ) -> tuple[float, float, float, float]:
        """Fusion entry: measurement or None -> predict-only coast."""
        if measurement is None:
            if not self.initialized:
                return self.state
            self.coast_count += 1
            return self.predict(dt)
        try:
            return self.update(float(measurement[0]), float(measurement[1]), dt, meas_var=meas_var)
        except Exception:
            return self.update(float(measurement[0]), float(measurement[1]), dt)

    @property
    def is_coasting(self) -> bool:
        return self.coast_count > 0

    @property
    def stale(self) -> bool:
        return self.coast_count > int(self.config.max_coast)

    @property
    def cov_xy(self) -> np.ndarray:
        try:
            return np.array([[self.P[0, 0], self.P[0, 1]], [self.P[1, 0], self.P[1, 1]]], dtype=float)
        except Exception:
            return np.eye(2) * 100.0

    @property
    def p_trace(self) -> float:
        try:
            return float(np.trace(self.P))
        except Exception:
            return 400.0

    @property
    def uncertainty_radius(self) -> float:
        """1-sigma position uncertainty radius px (for search/reacq sizing)."""
        try:
            vals = np.linalg.eigvalsh(self.cov_xy)
            return float(np.sqrt(max(1.0, float(np.max(vals)))))
        except Exception:
            return 10.0

    def lock_quality(self) -> dict:
        """Lock-quality indicators for gating control and M/N logic."""
        try:
            p_xy = float(self.P[0, 0] + self.P[1, 1])
            spd = float(np.hypot(self.x[2], self.x[3]))
            # quality in [0,1]: low covariance + active track + small residual
            cov_score = 1.0 / (1.0 + p_xy / 200.0)
            coast_pen = 1.0 / (1.0 + float(self.coast_count) / 3.0)
            res_pen = 1.0 / (1.0 + float(self.last_m_dist2) / 6.0)
            q = float(np.clip(cov_score * 0.5 + coast_pen * 0.3 + res_pen * 0.2, 0.0, 1.0))
            return {
                "quality": q, "p_xy": p_xy, "p_trace": self.p_trace,
                "coast": int(self.coast_count), "m_dist2": float(self.last_m_dist2),
                "speed_px_s": spd, "q_boost": float(self._q_boost),
                "locked": bool(self.initialized and self.coast_count == 0 and p_xy < 800.0),
            }
        except Exception:
            return {"quality": 0.0, "locked": False}
