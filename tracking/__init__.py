# tracking package — closed-loop perception (Camera -> YOLO -> Association -> Tracker -> State -> Control)
"""Perception and tracking stack. Control path never receives privileged ground truth."""

from tracking.association import AssociationConfig, associate, associate_multi, mahalanobis2, _appearance_score, _pred_bbox
from tracking.imm import IMMConfig, IMMTracker
from tracking.kalman import KalmanConfig, KalmanTracker
from tracking.metrics import FrameRecord, MetricsLogger
from tracking.pipeline import PipelineResult, TrackingPipeline
from tracking.state_machine import (
    ACQUISITION,
    DETECTED,
    LOCK,
    LOST,
    REACQUIRING,
    RE_ACQUISITION,
    SEARCH,
    SEARCHING,
    SPEC_TO_CODE,
    TRACK,
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
    bbox_iou,
    bbox_to_center,
    calibrate_classical_conf,
    fuse_detections_nms,
    intensity_refined_centroid,
    measurement_noise_for,
    pixel_error,
)

__all__ = [
    "AssociationConfig",
    "associate",
    "associate_multi",
    "mahalanobis2",
    "_appearance_score",
    "_pred_bbox",
    "KalmanConfig",
    "KalmanTracker",
    "IMMConfig",
    "IMMTracker",
    "AcquisitionStateMachine",
    "StateMachineConfig",
    "SEARCHING",
    "DETECTED",
    "TRACKING",
    "LOST",
    "REACQUIRING",
    "SEARCH",
    "ACQUISITION",
    "TRACK",
    "LOCK",
    "RE_ACQUISITION",
    "SPEC_TO_CODE",
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
    "intensity_refined_centroid",
    "measurement_noise_for",
    "calibrate_classical_conf",
    "bbox_iou",
    "fuse_detections_nms",
]
