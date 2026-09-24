# gui/main_window.py - Simulator window (thin composition root).
from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QStatusBar, QVBoxLayout, QWidget,
)

from src.gui.application.commands import ApplyConfigCommand
from src.gui.application.controller import ApplicationController
from src.gui.application.session import SimulationSession
from src.gui.application.state import LifecycleState
from src.gui.application.worker import SimWorker
from src.gui.theme import apply_theme
from src.gui.core.window_manager import WindowManager
from src.gui.presentation.simulation_presenter import SimulationPresenter
from src.gui.styles import TICK_MS
from src.gui.views.control_view import ControlView
from src.gui.views.simulation_view import SimulationView

log = logging.getLogger(__name__)

# Hot-reload debounce per config section (ms). Cheap in-place knobs
# (camera/PID/disturbances) apply fast for a live feel; heavyweight
# environment rebuilds (scene regen, world-size rebuild) wait longer so a
# slider drag coalesces into one rebuild instead of many.
HOT_RELOAD_DELAY_MS: dict[str, int] = {
    "camera": 150,
    "control": 150,
    "disturbances": 200,
    "remote_terminal": 300,
    "environment": 600,
    "local_terminal": 200,
    "preset": 50,
}
# When the sim worker holds the step mutex, a pending apply is re-queued
# (non-blocking) instead of freezing the GUI. Heavy env rebuilds already wait
# longer so they coalesce; busy retries are generous.
_BUSY_RETRY_MS = 70
_MAX_BUSY_RETRIES = 60


class MainWindow(QMainWindow):
    """Simulator window only. Constructs layout, attaches controller/views, connects signals."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coarse Alignment Simulator")
        self.setMinimumSize(1150, 760)
        self.resize(1350, 900)
        apply_theme(self)
        self._fullscreen = False

        # Application layer (owns sim)
        self.session = SimulationSession()
        self.session.ensure_built()
        self.controller = ApplicationController(self.session, self)
        self.presenter = SimulationPresenter()
        self.windows = WindowManager(self)
        # Sim worker: steps run off the GUI thread; snapshots return via
        # controller.snapshotReady (auto-queued). At most one step in flight.
        self.worker = SimWorker(self.controller, self)
        self._step_pending = False

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
        self.controls.btn_fov.clicked.connect(lambda: self.windows.show_fov())
        self.controls.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.controls.btn_settings.clicked.connect(lambda: self.windows.show_settings(self.session))
        # Queued: controller.step() executes in the worker thread, so its
        # signals must hop back to the GUI thread (AutoConnection would
        # deliver directly in the worker thread since the controller object
        # itself lives here — painting off-thread would crash).
        self.controller.stateChanged.connect(self._on_lifecycle, Qt.QueuedConnection)
        self.controller.errorRaised.connect(self._on_error, Qt.QueuedConnection)
        self.controller.snapshotReady.connect(self._on_snapshot, Qt.QueuedConnection)

        # Thin timer: sim high-freq, dashboard throttled.
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(TICK_MS)
        self._tick_count = 0
        # Debounced hot-reload timers per config section.
        self._config_timers: dict[str, QTimer] = {}
        self._pending_config: dict = {}
        self._config_retries: dict[str, int] = {}
        self._apply_button_states()
        self._refresh_live_badge()

    def _refresh_live_badge(self) -> None:
        try:
            from src.gui.application.state import LifecycleState as _LS
            self.controls.set_live(
                pending=bool(self._pending_config),
                running=self.controller.lifecycle == _LS.RUNNING,
            )
        except Exception as e:
            log.debug("live badge refresh skipped: %s", e)

    # -- dashboard proxy
    @property
    def dashboard(self):
        """The Live Dashboard view inside its own separate window."""
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
        # Repaint timer only: request one worker step when running. The step
        # itself runs off-thread; painting happens in _on_snapshot. If the
        # previous step hasn't returned, skip (coalesce to lower FPS).
        try:
            if self.controller.lifecycle == LifecycleState.RUNNING and not self._step_pending:
                self._step_pending = True
                self.worker.request_step()
        except Exception as e:
            log.debug("step request skipped: %s", e)

    def _refresh_status_bar(self) -> None:
        """Compact status strip (Design.md §17):
        ● LIVE | Seed 42 | 2000×2000 | Fog 100% | Turb 4 (collapses narrow).
        ERROR latches the last error until recovery (Start/Reset)."""
        try:
            state = self.controller.lifecycle
            if state == LifecycleState.RUNNING:
                dot = "● LIVE"
            elif state == LifecycleState.PAUSED:
                dot = "◌ PAUSED"
            elif state == LifecycleState.ERROR:
                dot = "⚠ ERROR"
            else:
                dot = "○ IDLE"
        except Exception:
            dot = "○ IDLE"
        try:
            seed = self.session.env_config.seed
            seed_t = f"Seed {int(seed)}" if seed is not None else "Seed —"
            world_t = f"{int(self.session.env_config.world_width)}×{int(self.session.env_config.world_height)}"
        except Exception:
            seed_t, world_t = "Seed —", "—×—"
        try:
            dc = self.session.disturbance_config
            preset = str(getattr(dc, "atmospheric_preset", "Clear"))
            sev = int(float(getattr(dc, "channel_severity", 1.0)) * 100)
            turb = int(getattr(dc, "turbulence", 0))
            dist_t = f"{preset} {sev}% | Turb {turb}"
        except Exception:
            dist_t = "—"
        try:
            narrow = self.centralWidget() is not None and self.centralWidget().width() < 900
        except Exception:
            narrow = False
        try:
            if self.controller.lifecycle == LifecycleState.ERROR:
                err = getattr(self.controller, "last_error", None) or "simulation fault"
                self._statusbar.showMessage(f"{dot} — {err}  |  Start or Reset to recover")
            elif narrow:
                self._statusbar.showMessage(f"{dot}  |  {seed_t}  |  Custom")
            else:
                self._statusbar.showMessage(f"{dot}  |  {seed_t}  |  {world_t}  |  {dist_t}")
        except Exception as e:
            log.debug("status strip refresh skipped: %s", e)

    def _on_snapshot(self, snap) -> None:
        self._step_pending = False
        if snap is None:
            return
        if self.controller.lifecycle != LifecycleState.RUNNING:
            return
        # Overload guard: sim + OpenCV share the 16 ms budget (60 FPS).
        # If the last step nearly filled it, skip viewport paint this tick
        # (keep sim + throttled dashboard running) so the UI degrades
        # gracefully instead of freezing. Threshold 14 ms leaves 2 ms margin.
        try:
            _proc = self.controller._proc_ms[-1] if getattr(self.controller, "_proc_ms", None) else 0.0
        except Exception:
            _proc = 0.0
        _overloaded = bool(_proc > 14.0)
        if not _overloaded:
            self.sim_view.render_snapshot(snap, self.session)
        self._tick_count += 1
        if self._tick_count % 4 == 0:
            state = self.presenter.update(snap, self.session, self.controller)
            try:
                self.dashboard.render(state)
            except Exception as e:
                log.debug("dashboard render skipped: %s", e)
            self._refresh_status_bar()
            if getattr(self.windows, "fov_window", None) is not None and self.windows.fov_window.isVisible():
                try:
                    self.windows.fov_window.render_snapshot(snap, self.session)
                except Exception as e:
                    log.debug("fov render skipped: %s", e)
            if getattr(self.windows, "_settings", None) is not None:
                if self.windows._settings.isVisible():
                    try:
                        telemetry_packet = {}
                        if getattr(snap, "terminals", None) is not None:
                            telemetry_packet["terminals"] = snap.terminals
                        self.windows._settings.update_telemetry(telemetry_packet)
                    except Exception as e:
                        log.debug("dialog telemetry update skipped: %s", e)

    # -- slots --------------------------------------------------------
    def _on_pause_button(self) -> None:
        self.controller.toggle_pause()

    def _on_reset(self) -> None:
        """Reset EVERYTHING: default configs, fresh session, fresh presentation.
        Control Deck stays open — just refreshes its panels from the new session.
        """
        try:
            with self.worker.try_guard(timeout_ms=2000):
                ok = self.controller.full_reset()
        except TimeoutError as e:
            self._on_error(f"Reset failed: {e}")
            return
        except Exception as e:
            self._on_error(f"Reset failed ({type(e).__name__}): {e}")
            log.exception("full reset failed")
            return
        if not ok:
            return
        self.session = self.controller.session
        try:
            self.presenter.reset()
        except Exception as e:
            log.debug("presenter reset skipped: %s", e)
        self.sim_view.invalidate_world_cache()
        # Keep Control Deck open — just sync it to new session instead of closing.
        self.clear_pending_configs()
        try:
            self.windows.sync_dialog(self.session)
        except Exception as e:
            log.debug("settings sync after reset skipped: %s", e)
        try:
            self.dashboard.render(self.presenter.update(None, self.session, self.controller))
        except Exception as e:
            log.debug("dashboard refresh after reset skipped: %s", e)

    def _on_lifecycle(self, value: str) -> None:
        self._apply_button_states()
        self._refresh_live_badge()
        if value != LifecycleState.RUNNING.value:
            self._step_pending = False
        try:
            if value == LifecycleState.STOPPED.value:
                self.presenter.reset()
                try:
                    self.dashboard.render(self.presenter.update(None, self.session, self.controller))
                except Exception as e:
                    log.debug("empty dashboard render failed: %s", e)
            elif value == LifecycleState.ERROR.value:
                # Unfreeze the dashboard so it reports ERROR instead of a stale RUNNING.
                try:
                    self.dashboard.render(self.presenter.update(None, self.session, self.controller))
                except Exception as e:
                    log.debug("error dashboard render failed: %s", e)
            self._refresh_status_bar()
        except Exception as e:
            log.debug("status update skipped: %s", e)

    def _on_error(self, msg: str) -> None:
        try:
            text = str(msg)
            self._statusbar.showMessage(text if text.startswith("⚠") else f"⚠ {text}")
        except Exception:
            pass
        log.error("%s", msg)

    def _apply_button_states(self) -> None:
        try:
            self.controls.apply_button_states(self.controller.button_states())
        except Exception as e:
            log.debug("button state apply failed: %s", e)

    # -- config intents (from SettingsDialog via WindowManager) ------
    @property
    def has_pending_configs(self) -> bool:
        """True while a debounced hot-reload apply is queued."""
        return bool(getattr(self, "_pending_config", {}))

    def clear_pending_configs(self) -> None:
        """Drop queued hot-reload applies (e.g. Reset swaps the session)."""
        for timer in getattr(self, "_config_timers", {}).values():
            try:
                timer.stop()
            except Exception as e:
                log.debug("config timer stop skipped: %s", e)
        try:
            self._pending_config.clear()
        except Exception:
            pass
        try:
            self._config_retries.clear()
        except Exception:
            pass
        self._refresh_live_badge()

    def flush_pending_configs(self) -> None:
        """Apply every queued config immediately (e.g. before Start/close)."""
        for section in list(getattr(self, "_pending_config", {}).keys()):
            try:
                timer = self._config_timers.get(section)
                if timer is not None:
                    timer.stop()
            except Exception as e:
                log.debug("config timer stop skipped: %s", e)
            self._fire_config(section)

    def _schedule_config(self, section: str, apply) -> None:
        timer = self._config_timers.get(section)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda s=section: self._fire_config(s))
            self._config_timers[section] = timer
        # Last-write-wins: only the newest config per section is kept.
        self._pending_config[section] = apply
        self._config_retries[section] = 0
        timer.start(HOT_RELOAD_DELAY_MS.get(section, 250))
        self._refresh_live_badge()

    def _fire_config(self, section: str) -> None:
        apply = self._pending_config.get(section)
        if apply is None:
            self._refresh_live_badge()
            return
        # Non-blocking busy handling: never freeze the GUI waiting on the
        # worker mutex — re-queue briefly, then surface a stuck worker.
        try:
            locked = self.worker.mutex.tryLock()
        except TypeError:
            try:
                locked = self.worker.mutex.tryLock(0)
            except Exception:
                locked = False
        if not locked:
            retries = int(self._config_retries.get(section, 0)) + 1
            self._config_retries[section] = retries
            if retries > _MAX_BUSY_RETRIES:
                self._pending_config.pop(section, None)
                self._config_retries.pop(section, None)
                self._refresh_live_badge()
                msg = f"{section} config not applied: sim busy"
                try:
                    self._statusbar.showMessage(f"⚠ {msg}")
                except Exception:
                    pass
                log.warning("deferred %s apply gave up after %d retries", section, retries)
                return
            try:
                self._config_timers[section].start(_BUSY_RETRY_MS)
            except Exception as e:
                log.debug("config retry schedule skipped: %s", e)
            return
        try:
            ok = apply()
            # controller.apply_config returns False on validation failure;
            # lambdas wrapping it forward that value (None = legacy success).
            if ok is False:
                raise ValueError(f"invalid {section} config rejected")
            self._pending_config.pop(section, None)
            self._config_retries.pop(section, None)
            self._refresh_live_badge()
            self._refresh_status_bar()
        except Exception as e:
            # Roll the open Control Deck back to session truth so the
            # sliders never silently diverge from what is actually running.
            self._pending_config.pop(section, None)
            self._config_retries.pop(section, None)
            self._refresh_live_badge()
            try:
                self.windows.sync_dialog(self.session)
            except Exception:
                pass
            try:
                self._statusbar.showMessage(f"⚠ {section} config not applied ({type(e).__name__}): {e}")
            except Exception:
                pass
            log.warning("deferred %s apply failed: %s", section, e)
        finally:
            try:
                self.worker.mutex.unlock()
            except Exception:
                pass

    def _on_camera_config(self, cfg) -> None:
        self._schedule_config("camera", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="camera", config=cfg)))

    def _on_control_config(self, cfg) -> None:
        self._schedule_config("control", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="control", config=cfg)))

    def _on_environment_config(self, cfg) -> None:
        def _apply():
            ok = self.controller.apply_config(ApplyConfigCommand(section="environment", config=cfg))
            if ok is False:
                return False
            self.sim_view.invalidate_world_cache()
            self.presenter.reset()
            self.windows.sync_dialog(self.session)
            return True
        self._schedule_config("environment", _apply)

    def _on_disturbances_config(self, cfg) -> None:
        self._schedule_config("disturbances", lambda: self.controller.apply_config(
            ApplyConfigCommand(section="disturbances", config=cfg)))

    def _on_remote_config(self, cfg) -> None:
        def _apply():
            ok = self.controller.apply_config(ApplyConfigCommand(section="remote_terminal", config=cfg))
            if ok is False:
                return False
            self.windows.sync_dialog(self.session)
            return True
        self._schedule_config("remote_terminal", _apply)

    def _on_local_config(self, cfg) -> None:
        # Throttle local autonomy: many spin boxes fire rapidly while editing —
        # coalesce via short debounce (200ms) already in _schedule_config.
        def _apply():
            ok = self.controller.apply_config(ApplyConfigCommand(section="local_terminal", config=cfg))
            if ok is False:
                return False
            self.windows.sync_dialog(self.session)
            return True
        self._schedule_config("local_terminal", _apply)

    def _apply_preset_bulk(self, preset_id: str) -> None:
        """Bulk preset apply — stop → restore defaults → load preset → start.

        Contract per user request: applying a preset automatically stops any
        running process, restores everything to defaults (fresh session),
        loads the preset bundle properly, and starts the simulation.
        One mutex hold so worker never sees a half-applied preset.
        """
        from src.gui.panels.presets_panel import apply_preset_to_session as _apply_bundle
        with self.worker.try_guard(timeout_ms=4000):
            # 1. Stop any running simulation (RUNNING/PAUSED → STOPPED).
            try:
                if self.controller.lifecycle != self.controller.lifecycle.__class__.STOPPED:
                    self.controller.stop()
            except Exception as e:
                log.debug("preset stop skipped: %s", e)
            self._step_pending = False
            self.clear_pending_configs()
            # 2. Restore everything to defaults (fresh session, STOPPED).
            ok = self.controller.full_reset()
            if not ok:
                raise RuntimeError(f"preset {preset_id}: full_reset failed")
            self.session = self.controller.session
            # 3. Load preset bundle onto the fresh default session.
            try:
                _apply_bundle(self.session, preset_id)
            except Exception as e:
                log.warning("preset %s bundle apply failed: %s", preset_id, e)
                raise
            # 4. Housekeeping — one sync/clear, not 6 separate rebuilds.
            try:
                self.sim_view.invalidate_world_cache()
            except Exception:
                pass
            try:
                self.presenter.reset()
            except Exception:
                pass
            try:
                self.windows.sync_dialog(self.session)
            except Exception:
                pass
            try:
                self._refresh_status_bar()
            except Exception:
                pass
            try:
                self._refresh_live_badge()
            except Exception:
                pass
            try:
                self._apply_button_states()
            except Exception:
                pass
            # 5. Start simulation with the new preset config.
            if not self.controller.start():
                log.warning("preset %s: start after apply did not transition (already RUNNING?)", preset_id)
            try:
                self._refresh_status_bar()
                self._refresh_live_badge()
                self._apply_button_states()
            except Exception:
                pass

    # -- compat adapters --------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.clear_pending_configs()
        except Exception as e:
            log.debug("config clear skipped: %s", e)
        try:
            self.windows.close_all()
        except Exception:
            pass
        try:
            self.worker.shutdown()
        except Exception as e:
            log.debug("worker shutdown skipped: %s", e)
        super().closeEvent(event)
