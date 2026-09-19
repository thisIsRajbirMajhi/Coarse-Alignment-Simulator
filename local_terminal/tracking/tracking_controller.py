# local_terminal/tracking_controller.py - Module 9: Tracking Controller (§§20-21).
from __future__ import annotations

from local_terminal.tracking.tracking import TargetTracker


class TrackingController:
    """Separate pan/tilt PID loops. Outputs requested pan/tilt command,
    never teleports (§21). Wraps the proven TargetTracker servo."""

    def __init__(self, tracking_config=None, angular_model=None):
        self._tracker = TargetTracker(tracking_config, angular_model)
        # expose estimator-compatible velocity for coasting
        self.vel_x = 0.0
        self.vel_y = 0.0

    @property
    def config(self):
        return self._tracker.config

    @config.setter
    def config(self, value):
        self._tracker.config = value

    @property
    def angular_model(self):
        return self._tracker.angular_model

    @angular_model.setter
    def angular_model(self, value):
        self._tracker.angular_model = value

    def reset(self) -> None:
        self._tracker.reset()
        self.vel_x = self.vel_y = 0.0

    def update(self, dt, target_present, spot, fov_size, camera_vel=None):
        res = self._tracker.update(dt, target_present, spot, fov_size, camera_vel_px_s=camera_vel)
        self.vel_x = float(self._tracker.vel_x)
        self.vel_y = float(self._tracker.vel_y)
        return res

    def compute_control(self, err_x: float, err_y: float, dt: float):
        return self._tracker.compute_control(err_x, err_y, dt)

    def pixel_to_angle(self, err_x: float, err_y: float) -> tuple[float, float]:
        return (err_x * self._tracker.angular_model.pixel_to_angle_x,
                err_y * self._tracker.angular_model.pixel_to_angle_y)
