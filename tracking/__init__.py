# tracking package — closed-loop perception (Camera -> YOLO -> Association -> Tracker -> State -> Control)
"""Perception and tracking stack. Control path never receives privileged ground truth."""

from tracking.association import AssociationConfig, associate
from tracking.kalman import KalmanConfig, KalmanTracker
from tracking.metrics import FrameRecord, MetricsLogger
from tracking.pipeline import PipelineResult, TrackingPipeline
from tracking.state_machine import (
    DETECTED,
    LOST,
    REACQUIRING,
    SEARCHING,
    TRACKING,
    AcquisitionStateMachine,
    StateMachineConfig,
)
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
    "KalmanConfig",
    "KalmanTracker",
    "AcquisitionStateMachine",
    "StateMachineConfig",
    "SEARCHING",
    "DETECTED",
    "TRACKING",
    "LOST",
    "REACQUIRING",
    "TrackingPipeline",
    "PipelineResult",
    "MetricsLogger",
    "FrameRecord",
    "Detection",
    "DetectorConfig",
    "YOLO26Detector",
    "BrightSpotDetector",
    "UnifiedDetector",
    "bbox_to_center",
    "pixel_error",
]
