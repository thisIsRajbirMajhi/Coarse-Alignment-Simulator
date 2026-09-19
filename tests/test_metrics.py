# tests/test_metrics.py - Live dashboard tracking metrics (Qt-free).
from __future__ import annotations

import math

from local_terminal.telemetry.metrics import TrackingMetrics


def _tele(acq="SEARCHING", trk="OFF", active=None, cands=0, err=None):
    d: dict = {
        "state": {"acquisition_state": acq, "tracking_state": trk},
        "autonomy": {"active_target_id": active, "candidate_count": cands},
        "tracking": {},
    }
    if err is not None:
        d["tracking"] = {"error_px": (float(err[0]), float(err[1]))}
    return d


def test_empty_snapshot():
    m = TrackingMetrics()
    s = m.snapshot()
    assert s["acquisition_time_s"] is None
    assert s["reacquisition_time_s"] is None
    assert s["retention_rate_pct"] is None
    assert s["detection_rate_pct"] is None
    assert s["center_hit_rate_pct"] is None
    assert s["avg_track_err_px"] is None
    assert s["rms_px"] is None
    assert s["reacquisition_count"] == 0
    assert s["target_loss_count"] == 0
    assert s["target_switch_count"] == 0
    assert s["searching_time_s"] == 0.0


def test_search_then_acquire_flow():
    m = TrackingMetrics()
    dt = 0.1
    for _ in range(5):  # 0.5 s searching, no candidates
        m.update(dt, _tele("SEARCHING", "OFF"))
    assert m.snapshot()["acquisition_time_s"] is None
    assert abs(m.searching_time_s - 0.5) < 1e-9
    for _ in range(5):  # acquired + centered tracking, err 3 px
        m.update(dt, _tele("ACQUIRED", "TRACKING", "BEACON-1", 1, (3.0, 0.0)))
    s = m.snapshot()
    assert s["acquisition_time_s"] is not None
    assert abs(s["acquisition_time_s"] - 0.5) < 1e-9
    assert abs(s["detection_rate_pct"] - 50.0) < 1e-9
    assert abs(s["center_hit_rate_pct"] - 100.0) < 1e-9
    assert abs(s["avg_track_err_px"] - 3.0) < 1e-9
    assert abs(s["rms_px"] - 3.0) < 1e-9
    assert abs(s["retention_rate_pct"] - 100.0) < 1e-9
    assert abs(s["avg_track_err_mrad"] - 3.0 * 0.109083) < 1e-9


def test_reacquire_loss_switch_counts():
    m = TrackingMetrics()
    dt = 0.1
    for _ in range(3):
        m.update(dt, _tele("SEARCHING", "OFF"))
    for _ in range(5):
        m.update(dt, _tele("ACQUIRED", "TRACKING", "BEACON-1", 1, (2.0, 0.0)))
    for _ in range(4):  # live reacquiring episode
        m.update(dt, _tele("ACQUIRED", "REACQUIRING", "BEACON-1", 0))
    assert m.reacquisition_count == 1
    assert abs(m.snapshot()["reacquisition_time_s"] - 0.3) < 1e-9
    for _ in range(3):  # recovered
        m.update(dt, _tele("ACQUIRED", "TRACKING", "BEACON-1", 1, (6.0, 0.0)))
    assert abs(m.snapshot()["reacquisition_time_s"] - 0.4) < 1e-9
    m.update(dt, _tele("SEARCHING", "LOST", None, 0))
    assert m.target_loss_count == 1
    # switch identity: new lock on a different observation
    for _ in range(5):
        m.update(dt, _tele("ACQUIRED", "TRACKING", "BEACON-2", 1, (1.0, 0.0)))
    assert m.target_switch_count == 1
    # retention < 100 after unheld time, loss rate > 0
    assert m.snapshot()["retention_rate_pct"] < 100.0
    assert m.snapshot()["target_loss_rate_per_min"] > 0.0


def test_center_hit_and_rms_math():
    m = TrackingMetrics()
    m.update(0.1, _tele("ACQUIRED", "TRACKING", "B-1", 1, (3.0, 4.0)))  # err 5
    m.update(0.1, _tele("ACQUIRED", "TRACKING", "B-1", 1, (10.0, 0.0)))  # err 10
    s = m.snapshot()
    assert abs(s["center_hit_rate_pct"] - 50.0) < 1e-9
    assert abs(s["avg_track_err_px"] - 7.5) < 1e-9
    assert abs(s["rms_px"] - math.sqrt((25.0 + 100.0) / 2.0)) < 1e-9


def test_reset_clears():
    m = TrackingMetrics()
    m.update(0.1, _tele("ACQUIRED", "TRACKING", "B-1", 1, (1.0, 0.0)))
    m.reset()
    s = m.snapshot()
    assert s["acquisition_time_s"] is None
    assert s["reacquisition_count"] == 0
    assert s["searching_time_s"] == 0.0


def test_presenter_fills_dashboard_state():
    from gui.presentation.simulation_presenter import SimulationPresenter

    class Snap:
        pan = 1000.0
        tilt = 1000.0
        fov_size = (640, 480)
        world_size = (2000, 2000)
        dt = 0.1
        pixel_scale_mrad = 0.109083
        local_terminal = _tele("SEARCHING", "OFF")

    p = SimulationPresenter()
    st = p.update(Snap(), None, None)
    assert st.searching_time_s is not None and st.searching_time_s > 0
    assert st.detection_rate_pct == 0.0
    assert st.reacquisition_count == 0

    class Snap2(Snap):
        local_terminal = _tele("ACQUIRED", "TRACKING", "BEACON-1", 1, (2.0, 0.0))

    st2 = p.update(Snap2(), None, None)
    assert st2.acquisition_time_s is not None
    assert st2.avg_track_err_px == 2.0
    assert st2.rms_px == 2.0
    assert st2.center_hit_rate_pct == 100.0
    p.reset()
    st3 = p.update(Snap(), None, None)
    assert st3.avg_track_err_px is None
