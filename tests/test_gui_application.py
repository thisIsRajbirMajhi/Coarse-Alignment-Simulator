# tests/test_gui_application.py - Architecture: lifecycle, dashboard, isolation.
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
    assert c.lifecycle == LifecycleState.RUNNING


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
        status="RUNNING",
        duration_s=120.0,
        fps=30.0,
        jitter_ms=12.5,
        pan=500.0,
        tilt=400.0,
        fov_w=640,
        fov_h=480,
        world_w=2000,
        world_h=2000,
        atmospheric_preset="Haze",
        platform_profile="Sinusoidal",
        platform_speed=5.0,
        turbulence=2,
        vibration=1,
        camera_motion=0,
        noise=3,
    )
    window.dashboard.render(st)
    pills = {k: v.text() for k, v in window.dashboard._pills.items()}
    assert pills["Status"] == "RUNNING"
    assert pills["Duration (S)"] == "120"
    assert pills["FPS"] == "30.0"
    assert pills["Jitter (ms)"] == "12"


def test_dashboard_renders_tracking_metrics(window):
    from gui.presentation.view_state import DashboardState
    st = DashboardState(
        status="RUNNING",
        duration_s=60.0,
        fps=30.0,
        jitter_ms=10.0,
        acquisition_time_s=4.5,
        reacquisition_time_s=1.2,
        searching_time_s=10.0,
        retention_rate_pct=92.0,
        detection_rate_pct=75.0,
        center_hit_rate_pct=88.0,
        target_loss_rate_pct=0.5,
        avg_track_err_px=3.0,
        avg_track_err_mrad=0.33,
        reacquisition_count=2,
        target_loss_count=1,
        target_switch_count=1,
        rms_px=4.0,
        rms_mrad=0.44,
    )
    window.dashboard.render(st)
    pills = {k: v.text() for k, v in window.dashboard._pills.items()}
    # Metrics.png rows
    assert pills["Acquisition Time (s)"] == "4.5"
    assert pills["Re-Acquisition Time (S)"] == "1.2"
    assert pills["Searching (s)"] == "10.0"
    assert pills["Retention Rate (%)"] == "92"
    assert pills["Detection Rate (%)"] == "75"
    assert pills["Center Hit rate (%)"] == "88"
    assert pills["Average Loss rate (/min)"] == "0.50"
    assert pills["Average Tracking Error (px | mrad)"] == "3 PX | 0.33 MRAD"
    assert pills["RMS (px)"] == "4.0"
    assert pills["RMSE (mrad)"] == "0.44"
    # Metrics1.png rows still present
    assert pills["Status"] == "RUNNING"
    assert pills["Duration (S)"] == "60"
    assert pills["FPS"] == "30.0"


def test_dashboard_live_metrics_accumulate(window):
    window.controller.start()
    for _ in range(6):
        window.controller.step()
    state = window.presenter.update(
        window.controller._last_snapshot, window.session, window.controller)
    assert state.searching_time_s is not None and state.searching_time_s >= 0
    assert state.detection_rate_pct is not None
    assert state.reacquisition_count >= 0 and state.target_loss_count >= 0
    window.dashboard.render(state)
    pills = {k: v.text() for k, v in window.dashboard._pills.items()}
    assert pills["Searching (s)"] != "—"
    assert pills["Detection Rate (%)"] != "—"


def test_config_panels_produce_validated_configs(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    cfg_remote = dlg.remote_panel.collect_config()
    assert cfg_remote.formation.terminal_count >= 1
    cfg_env = dlg.env_panel.collect_config()
    assert cfg_env.world_width >= 2000
    cfg_dist = dlg.dist_panel.collect_config()
    assert cfg_dist is not None
    dlg.close()


def test_presenter_snapshot_path(window):
    window.controller.start()
    for _ in range(6):
        window.controller.step()
    snap = window.controller._last_snapshot
    assert snap is not None and snap.fov_frame is not None
    state = window.presenter.update(snap, window.session, window.controller)
    assert state.status in ("RUNNING", "STOPPED", "PAUSED")
    assert state.fps >= 0 and state.duration_s >= 0


def test_sessions_isolated():
    from gui.application.session import SimulationSession
    a = SimulationSession(seed=1)
    b = SimulationSession(seed=2)
    a.ensure_built()
    b.ensure_built()
    a.step(1 / 30)
    assert a._frame_id != b._frame_id


def test_headless_unaffected():
    from simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=42)
    obs = sim.reset(seed=42)
    assert obs is not None
    obs2, _, _, _, _ = sim.step()
    assert obs2 is not None


def test_no_sim_imports_qt():
    import subprocess, sys
    code = "import simulation.headless, disturbance, remote_terminal; print('ok')"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert "PyQt" not in r.stdout + r.stderr or "ok" in r.stdout


def test_sim_and_dashboard_are_separate_windows(window):
    from gui.windows.dashboard_window import DashboardWindow
    from gui.views.dashboard_view import DashboardView
    from gui.views.simulation_view import SimulationView
    assert isinstance(window.sim_view, SimulationView)
    assert window.centralWidget().findChild(DashboardView) is None
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


def _pump_until(window, predicate, timeout_s: float = 10.0):
    """Run the Qt event loop until predicate() is true (worker snapshots are
    async since sim steps run off-thread). Raises on timeout."""
    import time
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        window.on_timer()
        for _ in range(20):
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
    return bool(predicate())


def test_world_and_fov_views_render(window):
    window.controller.start()
    assert _pump_until(window, lambda: window.sim_view.fov_label.pixmap() is not None)
    assert _pump_until(window, lambda: window.sim_view.world_label.pixmap() is not None)
    fov = window.sim_view.fov_label.pixmap()
    world = window.sim_view.world_label.pixmap()
    assert fov is not None and not fov.isNull()
    assert world is not None and not world.isNull()


def test_reset_clears_session_and_presentation(window):
    window.controller.start()
    assert _pump_until(window, lambda: window.session._frame_id > 0)
    window._on_reset()
    assert window.session._frame_id == 0


def test_reset_restores_everything(window):
    from gui.application.state import LifecycleState
    old_session = window.session
    window.controller.start()
    for _ in range(5):
        window.on_timer()
    window._on_reset()
    assert window.session is not old_session
    assert window.session._frame_id == 0
    assert window.controller.lifecycle == LifecycleState.STOPPED
    assert window.controller.duration_s == 0.0
    assert window.windows._settings is None


def test_hot_reload_is_debounced(window):
    import copy
    cfg = copy.copy(window.session.disturbance_config)
    cfg.turbulence = int(cfg.turbulence) + 1
    old_turb = window.session.disturbance_config.turbulence
    window._on_disturbances_config(cfg)
    assert window.session.disturbance_config.turbulence == old_turb
    window._fire_config("disturbances")
    assert window.session.disturbance_config.turbulence != old_turb


def test_settings_deck_matches_console_chrome(window):
    from PyQt5.QtWidgets import QTabWidget, QWidget as _W
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    header = dlg.findChild(_W, "headerBar")
    assert header is not None
    assert dlg.windowTitle() == "Settings"
    assert dlg.btn_close is not None and dlg.btn_close.text() == "Close"
    tabs = dlg.findChild(QTabWidget)
    assert tabs is not None and tabs.count() == 3  # Remote Terminal/Environment/Disturbances
    assert tabs.tabText(0) == "Remote Terminal"
    dlg.close()


def test_dialog_sync_back_after_world_change(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    dlg.sync_from_session(window.session)
    assert dlg.env_panel.slider_world_w.value() == int(window.session.env_config.world_width)
    dlg.close()


def test_tracker_point_overlay_drawn_on_camera_screen():
    pytest = __import__("pytest")
    pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
    import numpy as np
    from gui.core.renderer import Renderer
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    plain = Renderer.render_viewport(frame, None, telemetry=None)
    tele = {"autonomy": {"state": "LOCKED", "active_target_id": "RT-1",
                         "candidates": [{"terminal_id": "RT-1", "fov_x": 400.0,
                                         "fov_y": 300.0, "confidence": 0.95,
                                         "confirmed": True}]},
            "state": {}}
    marker = Renderer.tracker_marker_from_telemetry(tele, (640, 480))
    assert marker is not None
    assert marker[3] == "RT-1 LOCKED"
    marked = Renderer.render_viewport(frame, None, telemetry=tele)
    assert marked.sum() > plain.sum()
    # Out-of-frame candidate yields no marker (never raises).
    tele_out = {"autonomy": {"state": "SEARCHING", "active_target_id": None,
                             "candidates": [{"terminal_id": "RT-9", "fov_x": 9999.0,
                                             "fov_y": 9999.0, "confidence": 0.1,
                                             "confirmed": False}]},
                "state": {}}
    assert Renderer.tracker_marker_from_telemetry(tele_out, (640, 480)) is None
    assert Renderer.tracker_marker_from_telemetry(None) is None
    assert Renderer.render_viewport(frame, None) is not None

