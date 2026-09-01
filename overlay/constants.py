# overlay/constants.py - Single source for overlay limits & defaults (crosshair, lock, error)

OVERLAY_LIMITS: dict[str, tuple[float, float]] = {
    # Crosshair
    "crosshair_size": (4, 40),        # arm length px
    "crosshair_gap": (0, 30),         # gap from centre px
    "crosshair_thickness": (1, 4),    # line thickness px
    "centre_dot_radius": (0, 4),      # 0=off, 1..4 px
    # Lock circle
    "lock_circle_radius": (0, 40),    # 0=use hitbox radius, else fixed px offset 4..40
    "lock_circle_thickness": (1, 4),
    # Pulse
    "pulse_duration_ms": (100, 800),  # flash duration
    # Error text size handled via font scale 0.2..0.6
}

OVERLAY_DEFAULTS: dict = {
    # Crosshair — style controls what elements are drawn
    "crosshair_style": "cross+bracket",  # cross | bracket | circle | cross+bracket | cross+circle | all
    "crosshair_size": 16,                # arm length
    "crosshair_gap": 10,
    "crosshair_thickness": 1,
    "centre_dot": True,
    "centre_dot_radius": 1,
    "crosshair_color": (230, 230, 230),  # BGR for FOV reticle (neutral)
    # Lock status — per-state colors (BGR)
    "lock_circle_radius": 0,             # 0 = hitbox radius, else fixed
    "lock_circle_thickness": 1,
    "pulse_enabled": True,
    "pulse_duration_ms": 300,
    # Error visualization
    "show_error_line": True,
    "show_error_text": True,
    "error_units": "px+mrad",            # px | mrad | urad | px+mrad
    "error_text_scale": 0.28,
}

# Default lock colors — single source via common.colors (hex + BGR)
# Re-export from common/colors.py to keep 1 source; fallback defined here if common not available
try:
    from common.colors import LOCK_STATUS_COLORS_BGR as LOCK_COLOR_DEFAULTS  # type: ignore
except Exception:
    LOCK_COLOR_DEFAULTS: dict[str, tuple[int,int,int]] = {
        "searching": (170, 170, 170),  # gray
        "acquired": (90, 220, 220),    # cyan
        "tracking": (90, 220, 90),     # green
        "lost": (255, 80, 80),         # red
        "detecting": (255, 130, 130),  # blue-ish
    }

# Allowed style strings
CROSSHAIR_STYLES: list[str] = [
    "cross",
    "bracket",
    "circle",
    "cross+bracket",
    "cross+circle",
    "all",  # cross + bracket + circle
]

ERROR_UNITS_OPTIONS: list[str] = [
    "px",
    "mrad",
    "urad",
    "px+mrad",
]