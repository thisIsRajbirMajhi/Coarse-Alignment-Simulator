MAX_RES: int = 5000
MIN_RES: int = 50  # generic Scene engine limit for headless tests (50..5000)

# WORLD-SIZE POLICY: Per PDF Sr.1 — Screen Size (min.) 2000×2000, Optional User-defined.
#   Production now supports 2000..5000 (configurable) to allow performance trade-off:
#   5000×5000 = 25 MP (75 MB copy, heavy), 2000×2000 = 4 MP (~6× cheaper, meets 30 Hz).
#   - LIMITS["world_width/height"] = (2000,5000) per spec (min 2000).
#   - DEFAULTS = 2000×2000 for best FPS out-of-box; user can raise to 5000.
#   - Scene(...) generic engine still supports 50..5000 for headless tests (MIN_RES..MAX_RES).

DEFAULTS: dict = {
    "world_width": 2000,          # px, default 2000 per PDF min (user can raise to 5000)
    "world_height": 2000,         # px, default 2000 per PDF min
    "seed": 42,                   # int 0..999999, None means random
    "bg_top": 12,                 # int 0..60  — zenith (top) gradient color
    "bg_bottom": 22,              # int 0..80  — horizon (bottom) gradient color
    "vignetting_pct": 0,           # int 0..92  — edge darkening % (APPLIED at camera image stage,
                                   #              NOT world; follows camera FOV)
    "haze_pct": 35,               # int 0..100 — overall fog/haze level % (static field + scalar shimmer)
    "star_count": 60,             # int 0..4000 — star/clutter count
    "star_brightness": 1.0,       # float 0.5..1.8 — global brightness scale
}

# World configurable 2000..5000 per PDF (min 2000), God View shows full world at chosen size.
# Generic Scene engine allows 50..5000 for headless tests.
LIMITS: dict[str, tuple[float, float]] = {
    "world_width": (2000, 5000),
    "world_height": (2000, 5000),
    "seed": (0, 999999),
    "bg_top": (0, 60),
    "bg_bottom": (0, 80),
    "vignetting_pct": (0, 92),
    "haze_pct": (0, 100),
    "star_count": (0, 4000),
    "star_brightness": (0.5, 1.8),
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