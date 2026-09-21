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
    damping_ratio: float = 0.707         # Damping ratio zeta (1.0 = critical; 0.707 = Butterworth)
    inertia_kg_m2: float = 0.02          # Gimbal moment of inertia
    backlash_deg: float = 0.005          # Gear backlash (hysteresis on reversal)
    encoder_bits: int = 16               # Optical encoder quantization
    encoder_noise_deg: float = 0.001     # Encoder noise 1-sigma
    use_measured_feedback: bool = False  # Disturb-pose input from measured
                                         # (quantized+noisy) angles instead of
                                         # true angles (Plan Stage 2)

    # Expected Payload (local-terminal beacon expectations, Plan §3.1).
    # Configures which remote-terminal beacon payload the local terminal
    # accepts: TID allow-list seed, carrier wavelength + tolerance, nav
    # requirement, and self-ID for loopback-fault detection.
    expected_tid: str = "RT-001"
    expected_wavelength_nm: float = 1550.0
    expected_wl_tolerance_nm: float = 50.0
    expected_require_nav: bool = False
    local_id: str = ""                   # Self-ID; empty = loopback check disabled

    # Custom Starting Positions (all agents).
    # Camera gimbal start pose + local-terminal scan-grid start cell.
    # (Remote-terminal formation start offsets live on RemoteFormationConfig.)
    start_pan_deg: float = 0.0
    start_tilt_deg: float = 0.0
    use_custom_start: bool = False       # Init/reset to start pose instead of home
    scan_start_index: int = 0            # Local-terminal scan grid start cell (0..19)

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
        # Clamp custom start pose into travel limits.
        p_min, p_max = self.pan_min_deg, self.pan_max_deg
        t_min, t_max = self.tilt_min_deg, self.tilt_max_deg
        self.start_pan_deg = max(p_min, min(float(self.start_pan_deg), p_max))
        self.start_tilt_deg = max(t_min, min(float(self.start_tilt_deg), t_max))
        self.scan_start_index = int(max(0, min(int(self.scan_start_index), 19)))
        # Sanitize expected-payload strings.
        self.expected_tid = str(self.expected_tid or "").strip() or "RT-001"
        self.local_id = str(self.local_id or "").strip()
        self.use_custom_start = bool(self.use_custom_start)
        self.expected_require_nav = bool(self.expected_require_nav)
        return self

    def get_initial_pose(self) -> tuple[float, float]:
        """Gimbal pose used on init/reset: custom start or home."""
        if bool(self.use_custom_start):
            return (float(self.start_pan_deg), float(self.start_tilt_deg))
        return (float(self.home_pan_deg), float(self.home_tilt_deg))


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
