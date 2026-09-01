# searching/constants.py - Single source for SEARCHING-phase limits & defaults

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