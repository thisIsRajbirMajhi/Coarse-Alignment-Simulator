# camera/config.py - Validated configurations for PTZ Camera and PID Controller.
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from common.config_base import BaseValidatedConfig
from camera.constants import (
    CAMERA_DEFAULTS,
    CAMERA_LIMITS,
    PID_DEFAULTS,
    PID_LIMITS,
)


@dataclass
class CameraConfig(BaseValidatedConfig):
    """
    Configuration for virtual PTZ camera optics and gimbal kinematics.
    Inherits from BaseValidatedConfig for centralized validation and dict conversion.
    """
    # Optics / Viewport
    fov_deg_h: float = 4.0               # Horizontal FOV (degrees, default 4.0 per PDF)
    fov_deg_v: float = 3.0               # Vertical FOV (degrees, default 3.0 per PDF)
    resolution_w: int = 640              # Sensor/viewport width (fixed 640 per PDF)
    resolution_h: int = 480              # Sensor/viewport height (fixed 480 per PDF)
    update_rate_hz: float = 30.0         # Minimum 30 Hz per PDF
    
    # PTZ Gimbal Kinematics
    max_pan_speed_deg_s: float = 5.0     # 5-10 °/s per PDF, default 5.0
    max_tilt_speed_deg_s: float = 5.0    # 5-10 °/s per PDF, default 5.0
    max_pan_accel_deg_s2: float = 25.0   # Maximum angular acceleration
    max_tilt_accel_deg_s2: float = 25.0
    
    # Travel Limits
    pan_min_deg: float = -90.0
    pan_max_deg: float = 90.0
    tilt_min_deg: float = -45.0
    tilt_max_deg: float = 45.0
    home_pan_deg: float = 0.0
    home_tilt_deg: float = 0.0
    
    # Dynamics & Sensors
    damping_ratio: float = 0.707         # Critical damping ratio
    inertia_kg_m2: float = 0.02          # Gimbal moment of inertia
    backlash_deg: float = 0.005          # Gear backlash (hysteresis on reversal)
    encoder_bits: int = 16               # Optical encoder quantization
    encoder_noise_deg: float = 0.001     # Encoder noise 1-sigma

    LIMITS: ClassVar[dict[str, tuple[float, float]]] = CAMERA_LIMITS
    DEFAULTS: ClassVar[dict[str, object]] = CAMERA_DEFAULTS

    @property
    def deg_per_px_h(self) -> float:
        return self.fov_deg_h / max(1, self.resolution_w)

    @property
    def deg_per_px_v(self) -> float:
        return self.fov_deg_v / max(1, self.resolution_h)

    @property
    def px_per_deg_h(self) -> float:
        return max(1, self.resolution_w) / max(1e-4, self.fov_deg_h)

    @property
    def px_per_deg_v(self) -> float:
        return max(1, self.resolution_h) / max(1e-4, self.fov_deg_v)

    def validate(self) -> "CameraConfig":
        super().validate()
        if self.pan_min_deg > self.pan_max_deg:
            self.pan_min_deg, self.pan_max_deg = self.pan_max_deg, self.pan_min_deg
        if self.tilt_min_deg > self.tilt_max_deg:
            self.tilt_min_deg, self.tilt_max_deg = self.tilt_max_deg, self.tilt_min_deg
        if not (self.pan_min_deg <= self.home_pan_deg <= self.pan_max_deg):
            self.home_pan_deg = max(self.pan_min_deg, min(self.home_pan_deg, self.pan_max_deg))
        if not (self.tilt_min_deg <= self.home_tilt_deg <= self.tilt_max_deg):
            self.home_tilt_deg = max(self.tilt_min_deg, min(self.home_tilt_deg, self.tilt_max_deg))
        return self


@dataclass
class PIDConfig(BaseValidatedConfig):
    """
    Configuration for Dual-Axis PID tracking controller.
    Includes filtered derivative (low-pass on D term), anti-windup, and deadband.
    """
    # Pan axis gains
    kp_pan: float = 1.5
    ki_pan: float = 0.1
    kd_pan: float = 0.25
    
    # Tilt axis gains
    kp_tilt: float = 1.5
    ki_tilt: float = 0.1
    kd_tilt: float = 0.25
    
    # Robustness parameters
    tau: float = 0.02                    # Derivative filter time constant (seconds)
    deadband_px: float = 1.0             # Pixel tracking error deadband (prevents hunting)
    max_integral_deg: float = 10.0       # Integrator anti-windup clamp limit (degrees)
    max_output_deg_s: float = 5.0        # Velocity command limit (deg/s)
    mode: str = "AUTO"                   # Operating mode: "AUTO", "MANUAL", "OFF"

    LIMITS: ClassVar[dict[str, tuple[float, float]]] = PID_LIMITS
    DEFAULTS: ClassVar[dict[str, object]] = PID_DEFAULTS

    def validate(self) -> "PIDConfig":
        super().validate()
        # Ensure mode is one of valid strings
        if self.mode not in ("AUTO", "MANUAL", "OFF"):
            self.mode = "AUTO"
        return self
