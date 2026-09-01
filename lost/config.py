"""
Module: lost.config
Purpose: Typed, validated configuration for LOST phase.
Public API: LostConfig
Notes: Grace-period tuning — how long to retain estimate before discarding.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.config_base import BaseValidatedConfig, clip_field
from lost.constants import LOST_DEFAULTS, LOST_LIMITS

# ============================================================
# SECTION: LostConfig — reacquisition window
# ============================================================

@dataclass
class LostConfig(BaseValidatedConfig):
    """
    LOST tunables — loss-of-lock hold.

    - miss_limit (1..20): base threshold (from tracking)
    - lost_grace_mult (1.5..3.0): multiplier for LOST→SEARCHING timeout
    - acquire_hits (2..5): retained for symmetry (promotion needs hit)
    """

    LIMITS = LOST_LIMITS
    DEFAULTS = LOST_DEFAULTS

    miss_limit: int = LOST_DEFAULTS["miss_limit"]
    lost_grace_mult: float = LOST_DEFAULTS["lost_grace_mult"]
    acquire_hits: int = LOST_DEFAULTS["acquire_hits"]

    def validate(self) -> "LostConfig":
        self.miss_limit = int(clip_field(self.miss_limit, *self.LIMITS["miss_limit"]))
        self.lost_grace_mult = float(clip_field(self.lost_grace_mult, *self.LIMITS["lost_grace_mult"]))
        self.acquire_hits = int(clip_field(self.acquire_hits, *self.LIMITS["acquire_hits"]))
        return self
