# camera/state.py - Runtime states and telemetry models for PTZ Camera and PID Controller.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PTZState:
    """Runtime state of the virtual PTZ camera gimbal."""
    # True mechanical angles (degrees)
    pan_deg: float = 0.0
    tilt_deg: float = 0.0
    
    # Angular rates (deg/s)
    pan_vel_deg_s: float = 0.0
    tilt_vel_deg_s: float = 0.0
    
    # Angular accelerations (deg/s^2)
    pan_accel_deg_s2: float = 0.0
    tilt_accel_deg_s2: float = 0.0
    
    # Measured angles with encoder quantization & noise
    measured_pan_deg: float = 0.0
    measured_tilt_deg: float = 0.0
    
    # Commanded / target angles
    target_pan_deg: float = 0.0
    target_tilt_deg: float = 0.0
    
    # FOV bounding box in world scene coordinates [x0, y0, x1, y1]
    fov_rect: tuple[float, float, float, float] = (0.0, 0.0, 640.0, 480.0)
    
    # Status flags
    in_limits: bool = True
    settled: bool = True
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "pan_deg": self.pan_deg,
            "tilt_deg": self.tilt_deg,
            "pan_vel_deg_s": self.pan_vel_deg_s,
            "tilt_vel_deg_s": self.tilt_vel_deg_s,
            "measured_pan_deg": self.measured_pan_deg,
            "measured_tilt_deg": self.measured_tilt_deg,
            "target_pan_deg": self.target_pan_deg,
            "target_tilt_deg": self.target_tilt_deg,
            "fov_rect": list(self.fov_rect),
            "in_limits": self.in_limits,
            "settled": self.settled,
        }


@dataclass
class PIDState:
    """Runtime state and telemetry of the dual-axis PID tracking controller."""
    # Tracking errors
    error_pan_deg: float = 0.0
    error_tilt_deg: float = 0.0
    error_pan_px: float = 0.0
    error_tilt_px: float = 0.0
    
    # Individual PID terms
    p_pan: float = 0.0
    i_pan: float = 0.0
    d_pan: float = 0.0
    
    p_tilt: float = 0.0
    i_tilt: float = 0.0
    d_tilt: float = 0.0
    
    # Output commanded velocity (deg/s)
    cmd_pan_vel: float = 0.0
    cmd_tilt_vel: float = 0.0
    
    # Saturation flags
    saturated_pan: bool = False
    saturated_tilt: bool = False
    
    # Mode and activity
    mode: str = "AUTO"
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_pan_deg": self.error_pan_deg,
            "error_tilt_deg": self.error_tilt_deg,
            "error_pan_px": self.error_pan_px,
            "error_tilt_px": self.error_tilt_px,
            "p_pan": self.p_pan,
            "i_pan": self.i_pan,
            "d_pan": self.d_pan,
            "p_tilt": self.p_tilt,
            "i_tilt": self.i_tilt,
            "d_tilt": self.d_tilt,
            "cmd_pan_vel": self.cmd_pan_vel,
            "cmd_tilt_vel": self.cmd_tilt_vel,
            "saturated_pan": self.saturated_pan,
            "saturated_tilt": self.saturated_tilt,
            "mode": self.mode,
            "active": self.active,
        }
