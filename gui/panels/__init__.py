# gui/panels/__init__.py - Canonical panel exports
from __future__ import annotations

from gui.panels.base import BaseConfigPanel
from gui.panels.disturbances_panel import DisturbancesPanel
from gui.panels.environment_panel import EnvironmentPanel
from gui.panels.global_panel import GlobalPanel

__all__ = [
    "BaseConfigPanel",
    "GlobalPanel",
    "DisturbancesPanel",
    "EnvironmentPanel",
]


