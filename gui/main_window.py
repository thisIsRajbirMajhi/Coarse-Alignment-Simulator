# gui/main_window.py - Simulator window (thin composition root).
#
#   MainWindow  ("Coarse Alignment Simulator" — its OWN window)
#    ├── SimulationView (FOV + world, fullscreen-capable)
#    └── ControlView (Start/Stop/Pause/Reset + Dashboard/FullScreen/Settings)
#    └── ApplicationController -> SimulationSession -> Simulation
#
# The Live Dashboard lives in its OWN separate window
# (gui/windows/dashboard_window.py, owned by WindowManager) — never mixed in here.
#
# No target/camera/disturbance/tracking/PID math lives here.
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QStatusBar, QVBoxLayout, QWidget,
)

from gui.application.commands import ApplyConfigCommand, SelectTargetCommand, SetDetectorThresholdCommand
from gui.application.controller import ApplicationController
from gui.application.session import SimulationSession
from gui.application.state import LifecycleState
from gui.core.window_manager import WindowManager
from gui.presentation.simulation_presenter import SimulationPresenter
from gui.styles import APP_STYLE, TICK_MS
from gui.views.control_view import ControlView
from gui.views.simulation_view import SimulationView

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Simulator window only. Constructs layout, attaches controller/views, connects signals."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coarse Alignment Simulator")
        self.setMinimumSize(1150, 760)
        self.resize(1350, 900)
        self.setStyleSheet(APP_STYLE)
        self._fullscreen = False

        # Application layer (owns sim)
        self.session = SimulationSession()
        self.session.ensure_built()
        self.controller = ApplicationController(self.session, self)
        self.presenter = SimulationPresenter()
        self.windows = WindowManager(self)

        # --- layout: header + fullscreen-capable simulation view ---
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QWidget(self)
        header.setObjectName("headerBar")
        hbox = QHBoxLayout(header)
        title = QLabel("Coarse Alignment Simulator", header)
        title.setObjectName("appTitle")
        hbox.addWidget(title)
        hbox.addStretch(1)
        self.controls = ControlView(header)
        hbox.addWidget(self.controls)
        root.addWidget(header)

        self.sim_view = SimulationView(self)
        root.addWidget(self.sim_view, 1)

        sb = QStatusBar(self)
        sb.showMessage("Ready — press Start")
        self.setStatusBar(sb)
        self._statusbar = sb

        # --- signals: views -> controller -> session ---
        self.controls.btn_start.clicked.connect(self.controller.start)
        self.controls.btn_stop.clicked.connect(self.controller.stop)
        self.controls.btn_pause.clicked.connect(self._on_pause_button)
        self.controls.btn_reset.clicked.connect(self._on_reset)
        self.controls.btn_dashboard.clicked.connect(lambda: self.windows.show_dashboard())
        self.controls.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.controls.btn_settings.clicked.connect(lambda: self.windows.show_settings(self.session))
        self.controller.stateChanged.connect(self._on_lifecycle)
        self.controller.errorRaised.connect(self._on_error)

        # Thin timer: sim high-freq, dashboard (separate window) throttled.
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(TICK_MS)
        self._tick_count = 0
        # Debounced hot-reload timers per config section (dragging a slider
        # must not rebuild the scene on every tick).
        self._config_timers: dict[str, QTimer] = {}
        self._pending_config: dict = {}
        self._apply_button_states()

    # -- dashboard proxy (separate window; kept as .dashboard for API compat)
    @property
    def dashboard(self):
        """The Live Dashboard view inside its own separate window (no auto-show)."""
        return self.windows.ensure_dashboard().view

    # -- fullscreen -----------------------------------------------------
    def toggle_fullscreen(self) -> None:
        try:
            if self._fullscreen or self.isFullScreen():
                self._fullscreen = False
                self.showMaximized()
                self.controls.btn_fullscreen.setText("Full Screen")
            else:
                self._fullscreen = True
                self.showFullScreen()
                self.controls.btn_fullscreen.setText("Exit Full Screen")
        except Exception as e:
            log.debug("simulator fullscreen toggle failed: %s", e)

    # -- thin timer -------------------------------------------------
    def on_timer(self) -> None:
        self.controller.step()
        snap = self.controller._last_snapshot
        if snap is not None and self.controller.lifecycle == LifecycleState.RUNNING:
            self.sim_view.render_snapshot(snap, self.session)
        self._tick_count += 1
        if self._tick_count % 3 == 0 or snap is None:
            state = self.presenter.update(snap, self.session, self.controller)
            try:
                self.dashboard.render(state)
            except Exception as e:
                log.debug("dashboard render skipped: %s", e)

    # -- slots --------------------------------------------------------
    def _on_pause_button(self) -> None:
        if self.controller.lifecycle == LifecycleState.PAUSED:
            self.controller.resume()
        else:
            self.controller.pause()

    def _on_reset(self) -> None:
        """Reset EVERYTHING: default configs, fresh session, fresh presentation.

        Drops the settings dialog so no stale panel value survives, and
        returns to STOPPED (explicit Start required).
        """
        try:
            self.session = SimulationSession()
            self.session.ensure_built()
            self.controller.session = self.session
        except Exception as e:
            self.controller.errorRaised.emit(f"Reset failed: {e}")
            log.exception("full reset failed")
            return
        self.controller.stop()  # STOPPED + counters cleared (emits stateChanged)
        try:
            self.presenter.reset()
        except Exception as e:
            log.debug("presenter reset skipped: %s", e)
        self.sim_view.invalidate_world_cache()
        self.windows.drop_settings()
        for timer in getattr(self, "_config_timers", {}).values():
            try:
                timer.stop()
            except Exception as e:
                log.debug("config timer stop skipped: %s", e)
        try:
            self.dashboard.render(self.presenter.update(None, self.session, self.controller))
        except Exception as e:
            log.debug("dashboard refresh after reset skipped: %s", e)

    def _on_lifecycle(self, value: str) -> None:
        self._apply_button_states()
        try:
            if value == LifecycleState.RUNNING.value:
                self._statusbar.showMessage(f"Running — {self.session.camera_config.fov_width}x{self.session.camera_config.fov_height} FOV")
            elif value == LifecycleState.PAUSED.value:
                self._statusbar.showMessage("Paused")
            elif value == LifecycleState.STOPPED.value:
                self._statusbar.showMessage("Stopped — press Start")
                self.presenter.reset()
                try:
                    self.dashboard.render(self.presenter.update(None, self.session, self.controller))
                except Exception as e:
                    log.debug("empty dashboard render failed: %s", e)
            else:
                self._statusbar.showMessage(value)
        except Exception as e:
            log.debug("status update skipped: %s", e)

    def _on_error(self, msg: str) -> None:
        try:
            self._statusbar.showMessage(msg)
        except Exception:
            pass
        log.error("%s", msg)

    def _apply_button_states(self) -> None:
        try:
            self.controls.apply_button_states(self.controller.button_states())
        except Exception as e:
            log.debug("button state apply failed: %s", e)

    # -- config intents (from SettingsDialog via WindowManager) ------
    # Structural sections are debounced: slider drags coalesce into one
    # apply ~250ms after the last change instead of rebuilding per tick.
    # Target/threshold apply instantly (cheap, no rebuild).
    def _schedule_config(self, section: str, apply) -> None:
        timer = self._config_timers.get(section)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda s=section: self._fire_config(s))
            self._config_timers[section] = timer
        self._pending_config[section] = apply
        timer.start(250)

    def _fire_config(self, section: str) -> None:
        apply = self._pending_config.pop(section, None)
        if apply is None:
            return
        try:
            apply()
        except Exception as e:
            log.debug("deferred %s apply skipped: %s", section, e)

    def _on_camera_config(self, cfg) -> None:
        self._schedule_config("camera", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="camera", config=cfg)))

    def _on_control_config(self, cfg) -> None:
        self._schedule_config("control", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="control", config=cfg)))

    def _on_environment_config(self, cfg) -> None:
        def _apply():
            self.controller.apply_config(ApplyConfigCommand(section="environment", config=cfg))
            self.sim_view.invalidate_world_cache()
            self.presenter.reset()  # new world = new run for metrics
        self._schedule_config("environment", _apply)

    def _on_disturbances_config(self, cfg) -> None:
        self._schedule_config("disturbances", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="disturbances", config=cfg)))

    def _on_beacons_config(self, cfg) -> None:
        def _apply():
            self.controller.apply_config(ApplyConfigCommand(section="beacons", config=cfg))
            self.sim_view.invalidate_world_cache()
            self.presenter.reset()  # new targets = new run for metrics
        self._schedule_config("beacons", _apply)

    def _on_target_selected(self, idx: int) -> None:
        self.controller.select_target(SelectTargetCommand(target_index=int(idx)))

    def _on_threshold(self, value: int) -> None:
        self.controller.set_detector_threshold(SetDetectorThresholdCommand(threshold=int(value)))

    # -- compat adapters (thin; new code does not use these) ---------
    def _start(self) -> None:
        self.controller.start()

    def _pause(self) -> None:
        self._on_pause_button()

    def _reset(self) -> None:
        self._on_reset()

    def _tick(self) -> None:
        self.on_timer()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.timer.stop()
        except Exception:
            pass
        for timer in getattr(self, "_config_timers", {}).values():
            try:
                timer.stop()
            except Exception as e:
                log.debug("config timer stop skipped: %s", e)
        try:
            self.windows.close_all()
        except Exception:
            pass
        super().closeEvent(event)
