# remote_terminal/geometry.py - GeometryEngine: range/LOS/relative vector (§46).
#
# Pure functions only. No beam rendering, no beacon encoding here.
from __future__ import annotations

import math

from remote_terminal.models import Vector2


def normalize_angle_deg(angle_deg: float) -> float:
    """Wrap to (-180, 180] degrees."""
    a = float(angle_deg) % 360.0
    if a > 180.0:
        a -= 360.0
    if a <= -180.0:
        a += 360.0
    return a


def rotate_offset(x: float, y: float, heading_deg: float) -> Vector2:
    """Rotate a local formation offset into world axes (§43)."""
    return Vector2(float(x), float(y)).rotated(heading_deg)


def relative_vector(source_m: Vector2, target_m: Vector2) -> Vector2:
    """Target-minus-source vector (dx, dy) in metres."""
    return Vector2(target_m.x - source_m.x, target_m.y - source_m.y)


def range_m(source_m: Vector2, target_m: Vector2) -> float:
    """Euclidean distance in metres."""
    dx = target_m.x - source_m.x
    dy = target_m.y - source_m.y
    return math.sqrt(dx * dx + dy * dy)


def los_angle_deg(source_m: Vector2, target_m: Vector2) -> float:
    """Line-of-sight angle in degrees (0° = +X, 90° = +Y)."""
    dx = target_m.x - source_m.x
    dy = target_m.y - source_m.y
    return normalize_angle_deg(math.degrees(math.atan2(dy, dx)))


class GeometryEngine:
    """LOS/range namespace (one responsibility: geometry only)."""

    normalize_angle_deg = staticmethod(normalize_angle_deg)
    rotate_offset = staticmethod(rotate_offset)
    relative_vector = staticmethod(relative_vector)
    range_m = staticmethod(range_m)
    los_angle_deg = staticmethod(los_angle_deg)


__all__ = [
    "GeometryEngine",
    "normalize_angle_deg",
    "rotate_offset",
    "relative_vector",
    "range_m",
    "los_angle_deg",
]
