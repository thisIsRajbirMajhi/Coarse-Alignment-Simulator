"""
Module: gui.app — thin compatibility shim (refactored 2026).

Current modular structure (post-refactor, MainWindow 2578→~140 lines):

  Core:
    - gui.styles                       : APP_STYLE, SCENE_SIZE, FOV_SIZE, TICK_MS
    - gui.core.renderer                : Renderer (viewport/minimap, stateless)
    - gui.widgets.camera_card          : create_camera_card() (premium video card)
  Panels (gui/panels/* — all inherit BaseConfigPanel):
    - gui.panels.base                  : BaseConfigPanel (shared helpers)
    - gui.panels.dashboard_panel       : DashboardPanel (7 sections A-G, metrics only)
    - gui.panels.global_panel          : GlobalPanel (Start/Pause/Reset transport)
    - gui.panels.camera_panel          : CameraPanel (11 params: FOV, mechanics, display, units)
    - gui.panels.control_panel         : ControlPanel (P/PI/PID, gains, dead_zone, clamp, rate)
    - gui.panels.disturbances_panel    : DisturbancesPanel (Image Noise, Jitter, Atmosphere, Platform)
    - gui.panels.environment_panel     : EnvironmentPanel (World, Seed, Atmosphere, Starfield)  [canonical, shim at gui/environment_panel.py]
    - gui.panels.multi_beacon_panel    : MultiBeaconPanel (Count, Target, Shape, Motion, etc.) [canonical, shim at gui/multi_beacon_panel.py]
    - gui.panels.tuning_panel          : TuningPanel (Detection & Tracking)
  Windows:
    - gui.windows.control_window       : ControlDashboardWindow (detached control deck)
    - gui.windows.dashboard_window     : DashboardWindow (legacy, dummy after consolidation)
  Mixins (gui/mixins/* — each <400 lines, single responsibility):
    - gui.mixins.state_mixin           : StateMixin (dirty/_auto_timers/_snapshot)
    - gui.mixins.simulation_mixin      : SimulationMixin (_build_simulation)
    - gui.mixins.ui_mixin              : UIMixin (_build_ui, video stage, control tabs)
    - gui.mixins.beacon_mixin          : BeaconMixin (beacon handlers, randomize, hot-apply)
    - gui.mixins.scene_mixin           : SceneMixin (env/camera HOT applies, disturbance)
    - gui.mixins.control_mixin         : ControlMixin (global/control/tuning handlers)
    - gui.mixins.lifecycle_mixin       : LifecycleMixin (start/pause/reset/export/close)
    - gui.mixins.tick_mixin            : TickMixin (_tick pipeline)
    - gui.mixins.rendering_mixin       : RenderingMixin (viewport/minimap, photometry)
    - gui.mixins.stats_mixin           : StatsMixin (_update_stats → dashboard)
  Orchestrator:
    - gui.main_window                  : MainWindow (~140 lines, composes all mixins above + QMainWindow)

This shim re-exports the public API so existing imports keep working:

  from gui.app import MainWindow
  from gui.app import ControlDashboardWindow
  from main import main  -> still imports MainWindow from gui.app

Notes:
  - All new code should import directly from gui.main_window or specific panel modules.
  - Legacy import paths gui.environment_panel / gui.multi_beacon_panel still work via shims.
  - See gui/main_window.py docstring for MRO and delegation overview.
"""

from gui.main_window import MainWindow  # noqa: F401
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS  # noqa: F401
from gui.windows.control_window import ControlDashboardWindow  # noqa: F401

__all__ = ["MainWindow", "ControlDashboardWindow", "APP_STYLE", "SCENE_SIZE", "FOV_SIZE", "TICK_MS"]
