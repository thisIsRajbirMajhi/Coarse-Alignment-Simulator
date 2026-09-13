"""
Module: gui.app — public entry (console architecture).

  Application (Qt-free sim ownership):
    - gui.application.session          : SimulationSession (Scene/Beacons/Camera/PID/Pipeline)
    - gui.application.controller       : ApplicationController (lifecycle/step/timing)
    - gui.application.state/commands   : LifecycleState/UIState, intent commands
  Presentation (Qt-free view models):
    - gui.presentation.view_state      : DashboardState + formatters
    - gui.presentation.simulation_presenter : Snapshot+metrics -> DashboardState
  Views (Qt, no sim access):
    - gui.views.simulation_view        : FOV + world surfaces
    - gui.views.dashboard_view         : Live Dashboard (reference design)
    - gui.views.control_view           : Start/Stop/Pause/Reset primary controls
    - gui.views.settings_dialog        : secondary config (pure input panels)
  Core:
    - gui.styles                       : APP_STYLE, SCENE_SIZE, FOV_SIZE, TICK_MS
    - gui.core.renderer                : Renderer (viewport/minimap overlays, stateless)
    - gui.core.frame_presenter         : NumPy -> QPixmap
    - gui.core.photon_renderer         : beacon photon patches (sim-owned)
    - gui.core.window_manager          : secondary windows
  Panels (gui/panels/* — pure inputs: display/validate/emit Config):
    - gui.panels.base/global/camera/control/disturbances/environment/multi_beacon
  Orchestrator:
    - gui.main_window                  : MainWindow (thin composition root)

  from gui.app import MainWindow
  from main import main  -> imports MainWindow from gui.app
"""

from gui.main_window import MainWindow  # noqa: F401
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS  # noqa: F401

__all__ = ["MainWindow", "APP_STYLE", "SCENE_SIZE", "FOV_SIZE", "TICK_MS"]
