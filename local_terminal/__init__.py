# local_terminal/__init__.py - Local Terminal subsystem package per LocalTerminal.md
from __future__ import annotations

from local_terminal.acquisition.acquisition import AcquisitionScanner
from local_terminal.acquisition.acquisition_mgr import AcquisitionConfig2, AcquisitionManager
from local_terminal.tracking.association import CandidateAssociationManager
from local_terminal.optical.candidate_detector import CandidateDetector
from local_terminal.config import (
    AcquisitionConfig,
    AngularModelConfig,
    DetectionConfig,
    DisplayConfig,
    IdentityConfig,
    LocalStateConfig,
    LocalTerminalConfig,
    PositionConfig,
    PTZCameraConfig,
    RealismConfig,
    ReceivingPayloadConfig,
    TargetPayloadConfig,
    TargetProfile,
    TrackingConfig,
)
from local_terminal.tracking.estimator import TrackStateEstimator
from local_terminal.signal.frame_processor import FrameProcessor
from local_terminal.core.lifecycle import CandidateLifecycleManager
from local_terminal.telemetry.metrics import TrackingMetrics
from local_terminal.core.models import (
    AcquisitionResult,
    CameraFrame,
    CandidateTrack,
    DetectionCandidate,
    PTZCommand,
    SearchCommand,
    SignatureScores,
    TargetIdentificationSignature,
    TargetState,
    TrackingStatus,
    UpdateInput,
    UpdateOutput,
)
from local_terminal.hardware.ptz_actuator import PTZActuatorModel
from local_terminal.acquisition.reacquisition import ReacquisitionConfig, ReacquisitionManager, can_merge_reacquisition
from local_terminal.acquisition.search_manager import SearchManager
from local_terminal.optical.signature import SignatureAnalyzer
from local_terminal.core.state_machine import LocalStateMachine
from local_terminal.core.states import CandidateState, LocalTerminalState
from local_terminal.core.system import LocalTerminalSystem
from local_terminal.telemetry.telemetry_mgr import TelemetryManager
from local_terminal.core.terminal import LocalTerminal
from local_terminal.tracking.tracking import TargetTracker
from local_terminal.tracking.tracking_controller import TrackingController

__all__ = [
    "IdentityConfig",
    "LocalStateConfig",
    "PositionConfig",
    "DisplayConfig",
    "AngularModelConfig",
    "RealismConfig",
    "AcquisitionConfig",
    "DetectionConfig",
    "TrackingConfig",
    "LocalTerminalConfig",
    "PTZCameraConfig",
    "ReceivingPayloadConfig",
    "TargetPayloadConfig",
    "AcquisitionScanner",
    "TargetTracker",
    "LocalTerminal",
    "CandidateState",
    "LocalTerminalState",
    "CameraFrame",
    "CandidateTrack",
    "DetectionCandidate",
    "TargetState",
    "UpdateInput",
    "UpdateOutput",
    "LocalTerminalSystem",
    "FrameProcessor",
    "CandidateDetector",
    "CandidateAssociationManager",
    "SignatureAnalyzer",
    "CandidateLifecycleManager",
    "AcquisitionManager",
    "AcquisitionConfig2",
    "TrackStateEstimator",
    "TrackingController",
    "PTZActuatorModel",
    "ReacquisitionManager",
    "ReacquisitionConfig",
    "can_merge_reacquisition",
    "SearchManager",
    "LocalStateMachine",
    "TelemetryManager",
    "TrackingMetrics",
    "TargetPayloadConfig",
]
