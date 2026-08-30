"""
Module: tracking.constants
Purpose: Single source for tracker limits & defaults (smoothing, miss, acquisition).
Public API: TRACKER_LIMITS, TRACKER_DEFAULTS
Notes: Consumed by TrackerConfig, ExponentialFilter, and StateMachine.
"""

# ============================================================
# SECTION: Tracker limits
# ============================================================

TRACKER_LIMITS: dict[str, tuple[float, float]] = {
    # Smoothing α in y[n]=α·y[n-1]+(1-α)·x[n] — 0=snap to detection, 1=ignore new
    "smoothing": (0.0, 0.95),
    # Miss limit — consecutive misses before LOST (frames)
    "miss_limit": (1, 20),
    # Hits to confirm TRACKING from ACQUIRED — probation hits required
    "acquire_hits": (2, 5),
    # Grace multiplier for LOST→SEARCHING (miss_limit * grace_mult)
    "lost_grace_mult": (1.5, 3.0),
}

TRACKER_DEFAULTS: dict = {
    "smoothing": 0.5,
    "miss_limit": 5,
    "acquire_hits": 3,          # matches spec: 3 consecutive hits → LOCKED
    "lost_grace_mult": 2.0,     # LOST→SEARCHING after 2×miss_limit misses
}
