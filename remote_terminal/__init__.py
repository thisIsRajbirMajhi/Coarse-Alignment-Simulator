# remote_terminal/__init__.py - Remote Terminal subsystem package
from __future__ import annotations

from remote_terminal.config import (
    BeaconConfig,
    FormationConfig,
    IdentityConfig,
    MotionConfig,
    PositionConfig,
    RemoteBeacon,
    RemoteTerminalConfig,
    RemoteTerminalScenarioConfig,
    StateConfig,
    make_2d_scenario,
    make_2d_terminal,
)
from remote_terminal.optics import compute_temporal_factor, render_terminal_beacon_patch
from remote_terminal.scenario import RemoteTerminalScenario
from remote_terminal.terminal import RemoteTerminal

__all__ = [
    "IdentityConfig",
    "StateConfig",
    "PositionConfig",
    "BeaconConfig",
    "RemoteTerminalConfig",
    "FormationConfig",
    "MotionConfig",
    "RemoteTerminalScenarioConfig",
    "RemoteBeacon",
    "make_2d_terminal",
    "make_2d_scenario",
    "RemoteTerminal",
    "RemoteTerminalScenario",
    "render_terminal_beacon_patch",
    "compute_temporal_factor",
]
