# tracking/config.py - Typed, validated configuration for tracking / lock

from __future__ import annotations

from dataclasses import dataclass

from common.config_base import BaseValidatedConfig, clip_field
from tracking.constants import TRACKER_DEFAULTS, TRACKER_LIMITS

@dataclass
class TrackerConfig(BaseValidatedConfig):
    """
    Tracker tuning — controls lock state machine and smoothing.

    - smoothing (0..0.95): α in exponential filter
    - miss_limit (1..20): misses before ACQUIRED/TRACKING → LOST
    - acquire_hits (2..5): consecutive hits to confirm TRACKING
    - lost_grace_mult (1.5..3.0): LOST→SEARCHING after miss_limit * grace_mult
    """

    LIMITS = TRACKER_LIMITS
    DEFAULTS = TRACKER_DEFAULTS

    smoothing: float = TRACKER_DEFAULTS["smoothing"]
    miss_limit: int = TRACKER_DEFAULTS["miss_limit"]
    acquire_hits: int = TRACKER_DEFAULTS["acquire_hits"]
    lost_grace_mult: float = TRACKER_DEFAULTS["lost_grace_mult"]

    def validate(self) -> "TrackerConfig":
        self.smoothing = float(clip_field(self.smoothing, *self.LIMITS["smoothing"]))
        self.miss_limit = int(clip_field(self.miss_limit, *self.LIMITS["miss_limit"]))
        self.acquire_hits = int(clip_field(self.acquire_hits, *self.LIMITS["acquire_hits"]))
        self.lost_grace_mult = float(clip_field(self.lost_grace_mult, *self.LIMITS["lost_grace_mult"]))
        return self