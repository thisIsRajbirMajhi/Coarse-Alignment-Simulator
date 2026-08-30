"""
Module: detection.config
Purpose: Typed, validated configuration for beacon detection.
Public API: DetectorConfig
Notes: Immediate migration — MainWindow can store DetectorConfig as single source.
       Stateless detector, so config is just thresholds (no temporal state).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from detection.constants import DETECTOR_DEFAULTS, DETECTOR_LIMITS

# ============================================================
# SECTION: DetectorConfig — thresholds (stateless)
# ============================================================

@dataclass
class DetectorConfig:
    """
    Detector thresholds — stateless per-frame segmentation.

    - brightness_threshold (0..255): T in mask = (gray > T) ? 255 : 0
    - min_area (1..50): reject contours with area < min_area (px²)
    - max_beacons (1..20): cap detections per frame (sorted by confidence)
    """

    brightness_threshold: int = DETECTOR_DEFAULTS["brightness_threshold"]
    min_area: int = DETECTOR_DEFAULTS["min_area"]
    max_beacons: int = DETECTOR_DEFAULTS["max_beacons"]

    def validate(self) -> "DetectorConfig":
        lo, hi = DETECTOR_LIMITS["brightness_threshold"]
        self.brightness_threshold = int(np.clip(int(self.brightness_threshold), lo, hi))
        lo, hi = DETECTOR_LIMITS["min_area"]
        self.min_area = int(np.clip(int(self.min_area), lo, hi))
        lo, hi = DETECTOR_LIMITS["max_beacons"]
        self.max_beacons = int(np.clip(int(self.max_beacons), lo, hi))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DetectorConfig":
        known = {k: v for k, v in data.items() if k in DETECTOR_DEFAULTS}
        return cls(**{**DETECTOR_DEFAULTS, **known}).validate()
