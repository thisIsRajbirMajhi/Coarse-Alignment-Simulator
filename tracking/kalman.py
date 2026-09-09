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
    """Minimal 4-state constant-velocity filter (numpy only, no scipy)."""

    def __init__(self, config: KalmanConfig | None = None):
        self.config = (config or KalmanConfig()).validate()
        self.x = np.zeros(4, dtype=float)  # [x, y, vx, vy]
        self.P = np.eye(4, dtype=float) * 100.0
        self.initialized = False
        self.coast_count = 0
        self.last_dt = 1 / 30

    def reset(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x[:] = (float(x), float(y), 0.0, 0.0)
        self.P = np.eye(4, dtype=float) * 100.0
        self.initialized = True
        self.coast_count = 0

    @property
    def position(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> tuple[float, float]:
        return float(self.x[2]), float(self.x[3])

    @property
    def state(self) -> tuple[float, float, float, float]:
        return float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])

    def predict(self, dt: float | None = None) -> tuple[float, float, float, float]:
        dt = float(np.clip(float(dt if dt is not None else self.last_dt), 1e-4, 0.2))
        self.last_dt = dt
        F = np.array(
            [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1, 0],
             [0, 0, 0, 1]],
            dtype=float,
        )
        q = float(self.config.process_noise)
        # Discrete white-noise acceleration model
        Q = q * np.array(
            [[dt**4 / 4, 0, dt**3 / 2, 0],
             [0, dt**4 / 4, 0, dt**3 / 2],
             [dt**3 / 2, 0, dt**2, 0],
             [0, dt**3 / 2, 0, dt**2]],
            dtype=float,
        )
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        return self.state

    def update(self, cx: float, cy: float, dt: float | None = None) -> tuple[float, float, float, float]:
        if not self.initialized:
            self.reset(cx, cy)
            return self.state
        # Predict to measurement time first (fusion rule)
        self.predict(dt)
        z = np.array([float(cx), float(cy)], dtype=float)
        if not np.all(np.isfinite(z)):
            self.coast_count += 1
            return self.state
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        r = float(self.config.measurement_noise)
        R = np.eye(2, dtype=float) * r
        y_res = z - H @ self.x
        S = H @ self.P @ H.T + R
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            self.coast_count += 1
            return self.state
        self.x = self.x + K @ y_res
        self.P = (np.eye(4) - K @ H) @ self.P
        self.coast_count = 0
        return self.state

    def step(
        self, measurement: tuple[float, float] | None, dt: float | None = None
    ) -> tuple[float, float, float, float]:
        """Fusion entry: measurement or None -> predict-only coast."""
        if measurement is None:
            if not self.initialized:
                return self.state
            self.coast_count += 1
            return self.predict(dt)
        return self.update(float(measurement[0]), float(measurement[1]), dt)

    @property
    def is_coasting(self) -> bool:
        return self.coast_count > 0

    @property
    def stale(self) -> bool:
        return self.coast_count > int(self.config.max_coast)
