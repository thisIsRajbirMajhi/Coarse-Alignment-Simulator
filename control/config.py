"""
Module: control.config
Purpose: Typed, validated configuration for PID controller (robust, modular).
Public API: ControllerConfig
Notes: Single source for GUI and PIDController. HOT-reloaded, serializable.
       Output clamp should respect camera max_slew_rate — enforced in controller, not here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from control.constants import CONTROL_DEFAULTS, CONTROL_LIMITS, CONTROLLER_TYPES

# ============================================================
# SECTION: ControllerConfig — all 7 controller params
# ============================================================

@dataclass
class ControllerConfig:
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
        lo, hi = CONTROL_LIMITS["kp"]
        self.kp = float(np.clip(float(self.kp), lo, hi))
        lo, hi = CONTROL_LIMITS["ki"]
        self.ki = float(np.clip(float(self.ki), lo, hi))
        lo, hi = CONTROL_LIMITS["kd"]
        self.kd = float(np.clip(float(self.kd), lo, hi))
        lo, hi = CONTROL_LIMITS["update_rate_hz"]
        self.update_rate_hz = float(np.clip(float(self.update_rate_hz), lo, hi))
        lo, hi = CONTROL_LIMITS["dead_zone"]
        self.dead_zone = float(np.clip(float(self.dead_zone), lo, hi))
        lo, hi = CONTROL_LIMITS["output_clamp"]
        self.output_clamp = float(np.clip(float(self.output_clamp), lo, hi))
        # Enforce type → zero irrelevant gains for cleaner behavior
        if self.controller_type == "P":
            self.ki = 0.0; self.kd = 0.0
        elif self.controller_type == "PI":
            self.kd = 0.0
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ControllerConfig":
        known = {k: v for k, v in data.items() if k in CONTROL_DEFAULTS}
        return cls(**{**CONTROL_DEFAULTS, **known}).validate()

    # Back-compat: old ProportionalController had .gain
    @property
    def gain(self) -> float:
        return float(self.kp)

    @gain.setter
    def gain(self, value: float) -> None:
        self.kp = float(np.clip(float(value), *CONTROL_LIMITS["kp"]))

    def update_interval(self) -> float:
        """Seconds between controller computations (1/Hz)."""
        return 1.0 / max(1e-6, float(self.update_rate_hz))
