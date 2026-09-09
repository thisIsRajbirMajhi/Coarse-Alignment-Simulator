"""Tracking stack present: Kalman + state machine + closed-loop pipeline."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


def test_tracking_module_present():
    from tracking.kalman import KalmanTracker
    from tracking.state_machine import AcquisitionStateMachine
    from tracking.pipeline import TrackingPipeline
    tr = KalmanTracker()
    tr.step((100, 100))
    assert tr.initialized
    sm = AcquisitionStateMachine()
    assert sm.step(False) == "searching"


def test_beacon_tracker_fully_removed():
    with pytest.raises(ModuleNotFoundError):
        import beacon_tracker  # noqa
    with pytest.raises(ModuleNotFoundError):
        from beacon_tracker.detection.detector import BeaconDetector  # noqa
    with pytest.raises(ModuleNotFoundError):
        import beacon_tracker.search.scanner  # noqa


def test_headless_without_beacon_tracker_and_tracking():
    from simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=42)
    obs, reward, terminated, truncated, info = sim.step()
    assert "estimate" in obs
    assert obs["estimate"] is None
    assert obs["lock_status"] == "searching"
    assert info["all_detections"] == []
    assert reward == -1.0


def test_env_without_beacon_tracker():
    from simulation.env import FSOCEnv
    env = FSOCEnv(seed=42)
    obs, info = env.reset(seed=42)
    assert obs["lock"] == 0
    obs2, reward, _, _, _ = env.step([0, 0])
    assert "image" in obs2


def test_search_pattern_moves_and_reverses_pan():
    from tracking.search import SearchPattern

    search = SearchPattern(pan_speed=100.0, row_step=40.0)
    positions = [(50.0, 50.0)]
    for _ in range(20):
        pan, tilt = search.step(positions[-1][0], positions[-1][1], (0.0, 100.0), (0.0, 100.0), 0.5)
        positions.append((pan, tilt))

    pans = [pan for pan, _ in positions]
    assert max(pans) == 100.0
    assert min(pans) == 0.0
    assert any(a > b for a, b in zip(pans, pans[1:]))
