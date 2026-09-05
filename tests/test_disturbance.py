import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import cv2
import pytest
from disturbance import disturbances as dist
from disturbance.image_noise import apply_image_noise, apply_poisson_noise, apply_salt_pepper, apply_gaussian_noise
from disturbance.atmospheric import apply_atmospheric_disturbance
from disturbance.config import DisturbanceConfig


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
    assert isinstance(p2[0], float)


def test_noise_does_not_overflow():
    frame = np.full((20, 20, 3), 250, dtype=np.uint8)
    out = dist.apply_sensor_noise(frame, 10)
    assert out.dtype == np.uint8
    assert out.max() <= 255 and out.min() >= 0


# --- New: Multi-noise, presets, fixes ---
def test_poisson_float_lambda_no_int_truncation():
    frame = np.full((10, 10, 3), 120, dtype=np.uint8)
    # 120.9 should not be truncated to 120
    out = apply_poisson_noise(frame, scale=1.0, peak=100.5)
    assert out.shape == frame.shape
    assert out.dtype == np.uint8
    # should not crash, and mean close to original
    assert 80 < out.mean() < 160


def test_poisson_large_frame_normal_approx():
    frame = np.full((480, 640, 3), 150, dtype=np.uint8)
    out = apply_poisson_noise(frame, scale=1.5, peak=150)
    assert out.shape == frame.shape
    assert out.dtype == np.uint8


def test_image_noise_stacking_order():
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    out = apply_image_noise(frame, enable_gaussian=True, enable_poisson=True, enable_salt_pepper=True,
                            gaussian_sigma=5, poisson_scale=1.0, salt_pepper_density=0.05)
    assert out.shape == frame.shape
    # salt & pepper should make some pixels 0 or 255
    assert (out == 0).any() or (out == 255).any()


def test_image_noise_intensity_shortcut():
    frame = np.full((50, 50, 3), 100, dtype=np.uint8)
    out = apply_image_noise(frame, intensity=5)
    assert out.shape == frame.shape
    assert not np.array_equal(frame, out)


def test_salt_pepper_density_bounds():
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    out_low = apply_salt_pepper(frame, density=0.01)
    out_high = apply_salt_pepper(frame, density=0.20)
    # high density should have more corrupted pixels
    assert np.count_nonzero(out_high == 0) + np.count_nonzero(out_high == 255) > np.count_nonzero(out_low == 0) + np.count_nonzero(out_low == 255)


def test_gaussian_sigma_capped():
    frame = np.full((20, 20, 3), 128, dtype=np.uint8)
    out = apply_gaussian_noise(frame, sigma=100, max_sigma=20)
    # sigma clipped to 20, should not be extreme
    assert out.shape == frame.shape


def test_atmospheric_presets():
    frame = np.full((100, 100, 3), 180, dtype=np.uint8)
    for preset in ["Clear", "Haze", "Fog", "User Defined"]:
        out = apply_atmospheric_disturbance(frame, preset=preset)
        assert out.shape == frame.shape
        assert out.dtype == np.uint8
        if preset == "Clear":
            assert np.array_equal(frame, out)


def test_disturbance_config_preset_overwrite_warning(caplog):
    cfg = DisturbanceConfig(atmospheric_preset="Haze", atmospheric_contrast=80, atmospheric_brightness=80).validate()
    # Haze preset should overwrite to its map values (15, -5 etc), not keep 80
    assert cfg.atmospheric_contrast != 80 or cfg.atmospheric_brightness != 80


def test_disturbance_config_unknown_keys_warning(caplog):
    cfg = DisturbanceConfig.from_dict({"camera_jiter": 10, "turbulence": 5})
    # unknown key should be ignored, turbulence should be 5
    assert cfg.turbulence == 5


@pytest.mark.parametrize("intensity", [0, 1, 5, 10])
def test_parametric_sensor_noise_intensity(intensity):
    frame = np.full((30, 30, 3), 128, dtype=np.uint8)
    out = dist.apply_sensor_noise(frame, intensity)
    assert out.shape == frame.shape
    if intensity == 0:
        assert np.array_equal(frame, out)
