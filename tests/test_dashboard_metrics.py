import math
import time
import pytest
from PyQt5.QtWidgets import QApplication

from perf_log.metrics import PerformanceLogger
from gui.panels.dashboard_panel import DashboardPanel
from control.config import ControllerConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_initial_perf_logger_summary():
    pl = PerformanceLogger()
    s = pl.summary()
    assert s["frame_count"] == 0
    assert s["acquisition_time_s"] is None
    assert s["avg_reacquisition_time_s"] is None
    assert s["lock_retention_rate_pct"] == 0.0
    assert s["target_loss_pct"] == 0.0
    assert s["detection_rate_pct"] == 0.0
    assert s["center_hit_rate_pct"] == 0.0


def test_dashboard_panel_initial_update(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger()
    summary = pl.summary()
    panel.update_from_summary(summary, "searching", tracking_error_px=None, camera_scale_mrad=0.035)

    # Acquisition and Reacquisition should display "— S", not "0.00 S"
    assert panel.stat_labels["acquisition_time_s"].text() == "— S"
    assert panel.stat_labels["avg_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["min_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["max_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["lock_status"].text() == "SEARCHING"


def test_dashboard_panel_live_update(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger()
    pl.start()

    # Log 10 frames: 6 locked, 4 unlocked
    for i in range(6):
        pl.log_frame(True, 4.0 + i, 0.015, detected=True, hitbox_hit=True, center_hit=(i < 3), lock_state="tracking")
    for i in range(4):
        pl.log_frame(False, None, 0.015, detected=False, hitbox_hit=False, center_hit=False, lock_state="lost")

    summary = pl.summary()
    assert summary["frame_count"] == 10
    assert summary["lock_retention_rate_pct"] == 60.0
    assert summary["target_loss_pct"] == 40.0
    assert summary["detection_rate_pct"] == 60.0
    assert summary["center_hit_rate_pct"] == 30.0
    assert summary["acquisition_time_s"] is not None

    panel.update_from_summary(summary, "tracking", tracking_error_px=5.2, camera_scale_mrad=0.109)

    # Verify formatted output
    assert "S" in panel.stat_labels["acquisition_time_s"].text()
    assert panel.stat_labels["lock_status"].text() == "TRACKING"
    assert "60.0 %" == panel.stat_labels["lock_retention_rate_pct"].text()
    assert "40.0 %" == panel.stat_labels["target_loss_pct"].text()
    assert "px" in panel.stat_labels["avg_tracking_error_px"].text()
    assert "mrad" in panel.stat_labels["avg_tracking_error_px"].text()


def test_controller_config_gain_setter():
    cfg = ControllerConfig(kp=0.15)
    cfg.gain = 0.40
    assert cfg.kp == 0.40
    cfg.gain = 10.0  # Above limit (0.0..1.0)
    assert cfg.kp == 1.0
    cfg.gain = -1.0  # Below limit
    assert cfg.kp == 0.0
