"""
Package: beacon_tracker.detection
Purpose: Stateless per-frame CV blob detection pipeline.
Public API: BeaconDetector, DetectorConfig, preprocessing helpers
"""

from beacon_tracker.detection.config import DetectorConfig  # noqa: F401
from beacon_tracker.detection.constants import DETECTOR_DEFAULTS, DETECTOR_LIMITS, MORPH_KERNEL  # noqa: F401
from beacon_tracker.detection.detector import BeaconDetector  # noqa: F401
from beacon_tracker.detection.preprocessor import close_gaps, threshold_frame, to_grayscale  # noqa: F401

__all__ = [
    "BeaconDetector", "DetectorConfig",
    "DETECTOR_DEFAULTS", "DETECTOR_LIMITS", "MORPH_KERNEL",
    "to_grayscale", "threshold_frame", "close_gaps",
]
