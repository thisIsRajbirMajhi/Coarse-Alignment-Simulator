# local_terminal/__init__.py - Local Terminal subsystem package per LocalTerminal.md
from __future__ import annotations

from local_terminal.acquisition import AcquisitionScanner
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
from local_terminal.detection import DetectionEngine
from local_terminal.terminal import LocalTerminal
from local_terminal.tracking import TargetTracker

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
    "DetectionEngine",
    "TargetTracker",
    "LocalTerminal",
]
