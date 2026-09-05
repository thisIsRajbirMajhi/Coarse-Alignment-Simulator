# gui/panels/__init__.py - Canonical panel exports

from gui.panels.base import BaseConfigPanel  # noqa: F401
from gui.panels.global_panel import GlobalPanel  # noqa: F401
from gui.panels.camera_panel import CameraPanel  # noqa: F401
from gui.panels.control_panel import ControlPanel  # noqa: F401
from gui.panels.disturbances_panel import DisturbancesPanel  # noqa: F401
from gui.panels.environment_panel import EnvironmentPanel  # noqa: F401
from gui.panels.multi_beacon_panel import MultiBeaconPanel  # noqa: F401
from gui.panels.dashboard_panel import DashboardPanel  # noqa: F401
from gui.panels.tuning_panel import TuningPanel  # noqa: F401
from gui.panels.presets_panel import PresetsPanel, PRESETS  # noqa: F401

__all__ = [
    "BaseConfigPanel",
    "GlobalPanel",
    "CameraPanel",
    "ControlPanel",
    "DisturbancesPanel",
    "EnvironmentPanel",
    "MultiBeaconPanel",
    "DashboardPanel",
    "TuningPanel",
    "PresetsPanel",
    "PRESETS",
]
