"""
Module: searching.constants
Purpose: Single source for SEARCHING-phase limits & defaults.
Public API: SEARCHING_LIMITS, SEARCHING_DEFAULTS, SCAN_PATTERNS
Notes: SEARCHING is the idle scan — no estimate, just waiting for first detection.
       Tunables are intentionally minimal; most thresholds live in acquired/locked/lost.
       Scan pattern is for future active-search (spiral raster) — currently stateless.
"""

# ============================================================
# SECTION: Searching limits — scan & timeout
# ============================================================

SEARCHING_LIMITS: dict[str, tuple[float, float]] = {
    # Max frames to remain in SEARCHING before declaring timeout (diagnostics)
    "max_search_frames": (10, 10000),
    # Scan dwell — frames to linger at each scan cell before stepping
    "scan_dwell_frames": (1, 10),
}

SEARCHING_DEFAULTS: dict = {
    "max_search_frames": 1000,
    "scan_dwell_frames": 1,
    "scan_pattern": "spiral",  # spiral | raster | random
}

# Supported active-scan geometries (future: drives camera move when no lock)
SCAN_PATTERNS: list[str] = ["spiral", "raster", "random"]
