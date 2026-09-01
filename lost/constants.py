# lost/constants.py - Single source for LOST-phase limits & defaults

LOST_LIMITS: dict[str, tuple[float, float]] = {
    # Misses before ACQUIRED/TRACKING → LOST (same as locked)
    "miss_limit": (1, 20),
    # Multiplier for LOST → SEARCHING (grace window): timeout = miss_limit * grace_mult
    "lost_grace_mult": (1.5, 3.0),
    # Also retain acquire_hits for LOST → ACQUIRED promotion (via next hit)
    "acquire_hits": (2, 5),
}

LOST_DEFAULTS: dict = {
    "miss_limit": 5,
    "lost_grace_mult": 2.0,  # LOST→SEARCHING after 10 misses (5*2)
    "acquire_hits": 3,
}