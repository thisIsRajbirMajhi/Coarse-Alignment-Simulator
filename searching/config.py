"""
Module: searching.config
Purpose: Typed, validated configuration for SEARCHING phase.
Public API: SearchingConfig
Notes: Minimal — SEARCHING is intentionally lightweight. Most thresholds
       belong to acquired/locked/lost. This config governs scan pattern & timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.config_base import BaseValidatedConfig, clip_field
from searching.constants import SEARCHING_DEFAULTS, SEARCHING_LIMITS, SCAN_PATTERNS

# ============================================================
# SECTION: SearchingConfig — scan & timeout
# ============================================================

@dataclass
class SearchingConfig(BaseValidatedConfig):
    """
    SEARCHING tunables — active scan when no lock.

    - max_search_frames (10..10000): diagnostic timeout after which SEARCHING is declared stale
    - scan_dwell_frames (1..10): frames to hold at each scan cell before stepping
    - scan_pattern (spiral|raster|random): geometry of search sweep (future: drives camera move)
    """

    LIMITS = SEARCHING_LIMITS
    DEFAULTS = SEARCHING_DEFAULTS

    max_search_frames: int = SEARCHING_DEFAULTS["max_search_frames"]
    scan_dwell_frames: int = SEARCHING_DEFAULTS["scan_dwell_frames"]
    scan_pattern: str = SEARCHING_DEFAULTS["scan_pattern"]

    def validate(self) -> "SearchingConfig":
        self.max_search_frames = int(clip_field(self.max_search_frames, *self.LIMITS["max_search_frames"]))
        self.scan_dwell_frames = int(clip_field(self.scan_dwell_frames, *self.LIMITS["scan_dwell_frames"]))
        if self.scan_pattern not in SCAN_PATTERNS:
            self.scan_pattern = SEARCHING_DEFAULTS["scan_pattern"]
        return self
