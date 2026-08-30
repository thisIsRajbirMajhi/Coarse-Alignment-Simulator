"""
Module: target.constants
Purpose: Single source of truth for Beacon/Target limits & defaults.
Public API: BEACON_LIMITS, BEACON_DEFAULTS, MULTI_BEACON_LIMITS, MULTI_BEACON_DEFAULTS
Notes: Consumed by BeaconConfig, Target, and GUI panels for consistent clamping.
"""

# ============================================================
# SECTION: Per-Beacon Limits
# ============================================================

BEACON_LIMITS: dict[str, tuple[float, float]] = {
    # Visual / photometric
    "brightness": (0, 255),        # Beacon intensity (0–255), scintillation clips 180–255
    "radius": (1, 15),             # Visual size (px)
    # Detection geometry — hitbox ≥ visual radius for acquisition
    "hitbox_radius": (3, 80),      # Valid "detected" hit radius (px)
    "center_radius": (1, 10),      # Precise/centered hit radius (px) — subset of hitbox
    # Dynamics
    "speed": (5, 300),             # px/s
    "position_seed": (0, 999999),  # Random seed for starting position generation
    "x": (0, 5000),                # World X (clamped to bounds at runtime)
    "y": (0, 5000),                # World Y
    "heading": (0, 360),           # Degrees
}

BEACON_DEFAULTS: dict = {
    "enabled": True,
    "profile": "curved",           # MotionProfile value string
    "position_seed": 42,           # Seed for starting position randomisation
    "x": 400.0,
    "y": 300.0,
    "speed": 60.0,
    "brightness": 255,
    "radius": 5,
    "hitbox_radius": 14,
    "center_radius": 2,
    "heading": None,               # None → random from RNG, else 0–360 deg
    "beacon_id": 0,
}

# ============================================================
# SECTION: Multi-Beacon Limits
# ============================================================

MULTI_BEACON_LIMITS: dict[str, tuple[int, int]] = {
    "beacon_count": (1, 16),       # Total beacons in scene (GUI caps 12, factory allows 16)
    "target_index": (0, 15),       # Which beacon is tracked (others = distractors)
}

MULTI_BEACON_DEFAULTS: dict = {
    "beacon_count": 1,
    "target_index": 0,
}
