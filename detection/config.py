"""
Module: detection.config
Purpose: Typed, validated configuration for beacon detection.
Public API: DetectorConfig
Notes: Immediate migration — MainWindow can store DetectorConfig as single source.
       Stateless detector, so config is just thresholds (no temporal state).
"""

from __future__ import annotations

from dataclasses import dataclass

from common.config_base import BaseValidatedConfig, clip_field
from detection.constants import DETECTOR_DEFAULTS, DETECTOR_LIMITS

# ============================================================
# SECTION: DetectorConfig — thresholds (stateless)
# ============================================================

@dataclass
class DetectorConfig(BaseValidatedConfig):
    """
    Detector thresholds — stateless per-frame segmentation.

    - brightness_threshold (0..255): T in mask = (gray > T) ? 255 : 0
    - min_area (1..50): reject contours with area < min_area (px²)
    - max_beacons (1..20): cap detections per frame (sorted by confidence)
    """

    LIMITS = DETECTOR_LIMITS
    DEFAULTS = DETECTOR_DEFAULTS

    brightness_threshold: int = DETECTOR_DEFAULTS["brightness_threshold"]
    min_area: int = DETECTOR_DEFAULTS["min_area"]
    max_beacons: int = DETECTOR_DEFAULTS["max_beacons"]

    def validate(self) -> "DetectorConfig":
        self.brightness_threshold = int(clip_field(self.brightness_threshold, *self.LIMITS["brightness_threshold"]))
        self.min_area = int(clip_field(self.min_area, *self.LIMITS["min_area"]))
        self.max_beacons = int(clip_field(self.max_beacons, *self.LIMITS["max_beacons"]))
        return self
