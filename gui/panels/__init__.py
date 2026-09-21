# gui/panels/__init__.py - Canonical panel exports
from __future__ import annotations

from gui.panels.base import BaseConfigPanel
from gui.panels.camera_panel import CameraPanel
from gui.panels.controller_panel import ControllerPanel
from gui.panels.disturbances_panel import DisturbancesPanel
from gui.panels.environment_panel import EnvironmentPanel
from gui.panels.global_panel import GlobalPanel
from gui.panels.local_terminal_panel import LocalTerminalPanel
from gui.panels.remote_terminal_panel import RemoteTerminalPanel

__all__ = [
    "BaseConfigPanel",
    "GlobalPanel",
    "CameraPanel",
    "ControllerPanel",
    "DisturbancesPanel",
    "EnvironmentPanel",
    "LocalTerminalPanel",
    "RemoteTerminalPanel",
]


