import sys
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

import numpy as np
import cv2
from disturbance import disturbances as dist

def test_sensor_noise_identity():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    out = dist.apply_sensor_noise(frame, 0)
    assert np.array_equal(frame, out)

def test_turbulence_identity():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    out = dist.apply_turbulence(frame, 0)
    assert np.array_equal(frame, out)

def test_vibration_identity():
    assert dist.apply_platform_vibration(100, 200, 0) == (100, 200)

def test_camera_motion_identity():
    assert dist.apply_camera_motion(100, 200, 0) == (100, 200)

def test_camera_motion_with_state():
    state = {}
    p1 = dist.apply_camera_motion_with_state(400, 300, 5, state)
    assert "vx" in state and "vy" in state
    p2 = dist.apply_camera_motion_with_state(p1[0], p1[1], 5, state)
    # Should not crash and should drift gradually
    assert isinstance(p2[0], float)

def test_noise_does_not_overflow():
    frame = np.full((20, 20, 3), 250, dtype=np.uint8)
    out = dist.apply_sensor_noise(frame, 10)
    assert out.dtype == np.uint8
    assert out.max() <= 255 and out.min() >= 0

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all disturbance tests passed")