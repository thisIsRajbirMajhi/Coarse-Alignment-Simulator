"""
Module: tracking.config
Purpose: Typed, validated configuration for tracking / lock.
Public API: TrackerConfig
Notes: Immediate migration — MainWindow can store TrackerConfig.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from tracking.constants import TRACKER_DEFAULTS, TRACKER_LIMITS

# ============================================================
# SECTION: TrackerConfig — smoothing & miss/acquire thresholds
# ============================================================

@dataclass
class TrackerConfig:
    """
    Tracker tuning — controls lock state machine and smoothing.

    - smoothing (0..0.95): α in exponential filter
    - miss_limit (1..20): misses before ACQUIRED/TRACKING → LOST
    - acquire_hits (2..5): consecutive hits to confirm TRACKING
    - lost_grace_mult (1.5..3.0): LOST→SEARCHING after miss_limit * grace_mult
    """

    smoothing: float = TRACKER_DEFAULTS["smoothing"]
    miss_limit: int = TRACKER_DEFAULTS["miss_limit"]
    acquire_hits: int = TRACKER_DEFAULTS["acquire_hits"]
    lost_grace_mult: float = TRACKER_DEFAULTS["lost_grace_mult"]

    def validate(self) -> "TrackerConfig":
        lo, hi = TRACKER_LIMITS["smoothing"]
        self.smoothing = float(np.clip(float(self.smoothing), lo, hi))
        lo, hi = TRACKER_LIMITS["miss_limit"]
        self.miss_limit = int(np.clip(int(self.miss_limit), lo, hi))
        lo, hi = TRACKER_LIMITS["acquire_hits"]
        self.acquire_hits = int(np.clip(int(self.acquire_hits), lo, hi))
        lo, hi = TRACKER_LIMITS["lost_grace_mult"]
        self.lost_grace_mult = float(np.clip(float(self.lost_grace_mult), lo, hi))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackerConfig":
        known = {k: v for k, v in data.items() if k in TRACKER_DEFAULTS}
        return cls(**{**TRACKER_DEFAULTS, **known}).validate()
