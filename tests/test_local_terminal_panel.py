# tests/test_local_terminal_panel.py - UI tests for LocalTerminalPanel and Control Deck integration
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")


@pytest.fixture()
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_local_terminal_panel_builds_and_collects(qapp):
    from gui.panels.local_terminal_panel import LocalTerminalPanel
    from local_terminal.config import LocalTerminalConfig

    panel = LocalTerminalPanel()
    cfg = panel.collect_config()
    assert isinstance(cfg, LocalTerminalConfig)
    assert cfg.camera.resolution_width == 640
    assert cfg.camera.resolution_height == 480
    assert abs(cfg.camera.fov_x - 4.0) < 1e-3

    # Adjust FOV and verify dynamic angular model labels
    panel.fov_w_slider.setValue(1280)
    panel.fov_h_slider.setValue(960)
    panel.fov_x_slider.setValue(80)  # 8.0 deg
    panel._update_derived_angular_labels()

    cfg_updated = panel.collect_config()
    assert cfg_updated.camera.resolution_width == 1280
    assert abs(cfg_updated.camera.fov_x - 8.0) < 1e-3
    assert "µrad/px" in panel.lbl_ang_x.text()

    # Modify operations settings
    panel.combo_acq_pattern.setCurrentText("SPIRAL")
    panel.combo_trk_mode.setCurrentText("AUTO")
    panel.det_wl_slider.setValue(int(1550 * panel.det_wl_factor))

    cfg_ops = panel.collect_config()
    assert cfg_ops.acquisition.search_pattern == "SPIRAL"
    assert cfg_ops.tracking.mode == "AUTO"
    assert cfg_ops.detection.wavelength == 1550.0

    # Live telemetry update
    panel.update_telemetry({
        "state": {
            "power_state": "ON",
            "operational_state": "ACTIVE",
            "ptz_state": "MOVING",
            "acquisition_state": "ACQUIRED",
            "detection_state": "TARGET_CONFIRMED",
            "tracking_state": "TRACKING",
            "link_state": "CONNECTED",
        },
        "detection": {"confidence": 0.95},
        "tracking": {"error_px": (1.2, -0.8), "error_urad": (130.9, -87.3)},
        "communication": {"link_state": "CONNECTED"},
    })

    assert "ACTIVE" in panel.badge_op.text()
    assert "ACQUIRED" in panel.badge_acq.text()
    assert "TARGET_CONFIRMED" in panel.badge_det.text()
    assert "CONNECTED" in panel.badge_link.text()
    assert panel.prog_confidence.value() == 95
    assert "Δx = +1.2 px" in panel.lbl_trk_offsets.text()

    panel.close()


def test_control_deck_dialog_hosts_local_terminal(qapp):
    from gui.application.session import SimulationSession
    from gui.views.settings_dialog import SettingsDialog

    session = SimulationSession()
    session.ensure_built()
    dlg = SettingsDialog(session)

    # Check tabs
    assert dlg.tabs.count() == 4
    assert dlg.tabs.tabText(0) == "Remote Terminal"
    assert dlg.tabs.tabText(1) == "Local Terminal"
    assert dlg.tabs.tabText(2) == "Environment"
    assert dlg.tabs.tabText(3) == "Disturbances"

    # Verify panels are present and wired
    assert hasattr(dlg, "local_terminal_panel")
    assert hasattr(dlg, "camera_panel")
    assert hasattr(dlg, "remote_terminal_panel")
    assert dlg.remote_terminal_panel is dlg.terminal_panel

    # Verify uniform get_config() works on all panels
    cfg_lt = dlg.local_terminal_panel.get_config()
    cfg_rt = dlg.remote_terminal_panel.get_config()
    cfg_env = dlg.env_panel.get_config()
    cfg_dist = dlg.dist_panel.get_config()
    assert cfg_lt is not None
    assert cfg_rt is not None
    assert cfg_env is not None
    assert cfg_dist is not None

    # Fullscreen toggle
    dlg.toggle_fullscreen()
    assert dlg._fullscreen is True
    assert dlg.btn_fullscreen.text() == "Exit Full Screen"

    dlg.toggle_fullscreen()
    assert dlg._fullscreen is False
    assert dlg.btn_fullscreen.text() == "Full Screen"

    # Sync from session (must complete cleanly without exceptions)
    dlg.sync_from_session(session)
    dlg.close()


def test_local_terminal_randomize_and_accordion(qapp):
    from gui.panels.local_terminal_panel import LocalTerminalPanel

    panel = LocalTerminalPanel()
    # Check default state: advanced container is collapsed
    assert panel._advanced_visible is False
    assert "Click to Expand" in panel.btn_toggle_advanced.text()

    # Toggle to expand
    panel.toggle_advanced()
    assert panel._advanced_visible is True
    assert "Click to Collapse" in panel.btn_toggle_advanced.text()

    # Toggle to collapse
    panel.toggle_advanced()
    assert panel._advanced_visible is False

    # Test randomize button and method
    changed_events = []
    panel.configChanged.connect(lambda cfg: changed_events.append(cfg))

    panel.btn_randomize_local.click()
    assert len(changed_events) == 1
    new_cfg = changed_events[0]
    assert new_cfg.acquisition.search_pattern in ["SPIRAL", "RASTER", "RANDOM", "FIGURE_8", "SECTOR", "GRID"]
    assert new_cfg.tracking.algorithm in ["CENTROID", "PEAK", "KALMAN"]
    assert new_cfg.ptz.pan_speed > 0
    panel.close()

