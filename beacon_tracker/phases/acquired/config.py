# beacon_tracker/phases/acquired/config.py
# Typed, validated configuration for ACQUIRED phase — moved from acquired/config.py

from __future__ import annotations

from dataclasses import dataclass

from beacon_tracker.phases.acquired.constants import ACQUIRED_DEFAULTS, ACQUIRED_LIMITS
from common.config_base import BaseValidatedConfig, clip_field


@dataclass
class AcquiredConfig(BaseValidatedConfig):
    """
    ACQUIRED tunables — probation after first hit.

    - acquire_hits (2..5): consecutive hits to promote ACQUIRED → LOCKED/TRACKING
    - miss_limit (1..20): consecutive misses to demote ACQUIRED → LOST
    """

    LIMITS = ACQUIRED_LIMITS
    DEFAULTS = ACQUIRED_DEFAULTS

    acquire_hits: int = ACQUIRED_DEFAULTS["acquire_hits"]
    miss_limit: int = ACQUIRED_DEFAULTS["miss_limit"]

    def validate(self) -> "AcquiredConfig":
        self.acquire_hits = int(clip_field(self.acquire_hits, *self.LIMITS["acquire_hits"]))
        self.miss_limit = int(clip_field(self.miss_limit, *self.LIMITS["miss_limit"]))
        return self
