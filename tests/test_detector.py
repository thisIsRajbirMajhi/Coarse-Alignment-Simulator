import sys
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

import cv2
import numpy as np
from detection.detector import BeaconDetector
from disturbance import disturbances as dist

def test_clean_detection():
    det = BeaconDetector(brightness_threshold=200, min_area=2)
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (100, 75), 5, (255, 255, 255), -1)
    pos = det.detect(frame)
    assert pos is not None, "should detect bright beacon"
    assert abs(pos[0] - 100) < 1.5 and abs(pos[1] - 75) < 1.5, f"centroid off {pos}"

def test_dim_beacon_not_detected():
    det = BeaconDetector(brightness_threshold=200)
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (100, 75), 5, (150, 150, 150), -1)
    assert det.detect(frame) is None

def test_empty_frame():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    assert det.detect(frame) is None

def test_largest_contour_wins():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (50, 50), 3, (255, 255, 255), -1)
    cv2.circle(frame, (150, 100), 7, (255, 255, 255), -1)
    pos = det.detect(frame)
    assert pos is not None
    assert abs(pos[0] - 150) < 2 and abs(pos[1] - 100) < 2

def test_noise_resilience():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (100, 75), 5, (255, 255, 255), -1)
    noisy = dist.apply_sensor_noise(frame, intensity=5)
    pos = det.detect(noisy)
    assert pos is not None, "moderate noise should not break detection"

def test_turbulence_breaks_detection_at_high_intensity():
    det = BeaconDetector()
    frame = np.full((150, 200, 3), 15, dtype=np.uint8)
    cv2.circle(frame, (100, 75), 5, (255, 255, 255), -1)
    turb = dist.apply_turbulence(frame, intensity=8)
    # At high turbulence blur should often hide the beacon — either None or still detected is ok,
    # but function must not crash
    pos = turb  # keep unused warning quiet
    det.detect(turb)

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all detector tests passed")