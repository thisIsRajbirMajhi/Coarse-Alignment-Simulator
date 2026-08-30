"""
Module: camera.constants
Purpose: Single source for Camera limits & defaults (FOV, mechanics, display, optics).
Public API: CAMERA_LIMITS, CAMERA_DEFAULTS, DISPLAY_LIMITS, DISPLAY_DEFAULTS
Notes: Consumed by CameraConfig, PTZCamera, and CameraPanel for consistent clamping.
"""

from environment.constants import MAX_RES

# ============================================================
# SECTION: Camera / Optics Limits
# ============================================================

CAMERA_LIMITS: dict[str, tuple[float, float]] = {
    # Field of View — actual sensor resolution (px)
    "fov_width": (20, MAX_RES),
    "fov_height": (20, MAX_RES),
    # Pan/Tilt range — mechanical limits (px in scene coords). 0..MAX_RES, but also clamped to scene.
    "pan_min": (0, MAX_RES),
    "pan_max": (0, MAX_RES),
    "tilt_min": (0, MAX_RES),
    "tilt_max": (0, MAX_RES),
    # Home / centre — default pointing on start/reset (px)
    "home_pan": (0, MAX_RES),
    "home_tilt": (0, MAX_RES),
    # Max slew rate — actuator speed limit (px/s). 0 = unlimited handled as 1e6
    "max_slew_rate": (10, 5000),
    # Positional resolution — smallest step (px). 0.01..5.0, 0 = continuous
    "resolution": (0.01, 5.0),
    # Response latency — queue delay (ms). 0..500 ms
    "latency_ms": (0, 500),
    # Optics — pixel to angle conversion (mrad per px). 0.001..2.0
    "pixel_scale_mrad": (0.001, 2.0),
}

CAMERA_DEFAULTS: dict = {
    "fov_width": 250,
    "fov_height": 250,
    "pan_min": None,          # None → auto = fov/2
    "pan_max": None,          # None → auto = W - fov/2
    "tilt_min": None,
    "tilt_max": None,
    "home_pan": None,         # None → auto = W/2
    "home_tilt": None,        # None → auto = H/2
    "max_slew_rate": 800.0,   # px/s — ~3× FOV per second, realistic gimbal
    "resolution": 0.1,        # px — 0.1 px finest step (quantized)
    "latency_ms": 30,         # ms — ~1 frame delay, simulates actuator + comms
    "pixel_scale_mrad": 0.035, # mrad/px — 35 µrad per px (FSOC relevant, ~7 arcsec)
    "scene_width": 1000,      # helper for auto home/range when scene not yet known
    "scene_height": 1000,
}

# ============================================================
# SECTION: Display Limits
# ============================================================

DISPLAY_LIMITS: dict[str, tuple[int, int]] = {
    "viewport_width": (100, MAX_RES),
    "viewport_height": (100, MAX_RES),
    "god_width": (100, MAX_RES),
    "god_height": (100, MAX_RES),
}

DISPLAY_DEFAULTS: dict = {
    "viewport_width": 400,
    "viewport_height": 300,
    "god_width": 400,
    "god_height": 300,
}
