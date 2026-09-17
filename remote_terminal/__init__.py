# remote_terminal/__init__.py - Remote Terminal subsystem package
from __future__ import annotations

from remote_terminal.config import (
    BeaconConfig,
    CommunicationConfig,
    FormationConfig,
    IdentityConfig,
    MotionConfig,
    PositionConfig,
    RemoteTerminalConfig,
    RemoteTerminalScenarioConfig,
    StateConfig,
    TargetSignatureConfig,
)
from remote_terminal.optics import compute_temporal_factor, render_terminal_beacon_patch
from remote_terminal.scenario import RemoteTerminalScenario
from remote_terminal.terminal import RemoteTerminal

__all__ = [
    "IdentityConfig",
    "StateConfig",
    "PositionConfig",
    "BeaconConfig",
    "CommunicationConfig",
    "TargetSignatureConfig",
    "RemoteTerminalConfig",
    "FormationConfig",
    "MotionConfig",
    "RemoteTerminalScenarioConfig",
    "RemoteTerminal",
    "RemoteTerminalScenario",
    "render_terminal_beacon_patch",
    "compute_temporal_factor",
]
