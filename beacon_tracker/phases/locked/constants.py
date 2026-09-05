# beacon_tracker/phases/locked/constants.py
# Single source for LOCKED (=TRACKING) limits & defaults — moved from locked/constants.py

LOCKED_LIMITS: dict[str, tuple[float, float]] = {
    # Smoothing α in y[n]=α·y[n-1]+(1-α)·x[n] — 0=snap, 0.95=heavy
    "smoothing": (0.0, 0.95),
    # Misses before LOCKED → LOST
    "miss_limit": (1, 20),
    # Consecutive hits already satisfied (kept for symmetry)
    "acquire_hits": (2, 5),
}

LOCKED_DEFAULTS: dict = {
    "smoothing": 0.5,  # RC low-pass τ≈1.44 frames
    "miss_limit": 5,
    "acquire_hits": 3,
}
