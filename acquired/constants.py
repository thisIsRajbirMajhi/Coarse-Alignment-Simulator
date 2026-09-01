"""
Module: acquired.constants
Purpose: Single source for ACQUIRED-phase limits & defaults.
Public API: ACQUIRED_LIMITS, ACQUIRED_DEFAULTS
Notes: ACQUIRED is probation — first hit(s) before commit to LOCKED/TRACKING.
       Thresholds: acquire_hits (consecutive hits to confirm), miss_limit (misses to LOST).
"""

# ============================================================
# SECTION: Acquired limits — probation thresholds
# ============================================================

ACQUIRED_LIMITS: dict[str, tuple[float, float]] = {
    # Consecutive hits required to confirm TRACKING/LOCKED from ACQUIRED
    "acquire_hits": (2, 5),
    # Consecutive misses before ACQUIRED → LOST (loss-of-probation)
    "miss_limit": (1, 20),
}

ACQUIRED_DEFAULTS: dict = {
    "acquire_hits": 3,  # spec: 3 consecutive hits → LOCKED
    "miss_limit": 5,
}
