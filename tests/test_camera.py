# tests/test_camera.py - Comprehensive unit tests for PTZ Camera kinematics and FOV extraction.
import numpy as np
import pytest

from camera.config import CameraConfig
from camera.constants import CAMERA_DEFAULTS, CAMERA_LIMITS
from camera.ptz import PTZCamera


def test_camera_config_validation():
    """Test CameraConfig default values and limits clamping."""
    cfg = CameraConfig().validate()
    assert cfg.resolution_w == 640
    assert cfg.resolution_h == 480
    assert cfg.fov_deg_h == 4.0
    assert cfg.fov_deg_v == 3.0
    assert cfg.max_pan_speed_deg_s == 5.0
    assert cfg.max_tilt_speed_deg_s == 5.0

    # Test out-of-limits clamping
    bad_cfg = CameraConfig(
        fov_deg_h=100.0,
        max_pan_speed_deg_s=50.0,
        max_tilt_speed_deg_s=0.1,
    ).validate()
    assert bad_cfg.fov_deg_h == CAMERA_LIMITS["fov_deg_h"][1]
    assert bad_cfg.max_pan_speed_deg_s == CAMERA_LIMITS["max_pan_speed_deg_s"][1]
    assert bad_cfg.max_tilt_speed_deg_s == CAMERA_LIMITS["max_tilt_speed_deg_s"][0]


def test_camera_optical_properties():
    """Test angular and pixel scale properties."""
    cfg = CameraConfig(fov_deg_h=4.0, fov_deg_v=3.0, resolution_w=640, resolution_h=480)
    assert cfg.deg_per_px_h == 4.0 / 640.0
    assert cfg.deg_per_px_v == 3.0 / 480.0
    assert cfg.px_per_deg_h == 640.0 / 4.0
    assert cfg.px_per_deg_v == 480.0 / 3.0


def test_camera_initialization_and_home():
    """Test PTZCamera initial state and home position."""
    cam = PTZCamera(world_size=(2000, 2000))
    home_x, home_y = cam.get_home()
    assert home_x == 1000.0
    assert home_y == 1000.0

    cx, cy = cam.get_fov_center_world()
    assert cx == 1000.0
    assert cy == 1000.0

    x0, y0, x1, y1 = cam.get_fov_rect()
    assert x0 == 1000.0 - 320.0
    assert y0 == 1000.0 - 240.0
    assert x1 == 1000.0 + 320.0
    assert y1 == 1000.0 + 240.0


def test_camera_kinematics_velocity_limit():
    """Test that gimbal velocity cannot exceed max_pan_speed_deg_s."""
    cfg = CameraConfig(max_pan_speed_deg_s=5.0, max_pan_accel_deg_s2=50.0)
    cam = PTZCamera(config=cfg)

    # Command high velocity (20 deg/s)
    cam.update(dt=0.5, cmd_pan_vel=20.0, cmd_tilt_vel=0.0)
    st = cam.get_state()
    assert abs(st.pan_vel_deg_s) <= 5.0 + 1e-4


def test_camera_kinematics_accel_limit():
    """Test that gimbal acceleration limits rate of velocity change."""
    cfg = CameraConfig(max_pan_speed_deg_s=10.0, max_pan_accel_deg_s2=10.0)
    cam = PTZCamera(config=cfg)

    # In 0.1s, maximum velocity increase should be max_accel * dt = 1.0 deg/s
    cam.update(dt=0.1, cmd_pan_vel=10.0, cmd_tilt_vel=0.0)
    st = cam.get_state()
    assert st.pan_vel_deg_s <= 1.0 + 1e-3


def test_camera_travel_limits():
    """Test that pan/tilt angles are clamped to travel limits."""
    cfg = CameraConfig(pan_min_deg=-45.0, pan_max_deg=45.0, max_pan_speed_deg_s=10.0, max_pan_accel_deg_s2=50.0)
    cam = PTZCamera(config=cfg)

    # Run for 10 seconds at max speed
    for _ in range(100):
        cam.update(dt=0.1, cmd_pan_vel=10.0, cmd_tilt_vel=0.0)

    st = cam.get_state()
    assert st.pan_deg <= 45.0
    assert st.in_limits


def test_camera_encoder_quantization_and_noise():
    """Test optical encoder quantization and measurement noise."""
    cfg = CameraConfig(encoder_bits=16, encoder_noise_deg=0.001)
    cam = PTZCamera(config=cfg)
    cam.pan_deg = 10.12345
    cam.tilt_deg = 5.67890

    meas_pan, meas_tilt = cam.get_measured_angles()
    # Measured should be close to true angle within a few noise sigmas
    assert abs(meas_pan - cam.pan_deg) < 0.01
    assert abs(meas_tilt - cam.tilt_deg) < 0.01


def test_camera_fov_extraction_monochrome():
    """Test FOV viewport extraction produces strictly monochrome 640x480 frame."""
    cam = PTZCamera(world_size=(2000, 2000))
    # Create colored world frame (2000x2000x3)
    world = np.zeros((2000, 2000, 3), dtype=np.uint8)
    world[:, :, 0] = 50   # Blue
    world[:, :, 1] = 120  # Green
    world[:, :, 2] = 200  # Red

    fov = cam.extract_fov(world)
    assert fov.shape == (480, 640, 3)

    # Strict monochrome test: R == G == B on every pixel
    diff_rg = np.abs(fov[:, :, 0].astype(int) - fov[:, :, 1].astype(int))
    diff_gb = np.abs(fov[:, :, 1].astype(int) - fov[:, :, 2].astype(int))
    assert np.max(diff_rg) == 0
    assert np.max(diff_gb) == 0

    # Test raw 1-channel monochrome
    raw = cam.raw_monochrome
    assert raw is not None
    assert raw.shape == (480, 640)


def test_camera_fov_bounded_inside_world():
    """Test that camera FOV rectangle is always strictly bounded inside world scene."""
    cam = PTZCamera(world_size=(2000, 2000))
    # Command extreme pan and tilt angles
    for pan in [-90.0, -45.0, 0.0, 45.0, 90.0]:
        for tilt in [-45.0, 0.0, 45.0]:
            cam.pan_deg = pan
            cam.tilt_deg = tilt
            x0, y0, x1, y1 = cam.get_fov_rect()
            assert x0 >= 0.0 - 1e-4
            assert y0 >= 0.0 - 1e-4
            assert x1 <= 2000.0 + 1e-4
            assert y1 <= 2000.0 + 1e-4
            assert abs((x1 - x0) - 640.0) < 1e-4
            assert abs((y1 - y0) - 480.0) < 1e-4


def test_camera_coordinate_transforms():
    """Test world_to_fov and fov_to_world roundtrip."""
    cam = PTZCamera(world_size=(2000, 2000))
    # Optical axis center in world coordinates
    cx, cy = cam.get_fov_center_world()
    fov_x, fov_y = cam.world_to_fov(cx, cy)
    assert abs(fov_x - 320.0) < 1e-4
    assert abs(fov_y - 240.0) < 1e-4

    wx, wy = cam.fov_to_world(fov_x, fov_y)
    assert abs(wx - cx) < 1e-4
    assert abs(wy - cy) < 1e-4


def test_camera_reset_updates_measured_angles():
    """Test that resetting camera immediately updates measured angles cache."""
    cam = PTZCamera(world_size=(2000, 2000))
    cam.reset(pan_deg=2.5, tilt_deg=-1.5)
    meas_p, meas_t = cam.get_measured_angles()
    assert abs(meas_p - 2.5) < 0.05
    assert abs(meas_t - (-1.5)) < 0.05


def test_camera_settled_condition():
    """Test that settled flag requires both low velocity and proximity to target."""
    cam = PTZCamera(world_size=(2000, 2000))
    assert cam.get_state().settled is True

    # Command a distant target
    cam.set_target_angles(pan_deg=3.0, tilt_deg=2.0)
    # Target changed, not settled even if velocity is currently 0
    assert cam.get_state().settled is False

    # Simulate until it reaches target and stops
    for _ in range(100):
        cam.update(dt=0.05)

    st = cam.get_state()
    assert abs(st.pan_deg - 3.0) < 0.05
    assert abs(st.tilt_deg - 2.0) < 0.05
    assert st.settled is True


def test_camera_effective_angular_limits():
    """Test effective angular limits helper."""
    cam = PTZCamera(world_size=(2000, 2000))
    p_min, p_max, t_min, t_max = cam.get_effective_angular_limits()
    # For 2000x2000 world and 640x480 at 160 px/deg:
    # max_pan = (1000 - 320) / 160 = 4.25 deg
    # max_tilt = (1000 - 240) / 160 = 4.75 deg
    assert abs(p_min - (-4.25)) < 1e-3
    assert abs(p_max - 4.25) < 1e-3
    assert abs(t_min - (-4.75)) < 1e-3
    assert abs(t_max - 4.75) < 1e-3


def test_camera_extract_fov_bgra():
    """Test FOV extraction with 4-channel BGRA world frame."""
    cam = PTZCamera(world_size=(2000, 2000))
    world_bgra = np.full((2000, 2000, 4), 180, dtype=np.uint8)
    fov = cam.extract_fov(world_bgra)
    assert fov.shape == (480, 640, 3)
    assert np.all(fov[:, :, 0] == fov[:, :, 1])
    assert np.all(fov[:, :, 1] == fov[:, :, 2])


def test_camera_config_inverted_limits():
    """Test that inverted travel limits in CameraConfig are safely corrected."""
    cfg = CameraConfig(pan_min_deg=45.0, pan_max_deg=-45.0, home_pan_deg=100.0).validate()
    assert cfg.pan_min_deg <= cfg.pan_max_deg
    assert cfg.pan_min_deg <= cfg.home_pan_deg <= cfg.pan_max_deg

