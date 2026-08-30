import sys
sys.path.insert(0, r"C:\Users\mrajb\OneDrive\Desktop\FSOC Simulator")

import cv2
import numpy as np
from camera.ptz_camera import PTZCamera
from environment.scene import Scene


def test_corner_crop_no_crash():
    scene = Scene(800, 600, seed=1)
    cam = PTZCamera(fov_width=200, fov_height=150, pan=100, tilt=75, scene_bounds=(800, 600))
    assert cam.get_fov_rect() == (0, 0, 200, 150)
    frame = scene.get_frame()
    cv2.circle(frame, (10, 10), 5, (255, 255, 255), -1)
    fov = cam.capture(frame)
    assert fov.shape == (150, 200, 3)
    # beacon at (10,10) should appear at (10,10) in fov
    assert fov[10, 10, 0] == 255


def test_clamped_move():
    cam = PTZCamera(fov_width=200, fov_height=150, pan=700, tilt=525, scene_bounds=(800, 600))
    cam.move(1000, 1000)
    assert cam.pan == 700 and cam.tilt == 525
    cam.move(-10000, -10000)
    assert cam.pan == 100 and cam.tilt == 75


def test_opposite_corner():
    cam = PTZCamera(fov_width=200, fov_height=150, pan=700, tilt=525, scene_bounds=(800, 600))
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    frame[590, 790] = (255, 255, 255)
    fov = cam.capture(frame)
    # bright pixel at bottom-right of scene should be near bottom-right of fov
    # fov covers 600..800 x 450..600, so scene (790,590) -> fov (190,140)
    assert fov[140, 190, 0] == 255


def test_set_position():
    cam = PTZCamera(fov_width=200, fov_height=150, pan=400, tilt=300, scene_bounds=(800, 600))
    cam.set_position(0, 0)
    assert cam.pan == 100 and cam.tilt == 75
    cam.set_position(800, 600)
    assert cam.pan == 700 and cam.tilt == 525


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"pass {name}")
    print("all camera tests passed")
