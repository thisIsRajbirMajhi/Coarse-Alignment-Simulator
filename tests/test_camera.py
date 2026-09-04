import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest
from camera.ptz_camera import PTZCamera
from camera.config import CameraConfig
from environment.scene import Scene


def test_corner_crop_no_crash():
    scene = Scene(800, 600, seed=1)
    cam = PTZCamera(fov_width=200, fov_height=150, pan=100, tilt=75, scene_bounds=(800, 600))
    assert cam.get_fov_rect() == (0, 0, 200, 150)
    frame = scene.get_frame()
    cv2.circle(frame, (10, 10), 5, (255, 255, 255), -1)
    fov = cam.capture(frame)
    assert fov.shape == (150, 200, 3)
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
    assert fov[140, 190, 0] == 255


def test_set_position():
    cam = PTZCamera(fov_width=200, fov_height=150, pan=400, tilt=300, scene_bounds=(800, 600))
    cam.set_position(0, 0)
    assert cam.pan == 100 and cam.tilt == 75
    cam.set_position(800, 600)
    assert cam.pan == 700 and cam.tilt == 525


# --- New: PTZ mechanics (H2, Sr.13-14) ---
def test_slew_limit():
    cfg = CameraConfig(fov_width=200, fov_height=150, max_pan_speed_deg=5.0, max_tilt_speed_deg=5.0).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    # request large delta with small dt -> should be slew-limited
    cam.move(1000, 0, dt=0.033)
    # max pan 5 deg/s ~ 5*17.45/0.109 ≈ 800 px/s => 26 px per 0.033s
    assert abs(cam.pan - 400) < 50


def test_quantize():
    cfg = CameraConfig(fov_width=200, fov_height=150, resolution=0.5).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    cam.move(0.6, 0.6, dt=0.033)
    # quantized to 0.5 steps -> pan should be 400.5 or 401.0
    assert cam.pan % 0.5 < 1e-6


def test_latency_queue_with_dt():
    cfg = CameraConfig(fov_width=200, fov_height=150, latency_ms=100).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    cam.move(50, 0, dt=0.033)
    assert cam.pan == 400  # queued, not yet applied
    cam.update(dt=0.05)
    assert cam.pan == 400  # still pending (100ms)
    cam.update(dt=0.06)
    assert cam.pan != 400  # now executed


def test_latency_queue_stores_dt():
    cfg = CameraConfig(fov_width=200, fov_height=150, latency_ms=50).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    cam.move(100, 0, dt=0.01)  # small dt -> small slew
    cam.update(dt=0.06)
    pan_after = cam.pan
    # slew limited by stored dt 0.01, not current 0.06
    assert pan_after < 410


def test_flush_pending():
    cfg = CameraConfig(fov_width=200, fov_height=150, latency_ms=100).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    cam.move(30, 20, dt=0.033)
    cam.flush_pending()
    assert cam.pan != 400


def test_capture_region_optimized():
    scene = Scene(800, 600, seed=42)
    cfg = CameraConfig(fov_width=100, fov_height=100).validate((800, 600))
    cam = PTZCamera(config=cfg, scene_bounds=(800, 600))
    cam.set_position(400, 300)
    # capture_region should not require full frame rebuild
    region = cam.capture_region(scene)
    assert region.shape == (100, 100, 3)
    # compare with capture(get_frame) — should be similar (allow vignetting diff)
    full = scene.get_frame()
    via_full = cam.capture(full)
    # both have same star pattern (within tolerance)
    assert region.shape == via_full.shape


def test_fov_clamped_to_scene():
    cfg = CameraConfig(fov_width=5000, fov_height=5000).validate((2000, 2000))
    # config now clamps FOV to scene-10 (1990) per fix camera/config.py:112
    assert cfg.fov_width == 1990
    assert cfg.fov_height == 1990
    assert cfg.pan_min <= cfg.pan_max
    assert cfg.pan_min == 995  # hw=995


def test_pixel_scale_consistency():
    cfg = CameraConfig(fov_width=640, fov_height=480, fov_deg_x=4.0, fov_deg_y=3.0).validate((2000, 2000))
    # both axes 0.109
    assert abs(cfg.pixel_scale_mrad - 0.109) < 0.005
    assert hasattr(cfg, "pixel_scale_mrad_y")


@pytest.mark.parametrize("fov", [(100, 100), (640, 480), (1000, 1000)])
def test_parametric_fov(fov):
    w, h = fov
    scene = Scene(2000, 2000, seed=1)
    cfg = CameraConfig(fov_width=w, fov_height=h).validate((2000, 2000))
    cam = PTZCamera(config=cfg, scene_bounds=(2000, 2000))
    cam.set_position(1000, 1000)
    r = cam.get_fov_rect()
    assert r[2] - r[0] == w
    assert r[3] - r[1] == h
