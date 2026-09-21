# camera/constants.py - Limits, defaults, and presets for PTZ Camera and PID Controller.
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# PTZ Camera Limits & Defaults
# ---------------------------------------------------------------------------
# Per PDF Specifications:
# - Camera Resolution: 640 x 480 pixels
# - Camera FOV: Default 4° x 3° (user-defined)
# - Max Pan/Tilt Speed: 5-10 °/s (user-defined, default 5 °/s)
# - Camera update rate: >= 30 Hz
# - Screen size: 2000 x 2000 min

CAMERA_LIMITS: dict[str, tuple[float, float]] = {
    # Optics / Viewport
    "fov_deg_h": (0.5, 30.0),          # Horizontal Field of View (deg)
    "fov_deg_v": (0.5, 30.0),          # Vertical Field of View (deg)
    "resolution_w": (320, 1920),       # Fixed to 640 per requirement, clamped if set
    "resolution_h": (240, 1080),       # Fixed to 480 per requirement
    "update_rate_hz": (10.0, 120.0),   # Camera update frequency (Hz)
    
    # PTZ Gimbal Kinematics & Limits
    "max_pan_speed_deg_s": (0.5, 30.0),    # Max pan rate (deg/s, PDF default 5.0)
    "max_tilt_speed_deg_s": (0.5, 30.0),   # Max tilt rate (deg/s, PDF default 5.0)
    "max_pan_accel_deg_s2": (1.0, 100.0),  # Max pan angular acceleration (deg/s^2)
    "max_tilt_accel_deg_s2": (1.0, 100.0), # Max tilt angular acceleration (deg/s^2)
    
    # Gimbal Travel Limits
    "pan_min_deg": (-180.0, 0.0),
    "pan_max_deg": (0.0, 180.0),
    "tilt_min_deg": (-90.0, 0.0),
    "tilt_max_deg": (0.0, 90.0),
    "home_pan_deg": (-180.0, 180.0),
    "home_tilt_deg": (-90.0, 90.0),
    
    # Physical / Mechanical Characteristics
    "damping_ratio": (0.1, 2.0),           # Damping ratio zeta (1.0 = critical; 0.707 = Butterworth/underdamped)
    "inertia_kg_m2": (0.001, 1.0),         # Rotational inertia (kg*m^2)
    "backlash_deg": (0.0, 0.5),            # Gear backlash / dead-zone (deg)
    "encoder_bits": (10, 24),              # Encoder resolution in bits
    "encoder_noise_deg": (0.0, 0.05),      # 1-sigma encoder noise (deg)

    # Expected Payload (local-terminal beacon expectations, §3.1)
    "expected_wavelength_nm": (800.0, 1700.0),  # Expected carrier wavelength (nm)
    "expected_wl_tolerance_nm": (1.0, 200.0),   # Wavelength match tolerance (nm)

    # Custom Starting Positions (all agents)
    "start_pan_deg": (-180.0, 180.0),       # Custom gimbal start pose (deg)
    "start_tilt_deg": (-90.0, 90.0),
    "scan_start_index": (0, 19),             # Local-terminal scan grid start cell
}

CAMERA_DEFAULTS: dict[str, Any] = {
    "fov_deg_h": 4.0,                      # 4° horizontal FOV
    "fov_deg_v": 3.0,                      # 3° vertical FOV (4:3 aspect matching 640x480)
    "resolution_w": 640,
    "resolution_h": 480,
    "update_rate_hz": 30.0,                # >= 30 Hz per PDF
    
    "max_pan_speed_deg_s": 5.0,            # 5 °/s default per PDF
    "max_tilt_speed_deg_s": 5.0,           # 5 °/s default per PDF
    "max_pan_accel_deg_s2": 25.0,          # 25 °/s^2 acceleration limit
    "max_tilt_accel_deg_s2": 25.0,
    
    "pan_min_deg": -90.0,
    "pan_max_deg": 90.0,
    "tilt_min_deg": -45.0,
    "tilt_max_deg": 45.0,
    "home_pan_deg": 0.0,
    "home_tilt_deg": 0.0,
    
    "damping_ratio": 0.707,                # Butterworth design point (underdamped; critical = 1.0)
    "inertia_kg_m2": 0.02,
    "backlash_deg": 0.005,                 # 18 arcsec backlash
    "encoder_bits": 16,                    # 16-bit encoder (~0.0055° resolution)
    "encoder_noise_deg": 0.001,            # 3.6 arcsec RMS noise

    # Expected Payload (local-terminal beacon expectations)
    "expected_wavelength_nm": 1550.0,
    "expected_wl_tolerance_nm": 50.0,

    # Custom Starting Positions (camera + local-terminal scan)
    "start_pan_deg": 0.0,
    "start_tilt_deg": 0.0,
    "scan_start_index": 0,
}

CAMERA_PRESETS: dict[str, dict[str, Any]] = {
    "Standard FSOC (Default)": {
        "fov_deg_h": 4.0,
        "fov_deg_v": 3.0,
        "max_pan_speed_deg_s": 5.0,
        "max_tilt_speed_deg_s": 5.0,
        "max_pan_accel_deg_s2": 25.0,
        "max_tilt_accel_deg_s2": 25.0,
        "backlash_deg": 0.005,
        "encoder_noise_deg": 0.001,
        "damping_ratio": 0.707,
    },
    "High Dynamic (Agile UAV/LEO)": {
        "fov_deg_h": 6.0,
        "fov_deg_v": 4.5,
        "max_pan_speed_deg_s": 10.0,
        "max_tilt_speed_deg_s": 10.0,
        "max_pan_accel_deg_s2": 60.0,
        "max_tilt_accel_deg_s2": 60.0,
        "backlash_deg": 0.002,
        "encoder_noise_deg": 0.0005,
        "damping_ratio": 0.85,
    },
    "Precision Ground Optical (Narrow)": {
        "fov_deg_h": 2.0,
        "fov_deg_v": 1.5,
        "max_pan_speed_deg_s": 3.0,
        "max_tilt_speed_deg_s": 3.0,
        "max_pan_accel_deg_s2": 15.0,
        "max_tilt_accel_deg_s2": 15.0,
        "backlash_deg": 0.001,
        "encoder_noise_deg": 0.0002,
        "damping_ratio": 0.9,
    },
}

# ---------------------------------------------------------------------------
# PID Controller Limits & Defaults
# ---------------------------------------------------------------------------
# Dual-axis closed-loop tracking controller for camera gimbal
PID_LIMITS: dict[str, tuple[float, float]] = {
    "kp_pan": (0.0, 20.0),
    "ki_pan": (0.0, 10.0),
    "kd_pan": (0.0, 5.0),
    "kp_tilt": (0.0, 20.0),
    "ki_tilt": (0.0, 10.0),
    "kd_tilt": (0.0, 5.0),
    "tau": (0.001, 0.5),               # Low-pass filter time constant for D-term (s)
    "deadband_px": (0.0, 15.0),         # Pixel tracking dead-zone (px)
    "max_integral_deg": (0.1, 45.0),    # Anti-windup integrator clamp (deg)
    "max_output_deg_s": (0.5, 30.0),    # Controller output rate limit (deg/s)
}

PID_DEFAULTS: dict[str, Any] = {
    "kp_pan": 1.5,                      # Proportional gain (deg/s per deg error)
    "ki_pan": 0.1,                      # Integral gain
    "kd_pan": 0.25,                     # Derivative gain
    "kp_tilt": 1.5,
    "ki_tilt": 0.1,
    "kd_tilt": 0.25,
    "tau": 0.02,                        # 20ms derivative filter time constant (50 rad/s cutoff)
    "deadband_px": 1.0,                 # 1 pixel deadband to prevent hunting on noise
    "max_integral_deg": 10.0,           # ±10° anti-windup clamp
    "max_output_deg_s": 5.0,            # Matches camera max speed default (5 °/s)
    "mode": "AUTO",                     # "AUTO", "MANUAL", "OFF"
}

PID_PRESETS: dict[str, dict[str, Any]] = {
    "Balanced (Critically Damped)": {
        "kp_pan": 1.5,
        "ki_pan": 0.1,
        "kd_pan": 0.25,
        "kp_tilt": 1.5,
        "ki_tilt": 0.1,
        "kd_tilt": 0.25,
        "tau": 0.02,
        "deadband_px": 1.0,
    },
    "Aggressive (Fast Acquisition)": {
        "kp_pan": 3.0,
        "ki_pan": 0.3,
        "kd_pan": 0.45,
        "kp_tilt": 3.0,
        "ki_tilt": 0.3,
        "kd_tilt": 0.45,
        "tau": 0.015,
        "deadband_px": 0.5,
    },
    "Smooth / Low-Jitter (Conservative)": {
        "kp_pan": 0.8,
        "ki_pan": 0.03,
        "kd_pan": 0.15,
        "kp_tilt": 0.8,
        "ki_tilt": 0.03,
        "kd_tilt": 0.15,
        "tau": 0.04,
        "deadband_px": 2.0,
    },
}
