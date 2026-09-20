# remote_terminal/formation.py - FormationManager: formation geometry only.
#
# Generates terminal offsets relative to the formation center (§§35-44).
# Pure geometry: no motion, no optics. New shapes can be added here without
# touching RemoteTerminal (RemoteTerminal.md §80).
from __future__ import annotations

import math

from remote_terminal.config import FormationShape
from remote_terminal.geometry import rotate_offset
from remote_terminal.models import Vector2

# Internal constants (RemoteTerminal.md §§39,41,42 — NOT GUI parameters).
ARC_ANGLE_DEG: float = 120.0
RECTANGLE_ASPECT: float = 2.0  # width = 2 * height for perimeter layout
V_HALF_ANGLE_DEG: float = 30.0  # arm half-angle from the forward axis


class FormationManager:
    """Terminal offsets relative to the formation center (local frame)."""

    def __init__(self, arc_angle_deg: float = ARC_ANGLE_DEG):
        self.arc_angle_deg = float(arc_angle_deg)

    # -- public ------------------------------------------------------
    def compute_offsets(
        self,
        terminal_count: int,
        shape: FormationShape,
        spacing_m: float,
    ) -> list[Vector2]:
        """Centered local-frame offsets (unrotated; see ``oriented_offsets``)."""
        count = int(terminal_count)
        if count < 1:
            raise ValueError(f"terminal count must be >= 1, got {terminal_count!r}.")
        spacing = max(0.0, float(spacing_m))
        if not isinstance(shape, FormationShape):
            raise ValueError(f"unknown formation shape: {shape!r}.")
        if count == 1:
            # Degenerate single-point formation for every shape.
            return [Vector2(0.0, 0.0)]
        if shape == FormationShape.SINGLE:
            raise ValueError("SINGLE formation requires exactly one terminal.")
        if shape == FormationShape.LINE:
            return self._line(count, spacing)
        if shape == FormationShape.CIRCLE:
            return self._circle(count, spacing)
        if shape == FormationShape.ARC:
            return self._arc(count, spacing)
        if shape == FormationShape.GRID:
            return self._grid(count, spacing)
        if shape == FormationShape.RECTANGLE:
            return self._rectangle(count, spacing)
        if shape == FormationShape.V_FORMATION:
            return self._vee(count, spacing)
        raise ValueError(f"unknown formation shape: {shape!r}.")

    def oriented_offsets(
        self,
        terminal_count: int,
        shape: FormationShape,
        spacing_m: float,
        heading_deg: float,
    ) -> list[Vector2]:
        """Local offsets rotated into world axes (§43)."""
        return [
            rotate_offset(o.x, o.y, heading_deg)
            for o in self.compute_offsets(terminal_count, shape, spacing_m)
        ]

    # -- shapes ------------------------------------------------------
    @staticmethod
    def _line(count: int, spacing: float) -> list[Vector2]:
        # Evenly spaced along X, centered on the origin (§37).
        origin = (count - 1) / 2.0
        return [Vector2((i - origin) * spacing, 0.0) for i in range(count)]

    @staticmethod
    def _circle(count: int, spacing: float) -> list[Vector2]:
        # Even angular spacing; radius from spacing: circumference ≈ N·s (§38).
        radius = count * spacing / (2.0 * math.pi)
        return [
            Vector2(
                radius * math.cos(2.0 * math.pi * i / count),
                radius * math.sin(2.0 * math.pi * i / count),
            )
            for i in range(count)
        ]

    def _arc(self, count: int, spacing: float) -> list[Vector2]:
        # Arc of ARC_ANGLE_DEG; radius from spacing: arc length ≈ (N-1)·s (§39).
        arc_rad = math.radians(self.arc_angle_deg)
        radius = (count - 1) * spacing / arc_rad if arc_rad > 0 else 0.0
        if count == 2:
            angles = [-arc_rad / 2.0, arc_rad / 2.0]
        else:
            angles = [-arc_rad / 2.0 + arc_rad * i / (count - 1) for i in range(count)]
        return [Vector2(radius * math.cos(a), radius * math.sin(a)) for a in angles]

    @staticmethod
    def _grid(count: int, spacing: float) -> list[Vector2]:
        # Roughly square grid, centered on the OCCUPIED positions (§40):
        # generate the full grid, take the first N, then recenter.
        import math as _math

        cols = max(1, int(_math.ceil(_math.sqrt(count))))
        rows = max(1, int(_math.ceil(count / cols)))
        pts = [
            Vector2(
                (c - (cols - 1) / 2.0) * spacing,
                ((rows - 1) / 2.0 - r) * spacing,
            )
            for r in range(rows)
            for c in range(cols)
        ][:count]
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        return [Vector2(p.x - cx, p.y - cy) for p in pts]

    @staticmethod
    def _rectangle(count: int, spacing: float) -> list[Vector2]:
        # Evenly spaced along the perimeter of a 2:1 rectangle (§41).
        # Perimeter P ≈ N·s with W = 2H → H = N·s/6, W = N·s/3.
        if count == 2:
            return [Vector2(-spacing / 2.0, 0.0), Vector2(spacing / 2.0, 0.0)]
        h = count * spacing / 6.0
        w = 2.0 * h
        perimeter = 2.0 * (w + h)
        pts: list[Vector2] = []
        for i in range(count):
            d = (i / count) * perimeter
            pts.append(FormationManager._perimeter_point(w, h, d))
        # Re-center on the centroid (exact for symmetric counts).
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        return [Vector2(p.x - cx, p.y - cy) for p in pts]

    @staticmethod
    def _perimeter_point(w: float, h: float, d: float) -> Vector2:
        """Point at arclength ``d`` along the rectangle perimeter from (-w/2, -h/2)."""
        px, py = -w / 2.0, -h / 2.0
        for length, dx, dy in ((w, 1.0, 0.0), (h, 0.0, 1.0), (w, -1.0, 0.0), (h, 0.0, -1.0)):
            if d <= length:
                return Vector2(px + dx * d, py + dy * d)
            d -= length
            px, py = px + dx * length, py + dy * length
        return Vector2(px, py)  # float-error fallback: closing corner

    @staticmethod
    def _vee(count: int, spacing: float) -> list[Vector2]:
        # Leader at front (+X); arms trail at ±V_HALF_ANGLE_DEG (§42).
        half = math.radians(V_HALF_ANGLE_DEG)
        pts = [Vector2(0.0, 0.0)]
        for i in range(1, count):
            rank = (i + 1) // 2
            side = 1.0 if i % 2 == 1 else -1.0
            pts.append(
                Vector2(
                    -rank * spacing * math.cos(half),
                    side * rank * spacing * math.sin(half),
                )
            )
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        return [Vector2(p.x - cx, p.y - cy) for p in pts]


__all__ = [
    "FormationManager",
    "ARC_ANGLE_DEG",
    "RECTANGLE_ASPECT",
    "V_HALF_ANGLE_DEG",
]
