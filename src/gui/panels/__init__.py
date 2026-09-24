# gui/panels/__init__.py - Canonical panel exports
from __future__ import annotations

from src.gui.panels.base import BaseConfigPanel
from src.gui.panels.camera_panel import CameraPanel
from src.gui.panels.controller_panel import ControllerPanel
from src.gui.panels.disturbances_panel import DisturbancesPanel
from src.gui.panels.environment_panel import EnvironmentPanel
from src.gui.panels.global_panel import GlobalPanel
from src.gui.panels.local_terminal_panel import LocalTerminalPanel
from src.gui.panels.remote_terminal_panel import RemoteTerminalPanel

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


