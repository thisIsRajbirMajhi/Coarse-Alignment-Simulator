# tracking/imm — Interacting Multiple Model tracker (CV + CT + CV-agile bank)
#
# Why: single CV fails on turns/maneuvers. IMM runs 3 models in parallel:
#   Model 0 "smooth"  : CV, low process noise    (straight cruise)
#   Model 1 "turn"    : CT (coordinated turn) with adaptive turn rate omega
#                       (gentle / sustained turns, §10 "Turning Motion")
#   Model 2 "agile"   : CV, high process noise   (maneuvers / abrupt changes)
# and mixes them by likelihood each frame (standard IMM: mix -> predict ->
# update -> model-probability update -> combination).
# Spec mapping (§10-§12): Constant Velocity -> Model 0, Turning Motion ->
# Model 1 (true CT transition, not Q-only), Maneuvering -> Model 2.
#
# Numpy only, no scipy. API mirrors KalmanTracker (position/velocity/state,
# step/update/predict/stale/initialized) so TrackingPipeline can swap it in
# with use_imm=True. Extra: model_probs, active_model, cov_xy, lock_quality,
# mahalanobis, peek_predict.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.config_base import BaseValidatedConfig, clip_field
from tracking.kalman import KALMAN_LIMITS

IMM_LIMITS = {
    "process_noise": KALMAN_LIMITS["process_noise"],
    "measurement_noise": KALMAN_LIMITS["measurement_noise"],
    "max_coast": KALMAN_LIMITS["max_coast"],
    "q_scale_agile": (5.0, 40.0),
}

IMM_DEFAULTS = {
    "process_noise": 8.0,
    "measurement_noise": 9.0,
    "max_coast": 10,
    "q_scale_agile": 20.0,  # wide separation so agile wins on maneuvers
}


@dataclass
class IMMConfig(BaseValidatedConfig):
    LIMITS = IMM_LIMITS
    DEFAULTS = {k: v for k, v in IMM_DEFAULTS.items() if k in IMM_LIMITS}

    process_noise: float = IMM_DEFAULTS["process_noise"]
    measurement_noise: float = IMM_DEFAULTS["measurement_noise"]
    max_coast: int = IMM_DEFAULTS["max_coast"]
    q_scale_agile: float = IMM_DEFAULTS["q_scale_agile"]

    def validate(self) -> "IMMConfig":
        self.process_noise = float(clip_field(self.process_noise, *self.LIMITS["process_noise"]))
        self.measurement_noise = float(clip_field(self.measurement_noise, *self.LIMITS["measurement_noise"]))
        self.max_coast = int(clip_field(int(self.max_coast), *self.LIMITS["max_coast"]))
        self.q_scale_agile = float(clip_field(self.q_scale_agile, *self.LIMITS["q_scale_agile"]))
        return self


class IMMTracker:
    """3-model IMM: CV(smooth) + CT(turn, adaptive omega) + CV(agile).

    State per filter is [x,y,vx,vy]; the CT model uses a coordinated-turn
    transition with turn rate omega (rad/s, image px space). Omega is
    estimated online from velocity heading change (§11 turn-rate quantity)
    and exposed via ``turn_rate``. API mirrors KalmanTracker.
    """

    # Turn-rate limits (rad/s in image plane) for the CT model.
    OMEGA_MAX = 3.0
    SPEED_MIN_FOR_OMEGA = 15.0  # px/s: below this heading is noise

    def __init__(self, config: IMMConfig | None = None):
        self.config = (config or IMMConfig()).validate()
        q0 = float(self.config.process_noise)
        self._qs = [q0 * 0.1, q0, q0 * float(self.config.q_scale_agile)]
        # Adaptive turn rate for Model 1 (CT). 0 == straight (CT == CV).
        self._omega = 0.0
        self._prev_vel: tuple[float, float] | None = None
        # Markov transition: sticky diagonal, small switching prob
        self._Pi = np.array(
            [[0.90, 0.05, 0.05],
             [0.05, 0.90, 0.05],
             [0.05, 0.05, 0.90]],
            dtype=float,
        )
        self._xs = [np.zeros(4) for _ in range(3)]
        self._Ps = [np.eye(4) * 100.0 for _ in range(3)]
        self.mu = np.array([1 / 3, 1 / 3, 1 / 3], dtype=float)
        self.x = np.zeros(4, dtype=float)
        self.P = np.eye(4, dtype=float) * 100.0
        self.initialized = False
        self.coast_count = 0
        self.last_dt = 1 / 30
        self.last_m_dist2 = 0.0
        self.last_meas_var = float(self.config.measurement_noise)
        self.last_residual = (0.0, 0.0)

    # -- compat API ---------------------------------------------------------
    @property
    def position(self):
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self):
        return float(self.x[2]), float(self.x[3])

    @property
    def state(self):
        return float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])

    @property
    def model_probs(self):
        return (float(self.mu[0]), float(self.mu[1]), float(self.mu[2]))

    @property
    def active_model(self) -> int:
        return int(np.argmax(self.mu))

    @property
    def is_coasting(self) -> bool:
        return self.coast_count > 0

    @property
    def stale(self) -> bool:
        return self.coast_count > int(self.config.max_coast)

    @property
    def cov_xy(self) -> np.ndarray:
        try:
            return np.array([[self.P[0, 0], self.P[0, 1]], [self.P[1, 0], self.P[1, 1]]])
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
        try:
            vals = np.linalg.eigvalsh(self.cov_xy)
            return float(np.sqrt(max(1.0, float(np.max(vals)))))
        except Exception:
            return 10.0

    @property
    def turn_rate(self) -> float:
        """Current CT turn-rate estimate omega (rad/s). §11 advanced state."""
        try:
            return float(self._omega)
        except Exception:
            return 0.0

    @property
    def state_full(self) -> tuple[float, float, float, float, float]:
        """Extended state [x, y, vx, vy, omega] (§11 advanced quantities)."""
        return (float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3]), float(self._omega))

    def reset(self, x: float = 0.0, y: float = 0.0, vx: float = 0.0, vy: float = 0.0) -> None:
        for i in range(3):
            self._xs[i][:] = (float(x), float(y), float(vx), float(vy))
            self._Ps[i] = np.eye(4) * 100.0
        self.x[:] = (float(x), float(y), float(vx), float(vy))
        self.P = np.eye(4) * 100.0
        self.mu[:] = 1 / 3
        self.initialized = True
        self.coast_count = 0
        self._omega = 0.0
        self._prev_vel = None

    @staticmethod
    def _F_CV(dt: float) -> np.ndarray:
        return np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)

    @staticmethod
    def _F_CT(dt: float, omega: float) -> np.ndarray:
        """Coordinated-turn transition for state [x,y,vx,vy]."""
        try:
            w = float(omega)
        except Exception:
            w = 0.0
        if abs(w) < 1e-3:
            return IMMTracker._F_CV(dt)
        try:
            s = float(np.sin(w * dt))
            c = float(np.cos(w * dt))
            return np.array([
                [1, 0, s / w, -(1 - c) / w],
                [0, 1, (1 - c) / w, s / w],
                [0, 0, c, -s],
                [0, 0, s, c],
            ], dtype=float)
        except Exception:
            return IMMTracker._F_CV(dt)

    def _F(self, dt: float, model: int = 1) -> np.ndarray:
        # Model 1 is the true turning model (CT); 0/2 stay CV with wide Q
        # spacing ([0.1x, 1x, 20x]) for cruise vs maneuver separation.
        try:
            m = int(model)
        except Exception:
            m = 1
        if m == 1:
            return self._F_CT(dt, self._omega)
        return self._F_CV(dt)

    def _update_turn_rate(self, dt: float) -> None:
        """Adapt omega from heading change of the combined velocity."""
        try:
            dtc = float(dt)
            if not np.isfinite(dtc) or dtc < 1e-4:
                return
            vx, vy = float(self.x[2]), float(self.x[3])
            spd = float(np.hypot(vx, vy))
            if spd < float(self.SPEED_MIN_FOR_OMEGA):
                # Too slow: heading is noise -> decay to straight.
                self._omega = float(self._omega * 0.9)
                self._prev_vel = (vx, vy)
                return
            if self._prev_vel is None:
                self._prev_vel = (vx, vy)
                return
            pvx, pvy = float(self._prev_vel[0]), float(self._prev_vel[1])
            if float(np.hypot(pvx, pvy)) < float(self.SPEED_MIN_FOR_OMEGA):
                self._prev_vel = (vx, vy)
                return
            a1 = float(np.arctan2(pvy, pvx))
            a2 = float(np.arctan2(vy, vx))
            d = (a2 - a1 + float(np.pi)) % (2 * float(np.pi)) - float(np.pi)
            inst = float(np.clip(d / max(dtc, 1e-4), -self.OMEGA_MAX, self.OMEGA_MAX))
            # Low-pass: responsive but stable (0.3 new / 0.7 old).
            self._omega = float(np.clip(0.7 * float(self._omega) + 0.3 * inst,
                                        -self.OMEGA_MAX, self.OMEGA_MAX))
            self._prev_vel = (vx, vy)
        except Exception:
            pass

    @staticmethod
    def _Q(dt: float, q: float) -> np.ndarray:
        return q * np.array(
            [[dt**4 / 4, 0, dt**3 / 2, 0], [0, dt**4 / 4, 0, dt**3 / 2],
             [dt**3 / 2, 0, dt**2, 0], [0, dt**3 / 2, 0, dt**2]])

    _H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)

    def _mix(self) -> tuple[list[np.ndarray], list[np.ndarray]]:
        mu = self.mu
        c = self._Pi.T @ mu  # predicted mode probs
        c = np.clip(c, 1e-9, None)
        mix_xs, mix_Ps = [], []
        for j in range(3):
            w = (self._Pi[:, j] * mu) / max(c[j], 1e-9)
            xm = sum(w[i] * self._xs[i] for i in range(3))
            Pm = sum(w[i] * (self._Ps[i] + np.outer(self._xs[i] - xm, self._xs[i] - xm)) for i in range(3))
            mix_xs.append(np.array(xm))
            mix_Ps.append(np.array(Pm))
        return mix_xs, mix_Ps

    def predict(self, dt: float | None = None):
        dtc = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
        self.last_dt = dtc
        if not self.initialized:
            return self.state
        mix_xs, mix_Ps = self._mix()
        for j in range(3):
            Fj = self._F(dtc, j)
            Q = self._Q(dtc, self._qs[j])
            self._xs[j] = Fj @ mix_xs[j]
            self._Ps[j] = Fj @ mix_Ps[j] @ Fj.T + Q
        c = np.clip(self._Pi.T @ self.mu, 1e-9, None)
        self.mu = c / np.sum(c)
        self._combine()
        self._update_turn_rate(dtc)
        return self.state

    def _combine(self) -> None:
        xc = sum(self.mu[j] * self._xs[j] for j in range(3))
        Pc = sum(self.mu[j] * (self._Ps[j] + np.outer(self._xs[j] - xc, self._xs[j] - xc)) for j in range(3))
        self.x = np.array(xc)
        self.P = np.array(Pc)

    @staticmethod
    def _gauss_likelihood(res: np.ndarray, S: np.ndarray) -> float:
        try:
            det = float(S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0])
            if not np.isfinite(det) or det < 1e-9:
                return 1e-9
            inv = np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]]) / det
            d2 = float(res @ inv @ res)
            d2 = float(np.clip(d2, 0.0, 50.0))
            return float(np.exp(-0.5 * d2) / (2 * np.pi * np.sqrt(det) + 1e-9))
        except Exception:
            return 1e-9

    def update(self, cx: float, cy: float, dt: float | None = None, meas_var: float | None = None):
        if not self.initialized:
            self.reset(cx, cy)
            if meas_var is not None:
                try:
                    self.last_meas_var = float(np.clip(float(meas_var), 0.5, 100.0))
                except Exception:
                    pass
            return self.state
        # IMM cycle: mix already inside predict; here predict-then-update per mode
        dtc = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
        self.last_dt = dtc
        mix_xs, mix_Ps = self._mix()
        H = self._H
        r = float(meas_var) if meas_var is not None else float(self.config.measurement_noise)
        r = float(np.clip(r, 0.5, 100.0))
        self.last_meas_var = r
        R = np.eye(2) * r
        z = np.array([float(cx), float(cy)])
        if not np.all(np.isfinite(z)):
            self.coast_count += 1
            return self.state
        c_pred = np.clip(self._Pi.T @ self.mu, 1e-9, None)
        likes = np.zeros(3)
        for j in range(3):
            Fj = self._F(dtc, j)
            xp = Fj @ mix_xs[j]
            Pp = Fj @ mix_Ps[j] @ Fj.T + self._Q(dtc, self._qs[j])
            res = z - H @ xp
            S = H @ Pp @ H.T + R
            try:
                K = Pp @ H.T @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                K = np.zeros((4, 2))
            self._xs[j] = xp + K @ res
            I_KH = np.eye(4) - K @ H
            self._Ps[j] = I_KH @ Pp @ I_KH.T + K @ R @ K.T
            likes[j] = self._gauss_likelihood(res, S)
            if j == int(np.argmax(self.mu)):
                self.last_residual = (float(res[0]), float(res[1]))
        num = c_pred * np.clip(likes, 1e-12, None)
        denom = float(np.sum(num))
        self.mu = num / denom if denom > 1e-12 else np.array([1 / 3] * 3)
        self._combine()
        self._update_turn_rate(dtc)
        # combined residual Mahalanobis for diagnostics
        try:
            S_c = H @ self.P @ H.T + R
            res_c = z - H @ self.x
            det = float(S_c[0, 0] * S_c[1, 1] - S_c[0, 1] * S_c[1, 0])
            if np.isfinite(det) and det > 1e-9:
                inv = np.array([[S_c[1, 1], -S_c[0, 1]], [-S_c[1, 0], S_c[0, 0]]]) / det
                self.last_m_dist2 = float(res_c @ inv @ res_c)
        except Exception:
            pass
        self.coast_count = 0
        return self.state

    def step(self, measurement: tuple[float, float] | None, dt: float | None = None, meas_var: float | None = None):
        if measurement is None:
            if not self.initialized:
                return self.state
            self.coast_count += 1
            return self.predict(dt)
        try:
            return self.update(float(measurement[0]), float(measurement[1]), dt, meas_var=meas_var)
        except Exception:
            return self.update(float(measurement[0]), float(measurement[1]), dt)

    def peek_predict(self, dt: float | None = None):
        try:
            dtc = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
            F = self._F(dtc, int(np.argmax(self.mu)))
            # use combined state with nominal Q for peek
            Q = self._Q(dtc, self._qs[1])
            xp = F @ self.x
            Pp = F @ self.P @ F.T + Q
            return ((float(xp[0]), float(xp[1])), np.array([[Pp[0, 0], Pp[0, 1]], [Pp[1, 0], Pp[1, 1]]]))
        except Exception:
            return (self.position, self.cov_xy)

    def innovation_covariance(self, meas_var: float | None = None) -> np.ndarray:
        r = float(meas_var) if meas_var is not None else float(self.last_meas_var)
        H = self._H
        return H @ self.P @ H.T + np.eye(2) * float(np.clip(r, 0.5, 100.0))

    def mahalanobis(self, cx: float, cy: float, meas_var: float | None = None) -> float:
        try:
            S = self.innovation_covariance(meas_var)
            res = np.array([float(cx) - self.x[0], float(cy) - self.x[1]])
            det = float(S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0])
            if not np.isfinite(det) or det < 1e-6:
                return float(res @ res) / 9.0
            inv = np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]]) / det
            return float(res @ inv @ res)
        except Exception:
            return 1e9

    def lock_quality(self) -> dict:
        try:
            p_xy = float(self.P[0, 0] + self.P[1, 1])
            spd = float(np.hypot(self.x[2], self.x[3]))
            cov_score = 1.0 / (1.0 + p_xy / 200.0)
            coast_pen = 1.0 / (1.0 + float(self.coast_count) / 3.0)
            res_pen = 1.0 / (1.0 + float(self.last_m_dist2) / 6.0)
            # Bonus when one model dominates (confident regime)
            conf_bonus = float(np.max(self.mu)) * 0.1
            q = float(np.clip(cov_score * 0.5 + coast_pen * 0.3 + res_pen * 0.2 + conf_bonus, 0.0, 1.0))
            return {"quality": q, "p_xy": p_xy, "p_trace": self.p_trace,
                    "coast": int(self.coast_count), "m_dist2": float(self.last_m_dist2),
                    "speed_px_s": spd, "model_probs": self.model_probs,
                    "active_model": self.active_model, "turn_rate": float(self._omega),
                    "locked": bool(self.initialized and self.coast_count == 0 and p_xy < 800.0)}
        except Exception:
            return {"quality": 0.0, "locked": False}
