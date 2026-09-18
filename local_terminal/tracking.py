# local_terminal/tracking.py - Centroid target tracking engine per LocalTerminal.md
from __future__ import annotations

import math
from typing import Any

from local_terminal.config import AngularModelConfig, TrackingConfig


class TargetTracker:
    """
    Target tracking loop:
      - Centroid estimation
      - Angular error derivation via AngularModel
      - Prediction and smoothing
      - Lost target handling
    """

    def __init__(self, config: TrackingConfig | None = None, angular_model: AngularModelConfig | None = None):
        self.config = (config or TrackingConfig()).validate()
        self.angular_model = (angular_model or AngularModelConfig()).validate()

        self.tracking_active = False
        self.target_locked = False
        self.lost_time = 0.0

        # State estimates (pixels)
        self.smoothed_err_x = 0.0
        self.smoothed_err_y = 0.0
        self.vel_x = 0.0
        self.vel_y = 0.0
        self._last_raw_x = 0.0
        self._last_raw_y = 0.0
        self._initialized = False

        # PID servo state accumulators
        self._integral_x = 0.0
        self._integral_y = 0.0
        self._prev_err_x: float | None = None
        self._prev_err_y: float | None = None
        self._prev_deriv_x = 0.0
        self._prev_deriv_y = 0.0

    def reset(self) -> None:
        self.tracking_active = False
        self.target_locked = False
        self.lost_time = 0.0
        self.smoothed_err_x = 0.0
        self.smoothed_err_y = 0.0
        self.vel_x = 0.0
        self.vel_y = 0.0
        self._last_raw_x = 0.0
        self._last_raw_y = 0.0
        self._initialized = False
        self._integral_x = 0.0
        self._integral_y = 0.0
        self._prev_err_x = None
        self._prev_err_y = None
        self._prev_deriv_x = 0.0
        self._prev_deriv_y = 0.0

    def update(
        self,
        dt: float,
        target_in_fov: bool,
        spot_center_fov: tuple[float, float] | None,
        fov_size: tuple[int, int],
        camera_vel_px_s: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """
        Step the tracker with current frame observations.
        Returns tracking telemetry with pixel and angular errors.

        camera_vel_px_s: own-ship FOV velocity (+pan moves scene -x in FOV).
        Error-rate includes -camera_vel, so target velocity is compensated:
        v_target = d(err)/dt + camera_vel. Without it, own motion pollutes
        the estimate and causes feedback oscillation.
        """
        fw, fh = fov_size
        cx_target = fw * 0.5
        cy_target = fh * 0.5

        if not target_in_fov or spot_center_fov is None:
            self.lost_time += dt
            self.target_locked = False
            if self.lost_time > 1.0:
                self._initialized = False
            return {
                "active": self.config.mode in ("TRACKING", "AUTO"),
                "locked": False,
                "error_px": (self.smoothed_err_x, self.smoothed_err_y),
                "error_urad": (
                    self.smoothed_err_x * self.angular_model.pixel_to_angle_x,
                    self.smoothed_err_y * self.angular_model.pixel_to_angle_y,
                ),
                "lost_time": self.lost_time,
                "lost_behavior": self.config.lost_target_behavior,
            }

        # Spot is present
        self.lost_time = 0.0
        self.target_locked = True
        sx, sy = spot_center_fov
        raw_err_x = sx - cx_target
        raw_err_y = sy - cy_target

        if not self._initialized:
            self._last_raw_x = raw_err_x
            self._last_raw_y = raw_err_y
            self.smoothed_err_x = raw_err_x
            self.smoothed_err_y = raw_err_y
            self.vel_x = 0.0
            self.vel_y = 0.0
            self._initialized = True
        else:
            if dt > 1e-4:
                d_err_x = (raw_err_x - self._last_raw_x) / dt
                d_err_y = (raw_err_y - self._last_raw_y) / dt
                if camera_vel_px_s is not None:
                    # FOV error moves opposite to camera: v_tgt = d_err + v_cam
                    curr_vx = d_err_x + float(camera_vel_px_s[0])
                    curr_vy = d_err_y + float(camera_vel_px_s[1])
                else:
                    curr_vx, curr_vy = d_err_x, d_err_y
                # Clamp spike (e.g. reacquire jump) to 2000 px/s before filtering.
                curr_vx = float(max(-2000.0, min(2000.0, curr_vx)))
                curr_vy = float(max(-2000.0, min(2000.0, curr_vy)))
                alpha_v = 0.2
                self.vel_x = alpha_v * curr_vx + (1.0 - alpha_v) * self.vel_x
                self.vel_y = alpha_v * curr_vy + (1.0 - alpha_v) * self.vel_y

            self._last_raw_x = raw_err_x
            self._last_raw_y = raw_err_y

            # Exponential smoothing
            alpha = max(0.01, min(1.0, 1.0 - self.config.smoothing))
            self.smoothed_err_x = alpha * raw_err_x + (1.0 - alpha) * self.smoothed_err_x
            self.smoothed_err_y = alpha * raw_err_y + (1.0 - alpha) * self.smoothed_err_y

        # Predictive projection if enabled
        pred_x = self.smoothed_err_x
        pred_y = self.smoothed_err_y
        if self.config.prediction:
            pred_x += self.vel_x * self.config.prediction_horizon
            pred_y += self.vel_y * self.config.prediction_horizon

        # Angular error in microradians via angular model
        err_urad_x = pred_x * self.angular_model.pixel_to_angle_x
        err_urad_y = pred_y * self.angular_model.pixel_to_angle_y

        return {
            "active": self.config.mode in ("TRACKING", "AUTO"),
            "locked": True,
            "error_px": (pred_x, pred_y),
            "error_urad": (err_urad_x, err_urad_y),
            "lost_time": 0.0,
            "lost_behavior": self.config.lost_target_behavior,
        }

    def compute_control(self, err_x: float, err_y: float, dt: float) -> tuple[float, float]:
        """
        Compute closed-loop PID servo tracking commands (pixels) with:
          - Dead-zone suppression (prevents mechanical limit-cycling)
          - Proportional response
          - Anti-windup integral accumulation (steady-state drift rejection)
          - Low-pass filtered derivative action (damping oscillations)
          - Output saturation clamping
        """
        dt = float(max(1e-4, min(dt, 0.2)))
        dz = float(self.config.dead_zone)

        eff_err_x = 0.0 if abs(err_x) < dz else err_x
        eff_err_y = 0.0 if abs(err_y) < dz else err_y

        # Proportional
        p_x = float(self.config.kp) * eff_err_x
        p_y = float(self.config.kp) * eff_err_y

        # Integral with anti-windup clamping (integral path alone saturates
        # at output_clamp; P+D add within the same clamp).
        clamp = float(self.config.output_clamp)
        i_limit = clamp / max(1e-4, float(self.config.ki)) if float(self.config.ki) > 1e-6 else clamp
        self._integral_x = float(max(-i_limit, min(self._integral_x + eff_err_x * dt, i_limit)))
        self._integral_y = float(max(-i_limit, min(self._integral_y + eff_err_y * dt, i_limit)))
        i_x = float(self.config.ki) * self._integral_x
        i_y = float(self.config.ki) * self._integral_y

        # Derivative with low-pass filtering
        if self._prev_err_x is None or self._prev_err_y is None:
            deriv_x, deriv_y = 0.0, 0.0
        else:
            raw_dx = (eff_err_x - self._prev_err_x) / dt
            raw_dy = (eff_err_y - self._prev_err_y) / dt
            alpha_d = 0.3
            deriv_x = alpha_d * raw_dx + (1.0 - alpha_d) * self._prev_deriv_x
            deriv_y = alpha_d * raw_dy + (1.0 - alpha_d) * self._prev_deriv_y
            self._prev_deriv_x = deriv_x
            self._prev_deriv_y = deriv_y

        self._prev_err_x = eff_err_x
        self._prev_err_y = eff_err_y
        d_x = float(self.config.kd) * deriv_x
        d_y = float(self.config.kd) * deriv_y

        out_x = float(max(-clamp, min(p_x + i_x + d_x, clamp)))
        out_y = float(max(-clamp, min(p_y + i_y + d_y, clamp)))
        return out_x, out_y

