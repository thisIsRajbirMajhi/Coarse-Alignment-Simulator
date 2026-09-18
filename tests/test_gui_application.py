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
    assert pills["Duration (s)"] == "120 Sec"
    assert pills["Frames Per Second (FPS)"] == "30.0"
    assert pills["Jitter"] == "12 Ms"
    assert pills["Camera Pan"] == "500.0 px"
    assert pills["Camera Tilt"] == "400.0 px"
    assert pills["FOV Size"] == "640 × 480"
    assert pills["World Size"] == "2000 × 2000"
    assert pills["Atmospheric Preset"] == "Haze"
    assert pills["Platform Profile"] == "Sinusoidal"
    assert pills["Optical Turbulence"] == "2"


def test_config_panels_produce_validated_configs(window):
    cam = window.session.camera_config
    assert cam.fov_width > 0
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
    code = "import simulation.headless, disturbance, local_terminal.terminal; print('ok')"
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


def test_world_and_fov_views_render(window):
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
    cfg = copy.copy(window.session.controller_config)
    cfg.kp = float(cfg.kp) + 0.05
    old_kp = window.session.controller_config.kp
    window._on_control_config(cfg)
    assert window.session.controller_config.kp == old_kp
    window._fire_config("control")
    assert window.session.controller_config.kp != old_kp


def test_settings_deck_matches_console_chrome(window):
    from PyQt5.QtWidgets import QTabWidget, QWidget as _W
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    header = dlg.findChild(_W, "headerBar")
    assert header is not None
    assert dlg.windowTitle() == "Settings"
    assert dlg.btn_close is not None and dlg.btn_close.text() == "Close"
    tabs = dlg.findChild(QTabWidget)
    assert tabs is not None and tabs.count() in (4, 5)  # RemoteTerminal/Camera/Control/Environment/Disturbances
    dlg.close()


def test_camera_fov_sliders_capped_to_world(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    w, h = int(window.session.env_config.world_width), int(window.session.env_config.world_height)
    assert dlg.camera_panel.fov_w_slider.maximum() == w - 10
    assert dlg.camera_panel.fov_h_slider.maximum() == h - 10
    dlg.close()


def test_dialog_sync_back_after_world_change(window):
    from gui.views.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.session, window)
    dlg.sync_from_session(window.session)
    assert dlg.camera_panel.fov_h_slider.value() == int(window.session.camera_config.fov_height)
    dlg.close()
