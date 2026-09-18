# local_terminal/__init__.py - Local Terminal subsystem package per LocalTerminal.md
from __future__ import annotations

from local_terminal.acquisition import AcquisitionScanner
from local_terminal.acquisition_mgr import AcquisitionConfig2, AcquisitionManager
from local_terminal.association import CandidateAssociationManager
from local_terminal.candidate_detector import CandidateDetector
from local_terminal.config import (
    AcquisitionConfig,
    AngularModelConfig,
    DetectionConfig,
    DisplayConfig,
    IdentityConfig,
    LocalCameraConfig,
    LocalCommunicationConfig,
    LocalStateConfig,
    LocalTerminalConfig,
    PositionConfig,
    PTZConfig,
    RealismConfig,
    TrackingConfig,
)
from local_terminal.estimator import TrackStateEstimator
from local_terminal.frame_processor import FrameProcessor
from local_terminal.lifecycle import CandidateLifecycleManager
from local_terminal.metrics import TrackingMetrics
from local_terminal.models import (
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
from local_terminal.ptz_actuator import PTZActuatorModel
from local_terminal.reacquisition import ReacquisitionConfig, ReacquisitionManager
from local_terminal.search_manager import SearchManager
from local_terminal.signature import SignatureAnalyzer
from local_terminal.state_machine import LocalStateMachine
from local_terminal.states import CandidateState, LocalTerminalState
from local_terminal.system import LocalTerminalSystem
from local_terminal.telemetry_mgr import TelemetryManager
from local_terminal.terminal import LocalTerminal
from local_terminal.tracking import TargetTracker
from local_terminal.tracking_controller import TrackingController

__all__ = [
    "IdentityConfig",
    "LocalStateConfig",
    "PositionConfig",
    "LocalCameraConfig",
    "PTZConfig",
    "DisplayConfig",
    "AngularModelConfig",
    "RealismConfig",
    "AcquisitionConfig",
    "DetectionConfig",
    "TrackingConfig",
    "LocalCommunicationConfig",
    "LocalTerminalConfig",
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
    "SearchManager",
    "LocalStateMachine",
    "TelemetryManager",
    "TrackingMetrics",
]
