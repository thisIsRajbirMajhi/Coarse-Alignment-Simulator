# gui/main_window.py - Refactored orchestrator (thin facade)
#
# AFTER:  ~150 lines orchestrator delegating to focused mixins:
#   - mixins.state_mixin        : dirty tracking, snapshots, debounced auto
#   - mixins.simulation_mixin   : _build_simulation (scene/beacons/camera/controller)
#   - mixins.ui_mixin           : _build_ui + video stage + control deck + dashboard host
#   - mixins.beacon_mixin       : beacon count/target, randomization, hot-apply
#   - mixins.scene_mixin        : environment & camera hot-apply (world/FOV), disturbance hot, seed
#   - mixins.control_mixin      : global speed/motion, control, gain sync
#   - mixins.lifecycle_mixin    : start/pause/reset/export/closeEvent
#   - mixins.tick_mixin         : _tick pipeline (dt, disturbances, direct control, perf)
#   - mixins.rendering_mixin    : _render_viewport/minimap, photometry, pixmap, minimap thumb cache
#   - mixins.stats_mixin        : _update_stats (perf summary → dashboard)
#
# Tracking/Search removed: MainWindow no longer exposes .tracker; use _last_detection/_last_estimate instead.
#   Legacy .tracker kept as dummy for compat but is None.

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMainWindow, QStatusBar

from camera.config import CameraConfig
from control.config import ControllerConfig
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from gui.styles import APP_STYLE, FOV_SIZE, SCENE_SIZE, TICK_MS
from target.config import MultiBeaconConfig

# Mixins — each ~100-400 lines, single responsibility (imported for MRO)
from gui.mixins.state_mixin import StateMixin
from gui.mixins.simulation_mixin import SimulationMixin
from gui.mixins.ui_mixin import UIMixin
from gui.mixins.beacon_mixin import BeaconMixin
from gui.mixins.scene_mixin import SceneMixin
from gui.mixins.control_mixin import ControlMixin
from gui.mixins.lifecycle_mixin import LifecycleMixin
from gui.mixins.tick_mixin import TickMixin
from gui.mixins.rendering_mixin import RenderingMixin
from gui.mixins.stats_mixin import StatsMixin


class MainWindow(
    StateMixin,
    SimulationMixin,
    UIMixin,
    BeaconMixin,
    SceneMixin,
    ControlMixin,
    LifecycleMixin,
    TickMixin,
    RenderingMixin,
    StatsMixin,
    QMainWindow,
):
    """Refactored MainWindow — thin orchestrator.

    Inherits behavior from mixins; __init__ wires configs, simulation, UI, timer, status bar.
    No business logic lives here anymore — only composition and window chrome.
    """

    def __init__(self):
        # Explicit QMainWindow init (avoids MRO super chain through 10 mixins with no __init__)
        QMainWindow.__init__(self)
        self.setWindowTitle("FSOC Coarse Alignment Simulator")
        self.setMinimumSize(1150, 760)
        self.resize(1350, 860)
        self.setStyleSheet(APP_STYLE)

        # ——— State ———
        self._camera_drift_state: dict = {}
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}
        self._scene_size = SCENE_SIZE
        self._fov_size = FOV_SIZE
        self._viewport_display_size = (2000, 2000)
        self._god_display_size = (2000, 2000)
        # Direct detection state (tracking removed)
        self._last_detection: tuple[float,float] | None = None
        self._last_estimate: tuple[float,float] | None = None
        self._last_all_detections: list[dict] = []
        self._last_lock_state: str = "searching"
        # Beacon/Target — per PDF Sr11 Random default location within world
        import random as _rnd_mw
        _ws, _hs = SCENE_SIZE
        _rx = _rnd_mw.randint(200, max(201, _ws - 200))
        _ry = _rnd_mw.randint(200, max(201, _hs - 200))
        self.beacon_config = MultiBeaconConfig(beacon_count=1, target_index=0, x=_rx, y=_ry).validate()
        self._beacon_count = int(self.beacon_config.beacon_count)
        self._hitbox_radius = 14
        self._center_radius = 2
        self._target_beacon_id = int(self.beacon_config.target_index)
        # Global tuning defaults — beacon_tracker removed
        self._sim_speed = 1.0
        self._global_brightness = 255
        self._global_radius = 5
        # Environment — single typed config (replaces _env_* attrs)
        self.env_config = EnvironmentConfig().validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))
        # Camera — 11 params (FOV, mechanics, display, units)
        self.camera_config = CameraConfig(
            fov_width=self._fov_size[0], fov_height=self._fov_size[1],
            viewport_width=self._viewport_display_size[0], viewport_height=self._viewport_display_size[1],
            god_width=self._god_display_size[0], god_height=self._god_display_size[1],
        ).validate(self._scene_size)
        # Controller — P/PI/PID, dead zone, clamp, update rate
        self.controller_config = ControllerConfig().validate()
        # Disturbance & Noise — full spec suite
        self.disturbance_config = DisturbanceConfig().validate()
        self._last_viewport_frame = None
        self._last_god_frame = None
        # Dirty tracking for Apply per-section
        self._dirty_tabs: set[str] = set()
        self._applied_snapshot: dict = {}
        # Debounced auto-timers per section
        self._auto_timers: dict[str, QTimer] = {}  # type: ignore

        # Build simulation objects (delegates to SimulationMixin._build_simulation)
        self._build_simulation()
        # Build UI (delegates to UIMixin._build_ui)
        self._build_ui()
        # Ensure control deck starts clean (clear any dirty flagged during init)
        try:
            self._dirty_tabs.clear()
        except Exception:
            pass

        # Install click animations for all buttons (visual feedback: scale + flash + opacity)
        try:
            from gui.core.button_animator import install_global_button_animation, install_button_animations_for_widget
            self._btn_animator = install_global_button_animation(self)
            if hasattr(self, "_control_widget") and self._control_widget is not None:
                install_button_animations_for_widget(self._control_widget)
            if hasattr(self, "control_deck_window") and self.control_deck_window is not None:
                install_button_animations_for_widget(self.control_deck_window)
            # Also cover main window itself (transport buttons etc.)
            install_button_animations_for_widget(self)
        except Exception as e:
            print(f"Button animation install failed: {e}")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._running = False
        self._last_tick_time = None
        self._last_rgb = None  # type: ignore
        self._pause_time = None

        # Status bar
        sb = QStatusBar()
        sb.showMessage("Ready — configure scene/viewport (up to 5000×5000) then Start")
        self.setStatusBar(sb)

        # Dummy tracker for backward compat (exposes status/estimated_position but no filtering)
        try:
            from types import SimpleNamespace
            self.tracker = SimpleNamespace(status=SimpleNamespace(value=self._last_lock_state), estimated_position=self._last_estimate, get_velocity=lambda: None)
        except Exception:
            self.tracker = None

    # ── Single-source sizes: proxy to configs (fixes duplication warnings) ──
    @property
    def _scene_size(self):
        try:
            if hasattr(self, "env_config") and self.env_config is not None:
                return (int(self.env_config.world_width), int(self.env_config.world_height))
        except Exception:
            pass
        return getattr(self, "_scene_cache", (2000, 2000))

    @_scene_size.setter
    def _scene_size(self, val):
        try:
            w, h = int(val[0]), int(val[1])
            self.__dict__["_scene_cache"] = (w, h)
            if hasattr(self, "env_config") and self.env_config is not None:
                self.env_config.world_width = w
                self.env_config.world_height = h
        except Exception:
            self.__dict__["_scene_cache"] = (2000, 2000)

    @property
    def _fov_size(self):
        try:
            if hasattr(self, "camera_config") and self.camera_config is not None:
                return (int(self.camera_config.fov_width), int(self.camera_config.fov_height))
        except Exception:
            pass
        return getattr(self, "_fov_cache", (640, 480))

    @_fov_size.setter
    def _fov_size(self, val):
        try:
            w, h = int(val[0]), int(val[1])
            self.__dict__["_fov_cache"] = (w, h)
            if hasattr(self, "camera_config") and self.camera_config is not None:
                self.camera_config.fov_width = w
                self.camera_config.fov_height = h
        except Exception:
            self.__dict__["_fov_cache"] = (640, 480)

    @property
    def _viewport_display_size(self):
        # camera_config is single source; fallback cache for early init before config exists
        try:
            if hasattr(self, "camera_config") and self.camera_config is not None:
                return (int(self.camera_config.viewport_width), int(self.camera_config.viewport_height))
        except Exception:
            pass
        return getattr(self, "_viewport_cache", (2000, 2000))

    @_viewport_display_size.setter
    def _viewport_display_size(self, val):
        try:
            w, h = int(val[0]), int(val[1])
            self.__dict__["_viewport_cache"] = (w, h)
            if hasattr(self, "camera_config") and self.camera_config is not None:
                self.camera_config.viewport_width = w
                self.camera_config.viewport_height = h
        except Exception:
            self.__dict__["_viewport_cache"] = (2000, 2000)

    @property
    def _god_display_size(self):
        try:
            if hasattr(self, "camera_config") and self.camera_config is not None:
                return (int(self.camera_config.god_width), int(self.camera_config.god_height))
        except Exception:
            pass
        return getattr(self, "_god_cache", (2000, 2000))

    @_god_display_size.setter
    def _god_display_size(self, val):
        try:
            w, h = int(val[0]), int(val[1])
            self.__dict__["_god_cache"] = (w, h)
            if hasattr(self, "camera_config") and self.camera_config is not None:
                self.camera_config.god_width = w
                self.camera_config.god_height = h
        except Exception:
            self.__dict__["_god_cache"] = (2000, 2000)
