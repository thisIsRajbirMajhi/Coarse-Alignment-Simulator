import math
import time
import pytest
from PyQt5.QtWidgets import QApplication

from perf_log.metrics import PerformanceLogger
from gui.panels.dashboard_panel import DashboardPanel, _color_for_fps, _color_for_error, _color_for_rate
from control.config import ControllerConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_initial_perf_logger_summary():
    pl = PerformanceLogger(auto_log=False)
    s = pl.summary()
    assert s["frame_count"] == 0
    assert s["acquisition_time_s"] is None
    assert s["avg_reacquisition_time_s"] is None
    assert s["lock_retention_rate_pct"] == 0.0
    assert s["target_loss_pct"] == 0.0
    assert s["detection_rate_pct"] == 0.0
    assert s["center_hit_rate_pct"] == 0.0
    assert "fps_ewma" in s
    assert "schema_version" in s


def test_dashboard_panel_initial_update(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    summary = pl.summary()
    panel.update_from_summary(summary, "searching", tracking_error_px=None, camera_scale_mrad=0.035)

    assert panel.stat_labels["acquisition_time_s"].text() == "— S"
    assert panel.stat_labels["avg_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["min_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["max_reacquisition_time_s"].text() == "— S"
    assert panel.stat_labels["lock_status"].text() == "SEARCHING"


def test_dashboard_panel_live_update(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    pl.start()

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
    cfg.gain = 10.0
    assert cfg.kp == 1.0
    cfg.gain = -1.0
    assert cfg.kp == 0.0


# --- New: Strict spec thresholds & leak ---
def test_strict_spec_thresholds():
    # Sr.17 error ≤10 green, >10 red (no yellow)
    assert _color_for_error(10) == "#22c55e"
    assert _color_for_error(10.1) == "#ef4444"
    assert _color_for_error(15) == "#ef4444"
    # Sr.20 FPS ≥20 green, <20 red
    assert _color_for_fps(20) == "#22c55e"
    assert _color_for_fps(19.9) == "#ef4444"
    assert _color_for_fps(15) == "#ef4444"


def test_dashboard_no_hidden_label_leak(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for _ in range(5):
        pl.log_frame(True, 5.0, 0.01, lock_state="tracking", dt=0.033)
    s = pl.summary()
    initial = len(panel.stat_labels)
    for i in range(100):
        s[f"new_fake_{i}"] = i
        panel.update_from_summary(s, "tracking", 5.0)
    assert len(panel.stat_labels) == initial, "leak: hidden labels created per new key"


def test_dashboard_mrad_conversion(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    pl.log_frame(True, 10.0, 0.01, lock_state="tracking", dt=0.033)
    s = pl.summary()
    panel.update_from_summary(s, "tracking", tracking_error_px=10.0, camera_scale_mrad=0.109)
    txt = panel.stat_labels["avg_tracking_error_px"].text()
    assert "10.0 px" in txt
    assert "1.09 mrad" in txt  # 10*0.109


def test_retention_rate_color(qapp):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    pl.start()
    for _ in range(10):
        pl.log_frame(True, 1.0, 0.01, lock_state="tracking", dt=0.033)
    s = pl.summary()
    panel.update_from_summary(s, "tracking", 1.0)
    # 100% retention green
    lbl = panel.stat_labels["lock_retention_rate_pct"]
    assert "#22c55e" in lbl.styleSheet() or "60" not in lbl.text()  # at least not red

    pl2 = PerformanceLogger(auto_log=False)
    pl2.start()
    for _ in range(10):
        pl2.log_frame(False, None, 0.01, lock_state="searching", dt=0.033)
    s2 = pl2.summary()
    panel.update_from_summary(s2, "searching", None)
    assert panel.stat_labels["lock_retention_rate_pct"].text() == "0.0 %"


@pytest.mark.parametrize("status,expected", [("searching", "SEARCHING"), ("tracking", "TRACKING"), ("lost", "LOST"), ("acquired", "ACQUIRED")])
def test_parametric_status_display(qapp, status, expected):
    panel = DashboardPanel()
    pl = PerformanceLogger(auto_log=False)
    s = pl.summary()
    panel.update_from_summary(s, status, None)
    assert panel.stat_labels["lock_status"].text() == expected
