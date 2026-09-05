# beacon_tracker/phases/acquired/constants.py
# Single source for ACQUIRED-phase limits & defaults — moved from acquired/constants.py

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
