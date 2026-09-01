# control/config.py - Typed, validated configuration for PID controller (robust, modular)

from __future__ import annotations

from dataclasses import dataclass

from common.config_base import BaseValidatedConfig, clip_field
from control.constants import CONTROL_DEFAULTS, CONTROL_LIMITS, CONTROLLER_TYPES

@dataclass
class ControllerConfig(BaseValidatedConfig):
    """
    Controller configuration — P/PI/PID + dead zone + clamp + rate.

    13) controller_type — P | PI | PID
    14) kp — proportional gain
    15) ki — integral gain
    16) kd — derivative gain
    17) update_rate_hz — Hz, compute interval = 1/rate
    18) dead_zone — px, ignore errors below this (anti-jitter)
    19) output_clamp — px/tick, max correction (enforce ≤ camera slew*dt)
    """

    LIMITS = CONTROL_LIMITS
    DEFAULTS = CONTROL_DEFAULTS

    controller_type: str = CONTROL_DEFAULTS["controller_type"]
    kp: float = CONTROL_DEFAULTS["kp"]
    ki: float = CONTROL_DEFAULTS["ki"]
    kd: float = CONTROL_DEFAULTS["kd"]
    update_rate_hz: float = CONTROL_DEFAULTS["update_rate_hz"]
    dead_zone: float = CONTROL_DEFAULTS["dead_zone"]
    output_clamp: float = CONTROL_DEFAULTS["output_clamp"]

    def validate(self) -> "ControllerConfig":
        if self.controller_type not in CONTROLLER_TYPES:
            self.controller_type = CONTROL_DEFAULTS["controller_type"]
        self.kp = float(clip_field(self.kp, *self.LIMITS["kp"]))
        self.ki = float(clip_field(self.ki, *self.LIMITS["ki"]))
        self.kd = float(clip_field(self.kd, *self.LIMITS["kd"]))
        self.update_rate_hz = float(clip_field(self.update_rate_hz, *self.LIMITS["update_rate_hz"]))
        self.dead_zone = float(clip_field(self.dead_zone, *self.LIMITS["dead_zone"]))
        self.output_clamp = float(clip_field(self.output_clamp, *self.LIMITS["output_clamp"]))
        # Enforce type → zero irrelevant gains for cleaner behavior
        if self.controller_type == "P":
            self.ki = 0.0; self.kd = 0.0
        elif self.controller_type == "PI":
            self.kd = 0.0
        return self

    # Back-compat: old ProportionalController had .gain
    @property
    def gain(self) -> float:
        return float(self.kp)

    @gain.setter
    def gain(self, value: float) -> None:
        self.kp = float(clip_field(float(value), *CONTROL_LIMITS["kp"]))

    def update_interval(self) -> float:
        """Seconds between controller computations (1/Hz)."""
        return 1.0 / max(1e-6, float(self.update_rate_hz))