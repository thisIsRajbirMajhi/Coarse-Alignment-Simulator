# camera/pid_controller.py - Dual-axis PID tracking controller with filtered derivative and anti-windup.
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from src.camera.config import PIDConfig
from src.camera.state import PIDState

log = logging.getLogger(__name__)


class PIDController:
    """
    Dual-axis (Pan/Tilt) PID Controller for PAT Coarse Alignment.
    
    Features:
    - Independent tuning for Pan and Tilt axes
    - Continuous-to-discrete filtered derivative (low-pass on D-term with configurable tau)
      to eliminate sensor/centroiding jitter
    - Anti-windup with conditional integration (clamping) and hard integral limits
    - Deadband zone around boresight to prevent actuator hunting
    - Derivative kick prevention on setpoint/error reset
    - Full telemetry reporting
    """

    def __init__(self, config: PIDConfig | None = None):
        self.config = (config or PIDConfig()).validate()

        # Integrator accumulators (degrees)
        self.integral_pan: float = 0.0
        self.integral_tilt: float = 0.0

        # Filtered derivative states
        self.deriv_pan: float = 0.0
        self.deriv_tilt: float = 0.0

        # Previous errors for derivative calculation
        self.prev_error_pan: float = 0.0
        self.prev_error_tilt: float = 0.0
        self._first_step_pan: bool = True
        self._first_step_tilt: bool = True

        # Last computed state
        self._last_state: PIDState = PIDState()

    def apply_config(self, config: PIDConfig) -> None:
        """Hot-reload PID configuration."""
        self.config = config.validate()

    def reset(self) -> None:
        """Reset internal controller states (clear integrators and derivative filters)."""
        self.integral_pan = 0.0
        self.integral_tilt = 0.0
        self.deriv_pan = 0.0
        self.deriv_tilt = 0.0
        self.prev_error_pan = 0.0
        self.prev_error_tilt = 0.0
        self._first_step_pan = True
        self._first_step_tilt = True
        self._last_state = PIDState(mode=self.config.mode, active=False)

    def set_mode(self, mode: str) -> None:
        """Set operating mode: AUTO, MANUAL, or OFF."""
        if mode in ("AUTO", "MANUAL", "OFF"):
            old_mode = self.config.mode
            self.config.mode = mode
            if mode in ("OFF", "MANUAL") or (old_mode != "AUTO" and mode == "AUTO"):
                self.reset()

    def compute_from_pixels(
        self,
        error_x_px: float,
        error_y_px: float,
        deg_per_px_h: float,
        deg_per_px_v: float,
        dt: float,
        target_vel_x_px_s: float = 0.0,
        target_vel_y_px_s: float = 0.0,
    ) -> tuple[float, float]:
        """
        Compute velocity commands (deg/s) from pixel tracking errors (target - boresight).
        
        Args:
            error_x_px: Target x minus FOV center x (pixels).
            error_y_px: Target y minus FOV center y (pixels).
            deg_per_px_h: Optical scaling factor for horizontal axis.
            deg_per_px_v: Optical scaling factor for vertical axis.
            dt: Time step (seconds).
            target_vel_x_px_s: Optional target velocity feedforward in x (px/s).
            target_vel_y_px_s: Optional target velocity feedforward in y (px/s).
            
        Returns:
            (cmd_pan_vel_deg_s, cmd_tilt_vel_deg_s)
        """
        if self.config.mode != "AUTO":
            self._last_state = PIDState(mode=self.config.mode, active=False)
            return (0.0, 0.0)

        if not math.isfinite(error_x_px) or not math.isfinite(error_y_px):
            return (0.0, 0.0)

        dt_eff = float(np.clip(dt, 1e-4, 0.1))

        # 1. Deadband check (pixel space)
        pixel_dist = math.hypot(error_x_px, error_y_px)
        deadband = float(self.config.deadband_px)

        if pixel_dist <= deadband:
            eff_err_x = 0.0
            eff_err_y = 0.0
        else:
            # Soft deadband: subtract deadband magnitude in error direction
            factor = (pixel_dist - deadband) / pixel_dist
            eff_err_x = error_x_px * factor
            eff_err_y = error_y_px * factor

        # 2. Convert to angular error (degrees)
        # Pan: target right (+x) requires positive pan velocity (+pan)
        # Tilt: target down (+y in screen) requires negative tilt velocity (-tilt)
        error_pan_deg = eff_err_x * deg_per_px_h
        error_tilt_deg = -eff_err_y * deg_per_px_v

        # Feedforward from target velocity
        ff_pan = float(target_vel_x_px_s) * deg_per_px_h
        ff_tilt = -float(target_vel_y_px_s) * deg_per_px_v

        # 3. Compute PID for each axis independently
        cmd_pan, p_pan, i_pan, d_pan, sat_pan = self._update_axis(
            error=error_pan_deg,
            kp=self.config.kp_pan,
            ki=self.config.ki_pan,
            kd=self.config.kd_pan,
            integral=self.integral_pan,
            prev_deriv=self.deriv_pan,
            prev_error=self.prev_error_pan,
            dt=dt_eff,
            is_first_step=self._first_step_pan,
            feedforward=ff_pan,
        )

        cmd_tilt, p_tilt, i_tilt, d_tilt, sat_tilt = self._update_axis(
            error=error_tilt_deg,
            kp=self.config.kp_tilt,
            ki=self.config.ki_tilt,
            kd=self.config.kd_tilt,
            integral=self.integral_tilt,
            prev_deriv=self.deriv_tilt,
            prev_error=self.prev_error_tilt,
            dt=dt_eff,
            is_first_step=self._first_step_tilt,
            feedforward=ff_tilt,
        )

        # Store internal states
        self.integral_pan = i_pan
        self.integral_tilt = i_tilt
        self.deriv_pan = d_pan
        self.deriv_tilt = d_tilt
        self.prev_error_pan = error_pan_deg
        self.prev_error_tilt = error_tilt_deg
        self._first_step_pan = False
        self._first_step_tilt = False

        self._last_state = PIDState(
            error_pan_deg=error_pan_deg,
            error_tilt_deg=error_tilt_deg,
            error_pan_px=error_x_px,
            error_tilt_px=error_y_px,
            p_pan=p_pan,
            i_pan=i_pan,
            d_pan=d_pan,
            p_tilt=p_tilt,
            i_tilt=i_tilt,
            d_tilt=d_tilt,
            cmd_pan_vel=cmd_pan,
            cmd_tilt_vel=cmd_tilt,
            saturated_pan=sat_pan,
            saturated_tilt=sat_tilt,
            mode=self.config.mode,
            active=True,
        )

        return (cmd_pan, cmd_tilt)

    def _update_axis(
        self,
        error: float,
        kp: float,
        ki: float,
        kd: float,
        integral: float,
        prev_deriv: float,
        prev_error: float,
        dt: float,
        is_first_step: bool = False,
        feedforward: float = 0.0,
    ) -> tuple[float, float, float, float, bool]:
        """
        Single-axis PID calculation with filtered derivative and anti-windup clamping.
        
        Returns: (cmd_vel, P, I, D, is_saturated)
        """
        # Proportional term
        p_term = kp * error

        # Derivative term with first-order low-pass filter (tau)
        # Continuous: D(s) = (Kd * s / (1 + tau * s)) * E(s)
        # Discrete: D[k] = (tau / (tau + dt)) * D[k-1] + (Kd / (tau + dt)) * (e[k] - e[k-1])
        tau = max(1e-4, float(self.config.tau))
        if is_first_step:
            delta_e = 0.0
            d_term = 0.0
        else:
            delta_e = error - prev_error
            # Slew limit on delta_e to prevent derivative kick on target jumps / discontinuities
            max_slew = 3.0
            delta_e = float(np.clip(delta_e, -max_slew, max_slew))
            d_term = (tau / (tau + dt)) * prev_deriv + (kd / (tau + dt)) * delta_e

        # Tentative integral accumulation
        new_integral = integral + ki * error * dt
        max_int = float(self.config.max_integral_deg)
        new_integral = float(np.clip(new_integral, -max_int, max_int))

        # Output with tentative integral and feedforward
        raw_output = p_term + new_integral + d_term + float(feedforward)
        max_out = float(self.config.max_output_deg_s)
        is_saturated = abs(raw_output) > max_out

        # Conditional integration (anti-windup):
        # If saturated and error pushes further into saturation, freeze integral
        if is_saturated and (raw_output * error > 0):
            new_integral = integral
            # Recalculate output with frozen integral for consistency
            raw_output = p_term + new_integral + d_term + float(feedforward)

        cmd_vel = float(np.clip(raw_output, -max_out, max_out))

        return (cmd_vel, p_term, new_integral, d_term, is_saturated)

    def get_state(self) -> PIDState:
        return self._last_state

    def get_telemetry(self) -> dict[str, Any]:
        return self._last_state.to_dict()
