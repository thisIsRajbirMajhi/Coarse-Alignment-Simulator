import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest
from beacon_tracker.detection.detector import BeaconDetector
from beacon_tracker.detection.config import DetectorConfig
from disturbance import disturbances as dist


@pytest.fixture
def detector():
    return BeaconDetector(brightness_threshold=200, min_area=2)


def _beacon_frame(pos=(100, 75), r=5, bg=15, brightness=255, shape=(150, 200)):
    h, w = shape
    frame = np.full((h, w, 3), bg, dtype=np.uint8)
    cv2.circle(frame, pos, r, (brightness, brightness, brightness), -1)
    return frame


def test_clean_detection(detector):
    frame = _beacon_frame()
    pos = detector.detect(frame)
    assert pos is not None, "should detect bright beacon"
    assert abs(pos[0] - 100) < 1.5 and abs(pos[1] - 75) < 1.5, f"centroid off {pos}"


def test_dim_beacon_not_detected():
    det = BeaconDetector(brightness_threshold=200)
    frame = _beacon_frame(brightness=150)
    assert det.detect(frame) is None


def test_empty_frame():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    assert det.detect(frame) is None
    assert det.detect_all(frame) == []


def test_largest_contour_wins():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (50, 50), 3, (255, 255, 255), -1)
    cv2.circle(frame, (150, 100), 7, (255, 255, 255), -1)
    pos = det.detect(frame)
    assert pos is not None
    assert abs(pos[0] - 150) < 2 and abs(pos[1] - 100) < 2


def test_noise_resilience(detector):
    frame = _beacon_frame()
    noisy = dist.apply_sensor_noise(frame, intensity=5)
    pos = detector.detect(noisy)
    assert pos is not None, "moderate noise should not break detection"


def test_turbulence_no_crash(detector):
    frame = _beacon_frame()
    turb = dist.apply_turbulence(frame, intensity=8)
    # must not crash — result may be None or detected
    detector.detect(turb)


# --- New: validation & edge cases (H3) ---
def test_none_frame_returns_empty():
    det = BeaconDetector()
    assert det.detect_all(None) == []
    assert det.detect(None) is None


def test_zero_size_frame():
    det = BeaconDetector()
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert det.detect_all(empty) == []


def test_one_channel_grayscale():
    det = BeaconDetector(brightness_threshold=200)
    gray = np.full((100, 100), 15, dtype=np.uint8)
    cv2.circle(gray, (50, 50), 5, 255, -1)
    # to_grayscale handles both 2D and 3D
    pos = det.detect(gray)
    # may detect if preprocessing supports 2D, or empty if not — must not crash
    assert pos is None or isinstance(pos, tuple)


def test_h_w_1_channel_frame():
    det = BeaconDetector()
    frame = np.full((100, 100, 1), 15, dtype=np.uint8)
    # should not crash, may return [] or handle reshape
    assert isinstance(det.detect_all(frame), list)


def test_min_area_filters_small_blob():
    det_small = BeaconDetector(brightness_threshold=200, min_area=50)
    frame = _beacon_frame(r=2)  # area ~12 <50
    assert det_small.detect(frame) is None
    det_large = BeaconDetector(brightness_threshold=200, min_area=2)
    assert det_large.detect(frame) is not None


def test_max_beacons_cap():
    det = BeaconDetector(brightness_threshold=150, min_area=2)
    frame = np.full((200, 200, 3), 15, dtype=np.uint8)
    for cx in [30, 70, 110, 150, 190]:
        cv2.circle(frame, (cx, 100), 6, (255, 255, 255), -1)
    all_dets = det.detect_all(frame, max_beacons=2)
    assert len(all_dets) <= 2
    all_dets3 = det.detect_all(frame, max_beacons=10)
    # config max_beacons default 12, so should get all 5
    assert 4 <= len(all_dets3) <= 5


def test_confidence_sorting():
    det = BeaconDetector(brightness_threshold=150)
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (50, 50), 3, (220, 220, 220), -1)
    cv2.circle(frame, (150, 50), 6, (255, 255, 255), -1)
    dets = det.detect_all(frame)
    assert len(dets) >= 2
    assert dets[0]["confidence"] >= dets[1]["confidence"]


def test_config_validation():
    cfg = DetectorConfig(brightness_threshold=500, min_area=1000).validate()
    # should clip to limits (0..255, 1..50)
    assert 0 <= cfg.brightness_threshold <= 255
    assert 1 <= cfg.min_area <= 50


def test_detect_with_hitbox_convenience():
    det = BeaconDetector()
    frame = _beacon_frame()
    res = det.detect_with_hitbox(frame, hitbox_radius=14)
    assert res is not None
    assert "pos" in res and "hitbox_radius" in res
    assert res["hitbox_radius"] == 14


@pytest.mark.parametrize("bg,bright", [(0, 255), (15, 255), (50, 200)])
def test_parametric_contrast(bg, bright):
    det = BeaconDetector(brightness_threshold=180)
    frame = np.full((100, 100, 3), bg, dtype=np.uint8)
    cv2.circle(frame, (50, 50), 5, (bright, bright, bright), -1)
    # higher contrast should be more reliably detected
    if bright - bg > 100:
        assert det.detect(frame) is not None
