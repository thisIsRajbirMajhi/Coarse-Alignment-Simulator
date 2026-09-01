# control/controller.py - PID controller — robust, modular, well-commented with maths/physics

from __future__ import annotations

import math
import time

import numpy as np

from control.config import ControllerConfig
from control.constants import CONTROL_DEFAULTS

class PIDController:
    """PID controller — per-axis (pan, tilt) with shared gains."""

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
            for k in ["controller_type", "update_rate_hz", "dead_zone", "output_clamp"]:
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

    def compute_correction(self, error_x: float, error_y: float, dt: float | None = None, camera_max_slew: float | None = None) -> tuple[float, float]:
        err_mag = math.hypot(float(error_x), float(error_y))
        if err_mag < float(self.config.dead_zone):
            self._integral_x *= 0.9
            self._integral_y *= 0.9
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
            self._last_output = (0.0, 0.0)
            return (0.0, 0.0)
        now = time.time()
        interval = self.config.update_interval()
        if self._last_compute_time is not None:
            elapsed = now - self._last_compute_time
            if elapsed + 1e-6 < interval:
                return self._last_output
        self._last_compute_time = now
        if dt is None:
            dt = float(interval)
        dt = float(np.clip(dt, 1e-4, 0.2))
        p_x = float(self.config.kp) * float(error_x)
        p_y = float(self.config.kp) * float(error_y)
        i_x = self._integral_x
        i_y = self._integral_y
        if self.config.controller_type in ("PI", "PID") and float(self.config.ki) > 1e-9:
            i_x += float(self.config.ki) * float(error_x) * float(dt)
            i_y += float(self.config.ki) * float(error_y) * float(dt)
            clamp = float(self.config.output_clamp)
            i_x = float(np.clip(i_x, -clamp, clamp))
            i_y = float(np.clip(i_y, -clamp, clamp))
            self._integral_x = float(i_x)
            self._integral_y = float(i_y)
        else:
            i_x = 0.0; i_y = 0.0
        d_x = 0.0; d_y = 0.0
        if self.config.controller_type == "PID" and float(self.config.kd) > 1e-9:
            if self._prev_error_x is not None and self._prev_error_y is not None:
                raw_dx = (float(error_x) - float(self._prev_error_x)) / float(dt)
                raw_dy = (float(error_y) - float(self._prev_error_y)) / float(dt)
                filt_dx = 0.2 * raw_dx + 0.8 * float(self._prev_deriv_x)
                filt_dy = 0.2 * raw_dy + 0.8 * float(self._prev_deriv_y)
                d_x = float(self.config.kd) * float(filt_dx)
                d_y = float(self.config.kd) * float(filt_dy)
                self._prev_deriv_x = float(filt_dx)
                self._prev_deriv_y = float(filt_dy)
            else:
                d_x = 0.0; d_y = 0.0
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
        else:
            self._prev_error_x = float(error_x)
            self._prev_error_y = float(error_y)
            if self.config.controller_type != "PID":
                self._prev_deriv_x = 0.0; self._prev_deriv_y = 0.0
        u_x = float(p_x + i_x + d_x)
        u_y = float(p_y + i_y + d_y)
        clamp = float(self.config.output_clamp)
        if camera_max_slew is not None:
            try:
                cam_clamp = float(camera_max_slew) * float(dt)
                clamp = min(float(clamp), float(cam_clamp))
            except: pass
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