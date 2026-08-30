"""
Module: gui.app — thin compatibility shim (modular refactor).

Original monolithic ~2285-line GUI has been split into focused, well-commented modules:

  - gui.styles                     : APP_STYLE, SCENE_SIZE, FOV_SIZE, TICK_MS
  - gui.windows.control_window     : ControlDashboardWindow
  - gui.panels.dashboard_panel     : DashboardPanel (6 sections)
  - gui.panels.global_panel        : GlobalPanel (motion, speed, threshold, controls)
  - gui.panels.camera_panel        : CameraPanel (FOV/display/gain)
  - gui.panels.disturbances_panel  : DisturbancesPanel (4 sliders)
  - gui.environment_panel          : EnvironmentPanel (10 params, grouped)
  - gui.beacon_panel / multi_beacon_panel : Beacon/MultiBeacon (8 per-beacon + 3 multi)
  - gui.core.renderer              : Renderer (viewport/minimap drawing)
  - gui.mixins.state_mixin         : StateMixin (dirty/HOT/snapshot)
  - gui.main_window                : MainWindow (orchestrator, ~600 lines, delegates to above)

This shim re-exports the public API so existing imports keep working:

  from gui.app import MainWindow
  from gui.app import ControlDashboardWindow  (optional)
  from main import main  -> still imports MainWindow from gui.app

Notes:
  - All new code should import directly from gui.main_window or specific panel modules.
  - Structured comments per module/section are in each extracted file.
"""

from gui.main_window import MainWindow  # noqa: F401
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS  # noqa: F401
from gui.windows.control_window import ControlDashboardWindow  # noqa: F401

__all__ = ["MainWindow", "ControlDashboardWindow", "APP_STYLE", "SCENE_SIZE", "FOV_SIZE", "TICK_MS"]
