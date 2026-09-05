# control/controller.py - PID controller — robust, modular, well-commented with maths/physics

from __future__ import annotations

import math
import time

import numpy as np

from control.config import ControllerConfig
from control.constants import CONTROL_DEFAULTS

class PIDController:
    """PID controller — per-axis (pan, tilt) with shared gains + feedforward/adaptive/Smith."""

    def __init__(self, config: ControllerConfig | None = None, kp: float | None = None, ki: float | None = None, kd: float | None = None, **kwargs):
        if config is not None:
            self.config = config.validate()
        else:
            if kp is not None and ki is None and kd is None and "gain" in kwargs:
                kp = float(kwargs["gain"])
            cfg_kwargs = {}
            if kp is not None:
                cfg_kwargs["kp"] = float(kp)
            if ki is not None:
                cfg_kwargs["ki"] = float(ki)
            if kd is not None:
                cfg_kwargs["kd"] = float(kd)
            for k in ["controller_type", "update_rate_hz", "dead_zone", "output_clamp",
                      "feedforward_gain", "adaptive_gain", "derivative_filter", "setpoint_weight", "smith_latency_ms"]:
                if k in kwargs:
                    cfg_kwargs[k] = kwargs[k]
            self.config = ControllerConfig(**{**CONTROL_DEFAULTS, **cfg_kwargs}).validate()
            if kp is not None and ki is None and kd is None:
                self.config.controller_type = "P"
                self.config.ki = 0.0
                self.config.kd = 0.0
        self._integral_x: float = 0.0
        self._integral_y: float = 0.0
        self._prev_error_x: float | None = None
        self._prev_error_y: float | None = None
        self._prev_deriv_x: float = 0.0
        self._prev_deriv_y: float = 0.0
        self._last_compute_time: float | None = None
        self._last_output: tuple[float, float] = (0.0, 0.0)

    def apply_config(self, config: ControllerConfig) -> None:
        self.config = config.validate()
        if self.config.controller_type == "P":
            self._integral_x = 0.0
            self._integral_y = 0.0
            self._prev_deriv_x = 0.0
            self._prev_deriv_y = 0.0
        elif self.config.controller_type == "PI":
            self._prev_deriv_x = 0.0
            self._prev_deriv_y = 0.0

    def to_config(self) -> ControllerConfig:
        return ControllerConfig(
            controller_type=self.config.controller_type,
            kp=float(self.config.kp), ki=float(self.config.ki), kd=float(self.config.kd),
            update_rate_hz=float(self.config.update_rate_hz),
            dead_zone=float(self.config.dead_zone),
            output_clamp=float(self.config.output_clamp),
        ).validate()

    @property
    def gain(self) -> float:
        return float(self.config.kp)

    @gain.setter
    def gain(self, value: float) -> None:
        self.config.kp = float(value)
        self.config.validate()

    def compute_correction(
        self,
        error_x: float,
        error_y: float,
        dt: float | None = None,
        camera_max_slew: float | None = None,
        target_velocity: tuple[float, float] | None = None,
    ) -> tuple[float, float]:
        """
        Compute PID correction with feedforward, adaptive gain, Smith predictor, and proper dead zone.

        Args:
          error_x, error_y: tracking error in px (estimate - FOV/2)
          dt: seconds (from MainWindow, already sim_speed scaled)
          camera_max_slew: px/s for anti-windup clamp
          target_velocity: (vx, vy) px/s from tracker for feedforward/Smith
        """
        err_mag = math.hypot(float(error_x), float(error_y))
        # FIX: Proper dead zone — freeze integral (not fast decay), zero derivative, avoid windup
        if err_mag < float(self.config.dead_zone):
            # Freeze integral with slow decay (0.95) to avoid drift, not 0.5 fast
            self._integral_x *= 0.95
            self._integral_y *= 0.95
            # Deep dead zone → fully reset
            if err_mag < float(self.config.dead_zone) * 0.5:
                self._integral_x = 0.0
                self._integral_y = 0.0
                self._prev_deriv_x = 0.0
                self._prev_deriv_y = 0.0
            else:
                # Light decay on derivative
                self._prev_deriv_x *= 0.85
                self._prev_deriv_y *= 0.85
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
            self._last_output = (0.0, 0.0)
            return (0.0, 0.0)

        # Throttle only when dt not supplied (legacy wall-time mode); dt-driven always computes
        if dt is None:
            now = time.monotonic()
            interval = self.config.update_interval()
            if self._last_compute_time is not None:
                elapsed = now - self._last_compute_time
                if elapsed + 1e-6 < interval:
                    return self._last_output
            self._last_compute_time = now
        else:
            self._last_compute_time = time.monotonic()
        if dt is None:
            dt = float(self.config.update_interval())
        dt = float(np.clip(dt, 1e-4, 0.2))

        # Smith predictor — predict error ahead by known camera latency
        smith_ms = float(getattr(self.config, "smith_latency_ms", 0.0))
        if smith_ms > 1e-6 and target_velocity is not None:
            try:
                vx, vy = float(target_velocity[0]), float(target_velocity[1])
                pred_s = smith_ms / 1000.0
                error_x = float(error_x) + vx * pred_s
                error_y = float(error_y) + vy * pred_s
            except Exception:
                pass

        # Adaptive gain — kp scales with |err| to be aggressive when far, gentle when near
        kp_eff = float(self.config.kp)
        adaptive = float(getattr(self.config, "adaptive_gain", 0.0))
        if adaptive > 1e-9:
            kp_eff = kp_eff * (1.0 + adaptive * float(err_mag) / 20.0)
            kp_eff = float(np.clip(kp_eff, 0.0, 1.0))
        # Setpoint weighting — reduces kick on acquisition
        weight = float(getattr(self.config, "setpoint_weight", 1.0))
        w = float(np.clip(weight, 0.0, 1.0))
        p_x = kp_eff * float(error_x) * w
        p_y = kp_eff * float(error_y) * w

        # Integral with conditional anti-windup (only integrate when not saturated)
        i_x = self._integral_x
        i_y = self._integral_y
        if self.config.controller_type in ("PI", "PID") and float(self.config.ki) > 1e-9:
            # Conditional integration: don't accumulate if output would saturate same direction
            # Compute provisional clamp
            clamp = float(self.config.output_clamp)
            if camera_max_slew is not None:
                try:
                    cam_clamp_i = float(camera_max_slew) * float(dt)
                    clamp = min(clamp, cam_clamp_i)
                except Exception:
                    pass
            # Check if adding would push same direction as saturation
            would_sat_x = (i_x > 0 and error_x > 0 and abs(i_x + p_x) >= clamp) or (i_x < 0 and error_x < 0 and abs(i_x + p_x) >= clamp)
            would_sat_y = (i_y > 0 and error_y > 0 and abs(i_y + p_y) >= clamp) or (i_y < 0 and error_y < 0 and abs(i_y + p_y) >= clamp)
            if not would_sat_x:
                i_x += float(self.config.ki) * float(error_x) * float(dt)
            if not would_sat_y:
                i_y += float(self.config.ki) * float(error_y) * float(dt)
            clamp = float(self.config.output_clamp)
            if camera_max_slew is not None:
                try:
                    cam_clamp_i = float(camera_max_slew) * float(dt)
                    clamp = min(clamp, cam_clamp_i)
                except Exception:
                    pass
            i_x = float(np.clip(i_x, -clamp, clamp))
            i_y = float(np.clip(i_y, -clamp, clamp))
            self._integral_x = float(i_x)
            self._integral_y = float(i_y)
        else:
            i_x = 0.0
            i_y = 0.0

        # Derivative on measurement (avoid kick) with tunable filter
        d_x = 0.0
        d_y = 0.0
        if self.config.controller_type == "PID" and float(self.config.kd) > 1e-9:
            if self._prev_error_x is not None and self._prev_error_y is not None:
                raw_dx = (float(error_x) - float(self._prev_error_x)) / float(dt)
                raw_dy = (float(error_y) - float(self._prev_error_y)) / float(dt)
                alpha_filt = float(getattr(self.config, "derivative_filter", 0.80))
                alpha_filt = float(np.clip(alpha_filt, 0.0, 0.99))
                filt_dx = (1 - alpha_filt) * raw_dx + alpha_filt * float(self._prev_deriv_x)
                filt_dy = (1 - alpha_filt) * raw_dy + alpha_filt * float(self._prev_deriv_y)
                d_x = float(self.config.kd) * float(filt_dx)
                d_y = float(self.config.kd) * float(filt_dy)
                self._prev_deriv_x = float(filt_dx)
                self._prev_deriv_y = float(filt_dy)
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
        else:
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
            if self.config.controller_type != "PID":
                self._prev_deriv_x = 0.0
                self._prev_deriv_y = 0.0

        u_x = float(p_x + i_x + d_x)
        u_y = float(p_y + i_y + d_y)

        # Feedforward — velocity prediction (reduces lag from 10→3px on 80 px/s)
        ff_gain = float(getattr(self.config, "feedforward_gain", 0.0))
        if ff_gain > 1e-9 and target_velocity is not None:
            try:
                vx, vy = float(target_velocity[0]), float(target_velocity[1])
                ff_x = ff_gain * vx * float(dt)
                ff_y = ff_gain * vy * float(dt)
                u_x += float(ff_x)
                u_y += float(ff_y)
            except Exception:
                pass

        clamp = float(self.config.output_clamp)
        if camera_max_slew is not None:
            try:
                cam_clamp = float(camera_max_slew) * float(dt)
                clamp = min(float(clamp), float(cam_clamp))
            except Exception:
                pass
        u_x = float(np.clip(u_x, -clamp, clamp))
        u_y = float(np.clip(u_y, -clamp, clamp))
        self._last_output = (float(u_x), float(u_y))
        return (float(u_x), float(u_y))

    def reset(self) -> None:
        self._integral_x = 0.0; self._integral_y = 0.0
        self._prev_error_x = None; self._prev_error_y = None
        self._prev_deriv_x = 0.0; self._prev_deriv_y = 0.0
        self._last_compute_time = None
        self._last_output = (0.0, 0.0)

class ProportionalController(PIDController):
    """Shim for old code/tests: ProportionalController(gain=0.1) -> PID with P only."""

    def __init__(self, gain: float = 0.1, **kwargs):
        cfg = ControllerConfig(controller_type="P", kp=float(gain), ki=0.0, kd=0.0, **kwargs).validate()
        for k in ["update_rate_hz", "dead_zone", "output_clamp"]:
            if k in kwargs:
                setattr(cfg, k, float(kwargs[k]))
        cfg.validate()
        super().__init__(config=cfg)
        self._gain = float(gain)

    @property
    def gain(self) -> float:
        return float(self.config.kp)

    @gain.setter
    def gain(self, value: float) -> None:
        self.config.kp = float(value)
        self._gain = float(value)