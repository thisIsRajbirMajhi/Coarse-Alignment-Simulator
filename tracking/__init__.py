# tracking package — closed-loop perception (Camera -> YOLO -> Association -> Tracker -> State -> Control)
"""Perception and tracking stack. Control path never receives privileged ground truth."""

from tracking.association import AssociationConfig, associate
from tracking.detector import (
    BrightSpotDetector,
    Detection,
    DetectorConfig,
    UnifiedDetector,
    YOLO26Detector,
    bbox_to_center,
    pixel_error,
)

__all__ = [
    "AssociationConfig",
    "associate",
    "Detection",
    "DetectorConfig",
    "YOLO26Detector",
    "BrightSpotDetector",
    "UnifiedDetector",
    "bbox_to_center",
    "pixel_error",
]
