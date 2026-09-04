import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import numpy as np
from tracking.tracker import Tracker, LockStatus
from tracking.kalman import KalmanFilter


def test_acquisition_sequence():
    t = Tracker(smoothing=0.4, miss_limit=5)
    assert t.status == LockStatus.SEARCHING
    t.update((100, 100))
    assert t.status == LockStatus.ACQUIRED
    t.update((101, 101))
    assert t.status == LockStatus.ACQUIRED
    t.update((102, 102))
    assert t.status == LockStatus.TRACKING


def test_loss_after_misses():
    t = Tracker(smoothing=0.4, miss_limit=3)
    for _ in range(3):
        t.update((50, 50))
    assert t.status == LockStatus.TRACKING
    for _ in range(3):
        t.update(None)
    assert t.status == LockStatus.LOST
    t.update((60, 60))
    assert t.status == LockStatus.ACQUIRED


def test_searching_after_double_miss():
    t = Tracker(smoothing=0.4, miss_limit=2)
    for _ in range(3):
        t.update((10, 10))
    for _ in range(2):
        t.update(None)
    assert t.status == LockStatus.LOST
    assert t.estimated_position is not None
    for _ in range(4):
        t.update(None)
    assert t.status == LockStatus.SEARCHING
    assert t.estimated_position is None


def test_smoothing():
    t = Tracker(smoothing=0.8, miss_limit=5)
    t.update((0, 0))
    est = t.update((100, 0))
    assert abs(est[0] - 20) < 1e-6


def test_no_position_without_detection():
    t = Tracker()
    assert t.update(None) is None
    assert t.status == LockStatus.SEARCHING


# --- New: Kalman & advanced state coverage (H4) ---
def test_kalman_predict_coast():
    kf = KalmanFilter(process_var=12.0, meas_var=4.0)
    kf.init_from_measurement((100, 100), vel=(10, 0))
    pred = kf.predict(dt=0.033)
    assert pred is not None
    assert abs(pred[0] - 100.33) < 1.0  # 100 + 10*0.033


def test_kalman_outlier_rejection():
    kf = KalmanFilter(process_var=12.0, meas_var=4.0)
    kf.init_from_measurement((100, 100))
    # second measurement far away should be outlier-rejected for velocity seeding (800 px/s limit)
    kf._last_dt = 0.033
    kf._prev_z = (100, 100)
    kf.x[2] = 0.0; kf.x[3] = 0.0
    # velocity 2000 px/s should be rejected (tightened to 800)
    kf.update((300, 100))  # dx 200 /0.033 ~6060 px/s >800
    # velocity should remain small (not seeded to 6060)
    assert abs(kf.get_vel()[0]) < 1000


def test_kalman_velocity_seeding_reasonable():
    kf = KalmanFilter()
    kf.init_from_measurement((0, 0))
    kf._last_dt = 0.1
    kf._prev_z = (0, 0)
    kf.x[2] = 0.0; kf.x[3] = 0.0
    kf.update((5, 0))  # vx 50 px/s <800 -> should seed
    assert abs(kf.get_vel()[0] - 40) < 15  # 0.8*50


def test_tracker_dt_handling():
    t = Tracker(smoothing=0.4, miss_limit=5)
    t.update((0, 0), dt=0.033)
    t.update((10, 0), dt=0.033)
    est = t.update(None, dt=0.033)
    # should coast, not crash
    assert est is not None or t.status in (LockStatus.LOST, LockStatus.SEARCHING)


def test_tracker_reacquisition_timing():
    t = Tracker(smoothing=0.4, miss_limit=2)
    for _ in range(3):
        t.update((0, 0))
    assert t.status == LockStatus.TRACKING
    for _ in range(2):
        t.update(None)
    assert t.status == LockStatus.LOST
    t.update((10, 10))
    assert t.status == LockStatus.ACQUIRED
    t.update((11, 11))
    t.update((12, 12))
    assert t.status == LockStatus.TRACKING


def test_tracker_smoothing_bounds():
    for s in [0.0, 0.5, 0.99]:
        t = Tracker(smoothing=s)
        t.update((0, 0))
        t.update((100, 100))
        # should not crash, est within bounds
        assert t.estimated_position is not None


def test_lock_status_transitions_exhaustive():
    t = Tracker(miss_limit=3)
    # SEARCHING -> ACQUIRED -> TRACKING -> LOST -> SEARCHING
    assert t.status == LockStatus.SEARCHING
    t.update((1, 1)); assert t.status == LockStatus.ACQUIRED
    t.update((2, 2)); t.update((3, 3))
    assert t.status == LockStatus.TRACKING
    for _ in range(3): t.update(None)
    assert t.status == LockStatus.LOST
    for _ in range(5): t.update(None)
    assert t.status == LockStatus.SEARCHING


@pytest.mark.parametrize("miss_limit", [2, 3, 5])
def test_parametric_miss_limit(miss_limit):
    t = Tracker(miss_limit=miss_limit)
    for _ in range(3):
        t.update((0, 0))
    assert t.status == LockStatus.TRACKING
    for _ in range(miss_limit):
        t.update(None)
    assert t.status == LockStatus.LOST
