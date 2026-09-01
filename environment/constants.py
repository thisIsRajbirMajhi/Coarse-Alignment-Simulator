MAX_RES: int = 5000
MIN_RES: int = 50  # generic Scene engine limit for headless tests (50..5000)

# WORLD-SIZE POLICY: EXPLICITLY FIXED 5000×5000 (God View) for production.
#   - LIMITS["world_width/height"] = (5000,5000) locks EnvironmentConfig to fixed.
#   - Scene(...) generic engine still supports 50..5000 for tests, but production
#     path via EnvironmentConfig.validate() is fixed 5000×5000. This resolves the
#     world-size configuration inconsistency (fixed in production, generic for tests).
#   - DEFAULTS world_width/height = 5000 matches fixed policy.

DEFAULTS: dict = {
    "world_width": 5000,          # px, FIXED 5000 God View (LIMITS 5000,5000)
    "world_height": 5000,         # px, FIXED 5000 God View
    "seed": 42,                   # int 0..999999, None means random
    "bg_top": 12,                 # int 0..60  — zenith (top) gradient color
    "bg_bottom": 22,              # int 0..80  — horizon (bottom) gradient color
    "vignetting_pct": 0,           # int 0..92  — edge darkening % (APPLIED at camera image stage,
                                  #              NOT world; follows camera FOV)
    "haze_pct": 35,               # int 0..100 — overall fog/haze level % (static field + scalar shimmer)
    "star_count": 60,             # int 0..4000 — star/clutter count
    "star_brightness": 1.0,       # float 0.5..1.8 — global brightness scale
    "dynamic": False,             # bool — whether background animates
    "dynamic_speed": 1.0,         # float 0.1..5.0 — animation time multiplier
}

# God View FIXED 5000×5000, Camera Screen Size 2000-5000 configurable
# World size FIXED (5000,5000) in production; generic Scene allows 50..5000 for tests.
LIMITS: dict[str, tuple[float, float]] = {
    "world_width": (5000, 5000),
    "world_height": (5000, 5000),
    "seed": (0, 999999),
    "bg_top": (0, 60),
    "bg_bottom": (0, 80),
    "vignetting_pct": (0, 92),
    "haze_pct": (0, 100),
    "star_count": (0, 4000),
    "star_brightness": (0.5, 1.8),
    "dynamic_speed": (0.1, 5.0),
}

# Internal conversion helpers (kept here to avoid duplication)
# vignetting_pct (0..92) -> vignetting (0..0.92) for Scene internals
# haze_pct (0..100) -> haze_strength (0..1.0)

def vignetting_pct_to_strength(pct: int | float) -> float:
    """Convert GUI percentage (0-92) to internal strength (0-0.92)."""
    return float(pct) / 100.0

def vignetting_strength_to_pct(strength: float) -> int:
    """Convert internal strength (0-0.92) to GUI percentage (0-92)."""
    return int(round(float(strength) * 100))

def haze_pct_to_strength(pct: int | float) -> float:
    """Convert GUI percentage (0-100) to internal strength (0.0-1.0)."""
    return float(pct) / 100.0

def haze_strength_to_pct(strength: float) -> int:
    """Convert internal strength (0.0-1.0) to GUI percentage (0-100)."""
    return int(round(float(strength) * 100))