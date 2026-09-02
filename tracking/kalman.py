# tracking/kalman.py - Constant-velocity Kalman predictor for beacon occlusion handling
#
# State: [x, y, vx, vy]^T  (image or world coords, px and px/s)
# Model: x_{k+1} = F(dt) * x_k + w,  z_k = H * x_k + v
#   F = [[1,0,dt,0],[0,1,0,dt],[0,0,1,0],[0,0,0,1]]
#   H = [[1,0,0,0],[0,1,0,0]]
# Handles detection dropout via pure prediction (coast) using last velocity.
# get_state_vector() from Target already returns [x,y,vx,vy] so this filter
# is drop-in for Target dynamics and for FOV-space tracking.

from __future__ import annotations

import numpy as np

class KalmanFilter:
    """
    Constant-velocity Kalman filter — predicts through occlusion.

    - process_var (q): acceleration noise variance; larger → more responsive to maneuvers
    - meas_var (r): measurement noise variance; larger → trusts prediction more
    Typical tuning for 30 Hz, 640px FOV:
      q ~ 8–16, r ~ 4–9 gives smooth yet responsive tracking.
    """

    def __init__(
        self,
        process_var: float = 40.0,
        meas_var: float = 4.0,
        initial_state: np.ndarray | None = None,
        initial_cov_scale: float = 500.0,
    ):
        self.process_var = float(process_var)
        self.meas_var = float(meas_var)
        # State 4x1 and covariance 4x4; None until first measurement seeds it
        self.x: np.ndarray | None = None
        self.P: np.ndarray | None = None
        self._init_cov_scale = float(initial_cov_scale)
        self._prev_z: tuple[float, float] | None = None
        self._last_dt: float = 0.033
        if initial_state is not None:
            self.x = np.array(initial_state, dtype=float).reshape(4)
            self.P = np.eye(4) * self._init_cov_scale
            self.P[2, 2] = self._init_cov_scale * 0.2
            self.P[3, 3] = self._init_cov_scale * 0.2

    def is_initialized(self) -> bool:
        return self.x is not None and self.P is not None

    def init_from_measurement(self, z: tuple[float, float], vel: tuple[float, float] | None = None) -> np.ndarray:
        """Seed filter from first detection (pos, optional vel)."""
        vx, vy = (0.0, 0.0) if vel is None else (float(vel[0]), float(vel[1]))
        self.x = np.array([float(z[0]), float(z[1]), vx, vy], dtype=float)
        self.P = np.eye(4) * self._init_cov_scale
        # Large initial velocity uncertainty so second measurement quickly corrects velocity
        self.P[2, 2] = 2000.0
        self.P[3, 3] = 2000.0
        self._prev_z = (float(z[0]), float(z[1]))
        return self.get_pos()  # type: ignore

    def predict(self, dt: float) -> tuple[float, float] | None:
        """Time update — coast with current velocity. Returns predicted (x,y) or None."""
        if not self.is_initialized():
            return None
        dt = float(dt)
        self._last_dt = dt
        if dt < 1e-6:
            return self.get_pos()
        F = np.array(
            [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1, 0],
             [0, 0, 0, 1]],
            dtype=float,
        )
        # Process noise for white-noise acceleration model
        q = float(self.process_var)
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        Q = np.array(
            [[dt4 / 4, 0, dt3 / 2, 0],
             [0, dt4 / 4, 0, dt3 / 2],
             [dt3 / 2, 0, dt2, 0],
             [0, dt3 / 2, 0, dt2]],
            dtype=float,
        ) * q
        self.x = F @ self.x  # type: ignore
        self.P = F @ self.P @ F.T + Q  # type: ignore
        return self.get_pos()

    def update(self, z: tuple[float, float]) -> tuple[float, float]:
        """Measurement update with detection (x,y). Returns corrected (x,y)."""
        if not self.is_initialized():
            return self.init_from_measurement(z)  # type: ignore
        # Fast velocity seeding on second measurement: if velocity still near zero,
        # estimate from finite difference and seed before Kalman correction for
        # quick convergence (handles first motion after occlusion).
        if self._prev_z is not None and self.x is not None and abs(float(self.x[2])) < 2.0 and abs(float(self.x[3])) < 2.0:
            dt = float(self._last_dt) if self._last_dt > 1e-6 else 0.033
            vx_est = (float(z[0]) - float(self._prev_z[0])) / dt
            vy_est = (float(z[1]) - float(self._prev_z[1])) / dt
            # Only seed if reasonable (|v| < 2000 px/s to reject outliers)
            if abs(vx_est) < 2000 and abs(vy_est) < 2000 and (abs(vx_est) > 1 or abs(vy_est) > 1):
                self.x[2] = float(vx_est) * 0.8 + float(self.x[2]) * 0.2
                self.x[3] = float(vy_est) * 0.8 + float(self.x[3]) * 0.2
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        R = np.eye(2) * float(self.meas_var)
        z_np = np.array([float(z[0]), float(z[1])], dtype=float)
        y = z_np - H @ self.x  # type: ignore
        S = H @ self.P @ H.T + R  # type: ignore
        # Kalman gain
        try:
            K = self.P @ H.T @ np.linalg.inv(S)  # type: ignore
        except np.linalg.LinAlgError:
            K = self.P @ H.T / (np.trace(S) / 2 + 1e-6)  # type: ignore
        self.x = self.x + K @ y  # type: ignore
        I = np.eye(4)
        self.P = (I - K @ H) @ self.P  # type: ignore
        self._prev_z = (float(z[0]), float(z[1]))
        return self.get_pos()  # type: ignore

    def get_state(self) -> np.ndarray | None:
        """Full state [x,y,vx,vy] or None."""
        if self.x is None:
            return None
        return self.x.copy()

    def get_state_vector(self) -> np.ndarray | None:
        """Alias for get_state (mirrors Target.get_state_vector)."""
        return self.get_state()

    def get_pos(self) -> tuple[float, float] | None:
        if self.x is None:
            return None
        return (float(self.x[0]), float(self.x[1]))

    def get_vel(self) -> tuple[float, float] | None:
        if self.x is None:
            return None
        return (float(self.x[2]), float(self.x[3]))

    def reset(self) -> None:
        self.x = None
        self.P = None
        self._prev_z = None
        self._last_dt = 0.033
