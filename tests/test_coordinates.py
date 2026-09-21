# tests/test_coordinates.py - Unit tests for coordinate systems and transforms (Fixes.md §6.3).
from __future__ import annotations

import pytest

from common.coordinates import (
    FovPoint,
    PtzAngles,
    WorldPoint,
    angles_to_world_center,
    fov_to_angles,
    fov_to_world,
    world_center_to_angles,
    world_to_fov,
)


def test_fov_world_round_trip():
    fov_rect = (680.0, 760.0, 1320.0, 1240.0)  # 640x480 rect centered at (1000, 1000)
    wpt = WorldPoint(1000.0, 1000.0)
    fpt = world_to_fov(wpt, fov_rect)
    assert fpt.x == pytest.approx(320.0)
    assert fpt.y == pytest.approx(240.0)

    wpt_back = fov_to_world(fpt, fov_rect)
    assert wpt_back.x == pytest.approx(wpt.x)
    assert wpt_back.y == pytest.approx(wpt.y)


def test_angles_world_round_trip():
    cam_home = WorldPoint(1000.0, 1000.0)
    px_per_deg = (160.0, 160.0)
    angles = PtzAngles(1.5, -0.75)
    
    wpt = angles_to_world_center(angles, cam_home, px_per_deg)
    # cx = 1000 + 1.5 * 160 = 1240
    # cy = 1000 - (-0.75) * 160 = 1120
    assert wpt.x == pytest.approx(1240.0)
    assert wpt.y == pytest.approx(1120.0)

    angles_back = world_center_to_angles(wpt, cam_home, px_per_deg)
    assert angles_back.pan_deg == pytest.approx(angles.pan_deg)
    assert angles_back.tilt_deg == pytest.approx(angles.tilt_deg)


def test_fov_to_angles_centering():
    cam_angles = PtzAngles(0.0, 0.0)
    px_per_deg = (160.0, 160.0)
    # Target is at (400, 160) in FOV (dx = +80px, dy = -80px)
    fpt = FovPoint(400.0, 160.0)
    target_angles = fov_to_angles(fpt, cam_angles, px_per_deg, fov_size=(640, 480))
    
    # delta_pan = +80 / 160 = +0.5 deg
    # delta_tilt = -(-80) / 160 = +0.5 deg
    assert target_angles.pan_deg == pytest.approx(0.5)
    assert target_angles.tilt_deg == pytest.approx(0.5)


def test_boundary_points():
    fov_rect = (0.0, 0.0, 640.0, 480.0)
    corner_world = WorldPoint(640.0, 480.0)
    corner_fov = world_to_fov(corner_world, fov_rect)
    assert corner_fov.x == pytest.approx(640.0)
    assert corner_fov.y == pytest.approx(480.0)
