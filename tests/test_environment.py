import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
import cv2
from environment.scene import Scene
from environment.config import EnvironmentConfig
from environment.haze import build_haze_field
from environment.vignetting import apply_vignetting, clear_vignetting_cache


def test_scene_build_haze_none():
    rng = np.random.default_rng(42)
    h = build_haze_field(2000, 2000, rng, 0.0)
    assert h is None  # M4 fix: 0 haze no allocation


def test_scene_haze_applied():
    cfg = EnvironmentConfig(world_width=800, world_height=600, haze_pct=50, star_count=10).validate()
    sc = Scene(config=cfg)
    assert sc._haze_base is not None
    assert sc._base_no_stars is not None


def test_get_region_edge_clamping():
    sc = Scene(800, 600, seed=1)
    # FOV partially outside world
    r = sc.get_region(-50, -50, 150, 100)
    assert r.shape == (150, 200, 3)
    # fully outside
    r2 = sc.get_region(1000, 1000, 1200, 1150)
    assert r2.shape == (150, 200, 3)
    assert np.all(r2 == 0)
    # zero/negative size
    r3 = sc.get_region(100, 100, 100, 100)
    assert r3.shape[0] >= 1 and r3.shape[1] >= 1


def test_get_region_vs_get_frame_consistency():
    sc = Scene(500, 500, seed=42, star_count=50)
    x0, y0, x1, y1 = 100, 100, 200, 200
    region = sc.get_region(x0, y0, x1, y1)
    full = sc.get_frame()
    assert np.array_equal(region, full[y0:y1, x0:x1])


def test_vignetting_cache():
    clear_vignetting_cache()
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    out1 = apply_vignetting(frame.copy(), 0.3)
    out2 = apply_vignetting(frame.copy(), 0.3)
    assert np.array_equal(out1, out2)
    # 0 strength fast path
    out0 = apply_vignetting(frame.copy(), 0.0)
    assert np.array_equal(out0, frame)


def test_world_config_limits():
    cfg = EnvironmentConfig(world_width=1000, world_height=1000).validate()
    assert cfg.world_width == 2000  # clipped to min 2000
    cfg2 = EnvironmentConfig(world_width=6000, world_height=6000).validate()
    assert cfg2.world_width == 5000


def test_starfield_determinism():
    from environment.stars import generate_starfield
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    d1 = generate_starfield(500, 500, rng1, 100, 1.0)
    d2 = generate_starfield(500, 500, rng2, 100, 1.0)
    assert np.array_equal(d1["xy"], d2["xy"])
    assert np.array_equal(d1["brightness"], d2["brightness"])


@pytest.mark.parametrize("w,h", [(2000, 2000), (3000, 2000), (5000, 5000)])
def test_parametric_world_sizes(w, h):
    cfg = EnvironmentConfig(world_width=w, world_height=h, star_count=20).validate()
    sc = Scene(config=cfg)
    assert sc.width == w and sc.height == h
    # get_region at center
    r = sc.get_region(w//2 - 50, h//2 - 50, w//2 + 50, h//2 + 50)
    assert r.shape == (100, 100, 3)
