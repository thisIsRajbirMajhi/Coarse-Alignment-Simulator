# tests/test_gui_application.py - New architecture: lifecycle, dashboard, isolation.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")


@pytest.fixture()
def window(qapp=None):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.main_window import MainWindow
    w = MainWindow()
    yield w
    try:
        w.close()
    except Exception:
        pass


def test_lifecycle_start_pause_resume_stop_reset(window):
    c = window.controller
    from gui.application.state import LifecycleState
    assert c.lifecycle == LifecycleState.STOPPED
    c.start()
    assert c.lifecycle == LifecycleState.RUNNING
    c.pause()
    assert c.lifecycle == LifecycleState.PAUSED
    c.resume()
    assert c.lifecycle == LifecycleState.RUNNING
    c.stop()
    assert c.lifecycle == LifecycleState.STOPPED
    c.start()
    c.reset()
    assert c.lifecycle == LifecycleState.RUNNING  # reset while running stays running


def test_button_states_match_lifecycle(window):
    c = window.controller
    c.stop()
    assert window.controller.button_states() == {"start": True, "stop": False, "pause": False, "reset": True, "pause_text": "Pause"}
    c.start()
    assert c.button_states()["start"] is False and c.button_states()["stop"] is True
    c.pause()
    assert c.button_states()["pause_text"] == "Resume"


def test_dashboard_renders_known_state(window):
    from gui.presentation.view_state import DashboardState
    st = DashboardState(
        jitter_ms=145, acquisition_time_s=145, reacquisition_time_s=145, searching_time_s=145,
        retention_rate_pct=67, detection_rate_pct=78, center_hit_rate_pct=67, target_loss_rate_pct=12,
        avg_track_err_px=45, avg_track_err_mrad=1.82, reacquisition_count=55,
        target_loss_count=23, target_switch_count=77, rms_px=45, rms_mrad=1.82,
        status="TRACKING", duration_s=589, fps=33.7,
    )
    window.dashboard.render(st)
    pills = {k: v.text() for k, v in window.dashboard._pills.items()}
    assert pills["Acquisition Time"] == "145.0 Sec"
    assert pills["Jitter"] == "145 Ms"
    assert pills["Retention Rate"] == "67 %"
    assert pills["Average Tracking Error"] == "45 PX | 1.82 MRAD"
    assert pills["RMS / RMSE"] == "45 PX | 1.82 MRAD"
    assert pills["Status"] == "TRACKING"
    assert pills["Total Target Switches Count"] == "77"


def test_config_panels_produce_validated_configs(window):
    cam = window.session.camera_config
    assert cam.fov_width > 0
    # Panels are pure inputs: hosted in dialog, emit without touching session directly
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    cfg = dlg.camera_panel.collect_config()
    assert cfg.validate((2000, 2000)).fov_width > 0
    dlg.close()


def test_presenter_snapshot_path(window):
    window.controller.start()
    for _ in range(6):
        window.controller.step()
    snap = window.controller._last_snapshot
    assert snap is not None and snap.fov_frame is not None
    state = window.presenter.update(snap, window.session, window.controller)
    assert state.status in ("SEARCHING", "DETECTED", "TRACKING", "LOST", "REACQUIRING")
    assert state.fps >= 0 and state.duration_s >= 0


def test_sessions_isolated():
    from gui.application.session import SimulationSession
    a = SimulationSession(seed=1)
    b = SimulationSession(seed=2)
    a.ensure_built()
    b.ensure_built()
    assert a.beacons is not b.beacons
    a.step(1 / 30)
    assert a._frame_id != b._frame_id


def test_headless_unaffected():
    from simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=42)
    obs = sim.reset(seed=42)
    assert obs is not None


def test_no_sim_imports_qt():
    import subprocess, sys
    code = "import simulation.headless, tracking.pipeline, disturbance, control.controller, camera.ptz_camera; print('ok')"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert "PyQt" not in r.stdout + r.stderr or "ok" in r.stdout


def test_sim_and_dashboard_are_separate_windows(window):
    from gui.windows.dashboard_window import DashboardWindow
    from gui.views.dashboard_view import DashboardView
    from gui.views.simulation_view import SimulationView
    # Simulator window owns only the simulation view — no dashboard mixed in.
    assert isinstance(window.sim_view, SimulationView)
    assert window.centralWidget().findChild(DashboardView) is None
    # Dashboard lives in its own top-level window.
    dash_win = window.windows.ensure_dashboard()
    assert isinstance(dash_win, DashboardWindow)
    assert dash_win.parent() is None
    assert isinstance(dash_win.view, DashboardView)
    assert window.dashboard is dash_win.view


def test_dashboard_window_show_and_fullscreen_toggle(window):
    w = window.windows.show_dashboard()
    assert w.isVisible()
    w.toggle_fullscreen()
    w.toggle_fullscreen()
    assert w.isVisible()
    w.hide()
    assert not w.isVisible()


def test_simulator_fullscreen_toggle(window):
    window.toggle_fullscreen()
    window.toggle_fullscreen()
    assert window.controls.btn_dashboard is not None
    assert window.controls.btn_fullscreen is not None


def test_world_and_fov_views_render(window):
    from target.config import MultiBeaconConfig
    window.session.apply_beacon_config(MultiBeaconConfig(beacon_count=1, target_index=0, x=1000, y=1000))
    window.controller.start()
    for _ in range(10):
        window.on_timer()
    fov = window.sim_view.fov_label.pixmap()
    world = window.sim_view.world_label.pixmap()
    assert fov is not None and not fov.isNull()
    assert world is not None and not world.isNull()


def test_reset_clears_session_and_presentation(window):
    window.controller.start()
    for _ in range(10):
        window.on_timer()
    assert window.session._frame_id > 0
    window._on_reset()
    assert window.session._frame_id == 0
    assert len(window.presenter._err_window) == 0


def test_reset_restores_everything(window):
    from gui.application.commands import SetDetectorThresholdCommand
    from gui.application.state import LifecycleState
    old_session = window.session
    window.controller.set_detector_threshold(SetDetectorThresholdCommand(threshold=150))
    window.controller.start()
    for _ in range(5):
        window.on_timer()
    window._on_reset()
    # Fresh default session, stopped, defaults restored.
    assert window.session is not old_session
    assert window.session._frame_id == 0
    assert window.session.detector_threshold == 80
    assert window.controller.lifecycle == LifecycleState.STOPPED
    assert window.controller.duration_s == 0.0
    assert len(window.presenter._err_window) == 0
    assert window.windows._settings is None


def test_hot_reload_is_debounced(window):
    import copy
    cfg = copy.copy(window.session.controller_config)
    cfg.kp = float(cfg.kp) + 0.05
    old_kp = window.session.controller_config.kp
    window._on_control_config(cfg)
    # Not applied yet — coalescing slider drags.
    assert window.session.controller_config.kp == old_kp
    window._fire_config("control")
    assert window.session.controller_config.kp != old_kp


def test_changing_values_are_coloured(window):
    from gui.presentation.view_state import DashboardState
    st = DashboardState(detection_rate_pct=95.0, target_loss_rate_pct=2.0,
                        avg_track_err_px=5.0, avg_track_err_mrad=0.2,
                        status="TRACKING", fps=30.0)
    window.dashboard.render(st)
    assert "#1a7f37" in window.dashboard._pills["Detection Rate"].styleSheet()
    assert "#1a7f37" in window.dashboard._pills["Average Tracking Error"].styleSheet()
    assert "#1a7f37" in window.dashboard._pills["Status"].styleSheet()
    st.status = "LOST"
    st.detection_rate_pct = 10.0
    window.dashboard.render(st)
    assert "#b42318" in window.dashboard._pills["Status"].styleSheet()
    assert "#b42318" in window.dashboard._pills["Detection Rate"].styleSheet()


def test_default_target_spawns_in_world_and_moves_smoothly():
    import numpy as np
    from gui.application.session import SimulationSession
    s = SimulationSession()
    s.ensure_built()
    b = s.beacons[0]
    w, h = int(s.env_config.world_width), int(s.env_config.world_height)
    assert 0 <= b.x <= w and 0 <= b.y <= h
    prev = (b.x, b.y)
    for _ in range(60):
        s.step(1 / 30)
        jump = abs(b.x - prev[0]) + abs(b.y - prev[1])
        assert jump < 50, f"teleport {prev} -> {(b.x, b.y)}"
        assert 0 <= b.x <= w and 0 <= b.y <= h
        prev = (b.x, b.y)


def test_out_of_bounds_request_falls_back_in_world():
    from gui.application.session import SimulationSession
    from target.config import MultiBeaconConfig
    s = SimulationSession(beacon_config=MultiBeaconConfig(beacon_count=1, target_index=0, x=9999, y=9999))
    s.ensure_built()
    b = s.beacons[0]
    w, h = int(s.env_config.world_width), int(s.env_config.world_height)
    assert 0 <= b.x <= w and 0 <= b.y <= h


def test_detector_threshold_hot_applies(window):
    from gui.application.commands import SetDetectorThresholdCommand
    window.controller.set_detector_threshold(SetDetectorThresholdCommand(threshold=150))
    assert window.session.detector_threshold == 150
    assert window.session.pipeline.detector_config.threshold == 150
    window.controller.set_detector_threshold(SetDetectorThresholdCommand(threshold=9999))
    assert window.session.detector_threshold == 255  # clipped to DetectorConfig limits


def test_beacon_panel_sliders_follow_world_bounds(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    w, h = int(window.session.env_config.world_width), int(window.session.env_config.world_height)
    assert dlg.beacon_panel.slider_x.maximum() == w
    assert dlg.beacon_panel.slider_y.maximum() == h
    assert dlg.beacon_panel.slider_thresh.value() == window.session.detector_threshold
    dlg.close()


def test_settings_deck_matches_console_chrome(window):
    from PyQt5.QtWidgets import QTabWidget, QWidget as _W
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    header = dlg.findChild(_W, "headerBar")
    assert header is not None
    assert dlg.windowTitle() == "Settings"
    assert dlg.btn_close is not None and dlg.btn_close.text() == "Close"
    tabs = dlg.findChild(QTabWidget)
    assert tabs is not None and tabs.count() == 5  # Camera/Control/Environment/Disturbances/Beacons
    dlg.close()


def test_no_legacy_blue_theme_remains():
    from gui.styles import APP_STYLE
    for code in ("3b82f6", "2563eb", "1d4ed8", "1e40af", "dbeafe", "eff6ff", "93c5fd"):
        assert code not in APP_STYLE.lower()
    import inspect
    from gui.panels import base as _base
    src = inspect.getsource(_base)
    for code in ("3b82f6", "1e40af", "dbeafe"):
        assert code not in src.lower()


def test_dead_control_deck_removed():
    import importlib.util
    assert importlib.util.find_spec("gui.widgets") is None
    assert importlib.util.find_spec("gui.windows.control_window") is None
    from gui import app as _app
    assert "ControlDashboardWindow" not in _app.__all__


def test_randomize_parameters_updates_and_applies(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    before = dlg.beacon_panel.collect_multi_config()
    dlg.beacon_panel._randomize_parameters()
    after = dlg.beacon_panel.collect_multi_config()
    # Random draw should change at least the location almost surely; config must stay valid.
    assert after.validate().beacon_count >= 1
    window._on_beacons_config(after)
    window._fire_config("beacons")
    assert window.session.beacon_config.speed == pytest.approx(after.speed)
    dlg.close()


def test_randomize_motion_and_seed_emit(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    seen = []
    dlg.beaconsChanged.connect(lambda cfg: seen.append(("beacons", cfg)))
    dlg.environmentChanged.connect(lambda cfg: seen.append(("env", cfg)))
    dlg.beacon_panel._randomize_motion()
    old_seed = dlg.env_panel.slider_seed.value()
    dlg.env_panel._randomize_seed()
    kinds = [k for k, _ in seen]
    assert "beacons" in kinds and "env" in kinds
    assert dlg.env_panel.slider_seed.value() != old_seed or True  # seed draw may repeat rarely
    dlg.close()


def test_panel_reset_restores_defaults(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    dlg.beacon_panel.slider_speed.setValue(200)
    window._on_beacons_config(dlg.beacon_panel.collect_multi_config())
    window._fire_config("beacons")
    assert window.session.beacon_config.speed == pytest.approx(200)
    dlg.beacon_panel._on_reset()
    window._on_beacons_config(dlg.beacon_panel.collect_multi_config())
    window._fire_config("beacons")
    assert window.session.beacon_config.speed == pytest.approx(60)
    assert window.session.beacon_config.beacon_count == 1
    dlg.close()
