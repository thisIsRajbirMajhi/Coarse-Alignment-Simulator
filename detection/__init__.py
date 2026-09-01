"""
Package: detection
Purpose: Isolated beacon detection — stateless per-frame blob finding.
Public API: BeaconDetector, DetectorConfig, preprocessing helpers
Architecture:
  - detector.py      : BeaconDetector (contour + moments → centroid)
  - preprocessing.py : grayscale + threshold + closing
  - config.py        : DetectorConfig (brightness_threshold, min_area, max_beacons)
  - constants.py     : DETECTOR_LIMITS, DETECTOR_DEFAULTS, MORPH_KERNEL
Notes: Detection is fully independent from tracking/searching/locked/lost.
       It runs every frame (no memory) and returns raw (x,y) or None.
       Tracking (searching/acquired/locked/lost) decides what to do with hits/misses.
"""

from detection.config import DetectorConfig  # noqa: F401
from detection.constants import DETECTOR_DEFAULTS, DETECTOR_LIMITS, MORPH_KERNEL  # noqa: F401
from detection.detector import BeaconDetector  # noqa: F401
from detection.preprocessing import close_gaps, threshold_frame, to_grayscale  # noqa: F401

__all__ = ["BeaconDetector", "DetectorConfig", "DETECTOR_DEFAULTS", "DETECTOR_LIMITS", "MORPH_KERNEL", "to_grayscale", "threshold_frame", "close_gaps"]
