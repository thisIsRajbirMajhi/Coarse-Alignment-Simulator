# common/coordinates.py - Strongly-typed coordinate systems and transformations (Fixes.md §3.1, §3.2, §8.4).
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FovPoint:
    """Point in camera FOV pixel coordinates (0 <= x < fov_w, 0 <= y < fov_h)."""
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass(frozen=True)
class WorldPoint:
    """Point in global simulation world pixel coordinates (0 <= x < world_w, 0 <= y < world_h)."""
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass(frozen=True)
class PtzAngles:
    """PTZ gimbal angles in degrees (pan_deg, tilt_deg)."""
    pan_deg: float
    tilt_deg: float

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.pan_deg), float(self.tilt_deg))


def world_to_fov(world_pt: WorldPoint | tuple[float, float],
                 fov_rect: tuple[float, float, float, float] | Sequence[float]) -> FovPoint:
    """Convert world pixel coordinate to FOV image coordinate.
    
    fov_rect is (x0, y0, x1, y1) in world coordinates.
    """
    wx = float(world_pt.x if isinstance(world_pt, WorldPoint) else world_pt[0])
    wy = float(world_pt.y if isinstance(world_pt, WorldPoint) else world_pt[1])
    x0, y0 = float(fov_rect[0]), float(fov_rect[1])
    return FovPoint(wx - x0, wy - y0)


def fov_to_world(fov_pt: FovPoint | tuple[float, float],
                 fov_rect: tuple[float, float, float, float] | Sequence[float]) -> WorldPoint:
    """Convert FOV image coordinate to world pixel coordinate.
    
    fov_rect is (x0, y0, x1, y1) in world coordinates.
    """
    fx = float(fov_pt.x if isinstance(fov_pt, FovPoint) else fov_pt[0])
    fy = float(fov_pt.y if isinstance(fov_pt, FovPoint) else fov_pt[1])
    x0, y0 = float(fov_rect[0]), float(fov_rect[1])
    return WorldPoint(fx + x0, fy + y0)


def angles_to_world_center(angles: PtzAngles | tuple[float, float],
                           cam_home: WorldPoint | tuple[float, float],
                           px_per_deg: tuple[float, float] | Sequence[float]) -> WorldPoint:
    """Convert gimbal angles to the optical axis center intersection in world pixels.
    
    Camera convention:
      cx = home_x + pan_deg * px_per_deg_h
      cy = home_y - tilt_deg * px_per_deg_v
    """
    pan = float(angles.pan_deg if isinstance(angles, PtzAngles) else angles[0])
    tilt = float(angles.tilt_deg if isinstance(angles, PtzAngles) else angles[1])
    hx = float(cam_home.x if isinstance(cam_home, WorldPoint) else cam_home[0])
    hy = float(cam_home.y if isinstance(cam_home, WorldPoint) else cam_home[1])
    px_h, px_v = float(px_per_deg[0]), float(px_per_deg[1])
    return WorldPoint(hx + pan * px_h, hy - tilt * px_v)


def world_center_to_angles(world_pt: WorldPoint | tuple[float, float],
                           cam_home: WorldPoint | tuple[float, float],
                           px_per_deg: tuple[float, float] | Sequence[float]) -> PtzAngles:
    """Convert optical axis center intersection in world pixels to gimbal angles."""
    wx = float(world_pt.x if isinstance(world_pt, WorldPoint) else world_pt[0])
    wy = float(world_pt.y if isinstance(world_pt, WorldPoint) else world_pt[1])
    hx = float(cam_home.x if isinstance(cam_home, WorldPoint) else cam_home[0])
    hy = float(cam_home.y if isinstance(cam_home, WorldPoint) else cam_home[1])
    px_h, px_v = float(px_per_deg[0]), float(px_per_deg[1])
    pan = (wx - hx) / max(1e-6, px_h)
    tilt = (hy - wy) / max(1e-6, px_v)
    return PtzAngles(pan, tilt)


def fov_to_angles(fov_pt: FovPoint | tuple[float, float],
                  cam_angles: PtzAngles | tuple[float, float],
                  px_per_deg: tuple[float, float] | Sequence[float],
                  fov_size: tuple[int, int] | Sequence[int] = (640, 480)) -> PtzAngles:
    """Convert a point in FOV pixel coordinates to pointing angles required to center that point."""
    fx = float(fov_pt.x if isinstance(fov_pt, FovPoint) else fov_pt[0])
    fy = float(fov_pt.y if isinstance(fov_pt, FovPoint) else fov_pt[1])
    pan = float(cam_angles.pan_deg if isinstance(cam_angles, PtzAngles) else cam_angles[0])
    tilt = float(cam_angles.tilt_deg if isinstance(cam_angles, PtzAngles) else cam_angles[1])
    px_h, px_v = float(px_per_deg[0]), float(px_per_deg[1])
    fw, fh = float(fov_size[0]), float(fov_size[1])
    
    delta_pan = (fx - fw / 2.0) / max(1e-6, px_h)
    delta_tilt = -(fy - fh / 2.0) / max(1e-6, px_v)
    return PtzAngles(pan + delta_pan, tilt + delta_tilt)


__all__ = [
    "FovPoint",
    "WorldPoint",
    "PtzAngles",
    "world_to_fov",
    "fov_to_world",
    "angles_to_world_center",
    "world_center_to_angles",
    "fov_to_angles",
]
