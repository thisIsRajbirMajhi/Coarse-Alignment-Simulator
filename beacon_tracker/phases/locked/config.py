# beacon_tracker/phases/locked/config.py
# Typed, validated configuration for LOCKED (=TRACKING) phase — moved from locked/config.py

from __future__ import annotations

from dataclasses import dataclass

from beacon_tracker.phases.locked.constants import LOCKED_DEFAULTS, LOCKED_LIMITS
from common.config_base import BaseValidatedConfig, clip_field


@dataclass
class LockedConfig(BaseValidatedConfig):
    """
    LOCKED (=TRACKING) tunables — stable lock.

    - smoothing (0..0.95): α in y[n]=α·y[n-1]+(1-α)·x[n] — RC low-pass
    - miss_limit (1..20): misses before LOCKED → LOST
    - acquire_hits (2..5): retained for symmetry (already satisfied)
    """

    LIMITS = LOCKED_LIMITS
    DEFAULTS = LOCKED_DEFAULTS

    smoothing: float = LOCKED_DEFAULTS["smoothing"]
    miss_limit: int = LOCKED_DEFAULTS["miss_limit"]
    acquire_hits: int = LOCKED_DEFAULTS["acquire_hits"]

    def validate(self) -> "LockedConfig":
        self.smoothing = float(clip_field(self.smoothing, *self.LIMITS["smoothing"]))
        self.miss_limit = int(clip_field(self.miss_limit, *self.LIMITS["miss_limit"]))
        self.acquire_hits = int(clip_field(self.acquire_hits, *self.LIMITS["acquire_hits"]))
        return self
