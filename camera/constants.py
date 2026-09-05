# camera/constants.py - Single source for Camera limits & defaults (FOV, mechanics, display, optics)

from environment.constants import MAX_RES

CAMERA_LIMITS: dict[str, tuple[float, float]] = {
    # Sensor Resolution — 640x480 suggested, user-defined (generic engine 100..5000 for headless)
    "fov_width": (100, MAX_RES),
    "fov_height": (100, MAX_RES),
    # FOV in degrees — 4 x 3 default, user defined
    "fov_deg_x": (1.0, 10.0),
    "fov_deg_y": (1.0, 10.0),
    # Pan/Tilt range — mechanical limits (px in scene coords). 0..MAX_RES, but also clamped to scene.
    "pan_min": (0, MAX_RES),
    "pan_max": (0, MAX_RES),
    "tilt_min": (0, MAX_RES),
    "tilt_max": (0, MAX_RES),
    # Home / centre — default pointing on start/reset (px)
    "home_pan": (0, MAX_RES),
    "home_tilt": (0, MAX_RES),
    "max_pan_speed_deg": (5.0, 10.0),
    "max_tilt_speed_deg": (5.0, 10.0),
    # Legacy px/s — now DERIVED from deg/s, not user-set (kept for back-compat only)
    "max_slew_rate": (10, 5000),
    "resolution": (0.01, 5.0),
    "latency_ms": (0, 500),
    # Realism extensions — acceleration, backlash, encoder/latency jitter
    "max_accel_deg": (20.0, 300.0),
    "backlash_px": (0.0, 2.0),
    "encoder_sigma_px": (0.0, 0.5),
    "latency_jitter_ms": (0.0, 5.0),
    "pixel_scale_mrad": (0.001, 2.0),
    "update_rate_hz": (30, 120),
}

CAMERA_DEFAULTS: dict = {
    "fov_width": 640,
    "fov_height": 480,
    "fov_deg_x": 4.0,
    "fov_deg_y": 3.0,
    "pan_min": None,
    "pan_max": None,
    "tilt_min": None,
    "tilt_max": None,
    "home_pan": None,
    "home_tilt": None,
    "max_pan_speed_deg": 5.0,  # per PDF Sr.13 default 5°/s
    "max_tilt_speed_deg": 5.0,  # per PDF Sr.14 default 5°/s
    "max_slew_rate": 800.0,  # legacy derived — overwritten by deg/s derive (5°/s ≈ 800 px/s at 0.109 mrad/px)
    "resolution": 0.1,
    "latency_ms": 12,
    "max_accel_deg": 120.0,  # ~2040 px/s² at 0.109 scale
    "backlash_px": 0.25,
    "encoder_sigma_px": 0.04,
    "latency_jitter_ms": 1.2,
    "pixel_scale_mrad": 0.109,
    "scene_width": 2000,  # per PDF Sr.1 min 2000
    "scene_height": 2000,
    "update_rate_hz": 30,  # per PDF Sr.5 30 Hz min
}

DISPLAY_LIMITS: dict[str, tuple[int, int]] = {
    "viewport_width": (2000, MAX_RES),
    "viewport_height": (2000, MAX_RES),
    "god_width": (2000, MAX_RES),
    "god_height": (2000, MAX_RES),
}

DISPLAY_DEFAULTS: dict = {
    "viewport_width": 2000,
    "viewport_height": 2000,
    "god_width": 2000,
    "god_height": 2000,
}