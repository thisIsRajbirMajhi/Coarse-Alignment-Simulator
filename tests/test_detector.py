"""beacon_tracker removed: verify module is not importable and system still runs without it."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


def test_beacon_tracker_removed():
    with pytest.raises(ModuleNotFoundError):
        import beacon_tracker  # noqa
    with pytest.raises(ModuleNotFoundError):
        from beacon_tracker.detection.detector import BeaconDetector  # noqa


def test_beacon_tracker_detection_removed():
    with pytest.raises(ModuleNotFoundError):
        from beacon_tracker.detection.config import DetectorConfig  # noqa


def test_headless_without_beacon_tracker():
    from simulation.headless import HeadlessSimulation
    sim = HeadlessSimulation(seed=42)
    obs, reward, terminated, truncated, info = sim.step()
    assert "frame" in obs
    assert "estimate" in obs
    assert obs["estimate"] is None
    assert obs["lock_status"] == "searching"
    assert info["all_detections"] == []


def test_env_without_beacon_tracker():
    from simulation.env import FSOCEnv
    env = FSOCEnv(seed=42)
    obs, info = env.reset(seed=42)
    assert "image" in obs
    assert "vector" in obs
    assert "lock" in obs
    obs2, reward, term, trunc, info2 = env.step([0, 0])
    assert reward == -1.0
