# tests/test_gui_camera.py - Unit and integration tests for Camera and Controller GUI panels and FOV window.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")

from PyQt5.QtWidgets import QApplication

from camera.config import CameraConfig, PIDConfig
from gui.panels.camera_panel import CameraPanel
from gui.panels.controller_panel import ControllerPanel
from gui.windows.fov_window import FOVWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_camera_panel_collect_and_set(app):
    """Test CameraPanel controls collection and configuration updates."""
    panel = CameraPanel()
    cfg = panel.collect_config()
    assert isinstance(cfg, CameraConfig)
    assert cfg.resolution_w == 640
    assert cfg.resolution_h == 480
    assert cfg.fov_deg_h == 4.0

    # Set new config
    new_cfg = CameraConfig(fov_deg_h=6.0, max_pan_speed_deg_s=8.0).validate()
    panel.set_config(new_cfg)
    collected = panel.collect_config()
    assert abs(collected.fov_deg_h - 6.0) < 0.1
    assert abs(collected.max_pan_speed_deg_s - 8.0) < 0.1


def test_controller_panel_collect_and_set(app):
    """Test ControllerPanel controls collection and configuration updates."""
    panel = ControllerPanel()
    cfg = panel.collect_config()
    assert isinstance(cfg, PIDConfig)
    assert cfg.kp_pan == 1.5
    assert cfg.tau == 0.02

    # Set new config
    new_cfg = PIDConfig(kp_pan=3.0, tau=0.015, mode="MANUAL").validate()
    panel.set_config(new_cfg)
    collected = panel.collect_config()
    assert abs(collected.kp_pan - 3.0) < 0.05
    assert abs(collected.tau - 0.015) < 0.005
    assert collected.mode == "MANUAL"


def test_fov_window_render(app):
    """Test FOVWindow creation and snapshot rendering."""
    import numpy as np
    from gui.application.session import FrameSnapshot

    win = FOVWindow()
    assert win.fov_label.width() == 640
    assert win.fov_label.height() == 480

    # Render a dummy snapshot
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    snap = FrameSnapshot(
        frame_id=1,
        world_frame=np.zeros((2000, 2000, 3), dtype=np.uint8),
        world_size=(2000, 2000),
        fov_frame=frame,
        camera_telemetry={"ptz": {"pan_deg": 1.25, "tilt_deg": -0.5}},
        pid_telemetry={"error_pan_px": 2.0, "error_tilt_px": 1.0, "mode": "AUTO", "active": True},
    )

    win.render_snapshot(snap)
    assert "Pan: +1.25° | Tilt: -0.50°" in win.lbl_pan_tilt.text()
    assert win.lbl_mode.text() == "AUTO"
    win.close()


def test_main_window_has_fov_button(app):
    """Test that MainWindow has the Camera FOV button and WindowManager can open FOV window."""
    from gui.main_window import MainWindow

    win = MainWindow()
    assert hasattr(win.controls, "btn_fov")
    assert win.controls.btn_fov.text() == "Camera FOV"

    # Test WindowManager ensure_fov and show_fov
    fov_win = win.windows.ensure_fov()
    assert fov_win is not None
    assert isinstance(fov_win, FOVWindow)

    win.windows.show_fov()
    assert win.windows.fov_window is not None

    win.close()


def test_disturbances_panel_vibration_and_drift_round_trip(app):
    """Regression: vibration/drift must be settable (were hardcoded 0)."""
    from disturbance.core.config import DisturbanceConfig
    from gui.panels.disturbances_panel import DisturbancesPanel

    panel = DisturbancesPanel()
    panel.slider_vibration.setValue(45)
    panel.slider_cam_drift.setValue(30)
    cfg = panel.collect_config()
    assert cfg.vibration == pytest.approx(4.5)
    assert cfg.camera_motion == pytest.approx(3.0)

    panel.set_config(DisturbanceConfig(vibration=4.5, camera_motion=3.0).validate())
    assert panel.slider_vibration.value() == 45
    assert panel.slider_cam_drift.value() == 30
    # Hidden legacy sliders stay synced for back-compat readers.
    assert panel.sliders["Vibration"].value() == 4
    assert panel.sliders["Camera Motion"].value() == 3
