"""
Module: acquired.config
Purpose: Typed, validated configuration for ACQUIRED phase.
Public API: AcquiredConfig
Notes: Probation tuning — how many hits to confirm lock, how many misses to lose probation.
"""

from __future__ import annotations

from dataclasses import dataclass

from acquired.constants import ACQUIRED_DEFAULTS, ACQUIRED_LIMITS
from common.config_base import BaseValidatedConfig, clip_field

# ============================================================
# SECTION: AcquiredConfig — probation thresholds
# ============================================================

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
