# remote_terminal/formation.py - FormationManager: formation geometry only (Plan Hybrid-AI §1).
#
# Pruned to 3 shapes: SINGLE, LINE, CIRCLE. GRID/RECTANGLE/V/ARC deleted.
# Internal constants ARC_ANGLE etc. removed — not needed for 3 shapes.

from __future__ import annotations

import math

from remote_terminal.config import FormationShape
from remote_terminal.geometry import rotate_offset
from remote_terminal.models import Vector2


class FormationManager:
    """Terminal offsets relative to the formation center (local frame)."""

    def __init__(self):
        pass

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
            return [Vector2(0.0, 0.0)]
        if shape == FormationShape.SINGLE:
            raise ValueError("SINGLE formation requires exactly one terminal.")
        if shape == FormationShape.LINE:
            return self._line(count, spacing)
        if shape == FormationShape.CIRCLE:
            return self._circle(count, spacing)
        raise ValueError(f"unknown formation shape: {shape!r}. Allowed: single, line, circle.")

    def oriented_offsets(
        self,
        terminal_count: int,
        shape: FormationShape,
        spacing_m: float,
        heading_deg: float,
    ) -> list[Vector2]:
        """Local offsets rotated into world axes."""
        return [
            rotate_offset(o.x, o.y, heading_deg)
            for o in self.compute_offsets(terminal_count, shape, spacing_m)
        ]

    @staticmethod
    def _line(count: int, spacing: float) -> list[Vector2]:
        origin = (count - 1) / 2.0
        return [Vector2((i - origin) * spacing, 0.0) for i in range(count)]

    @staticmethod
    def _circle(count: int, spacing: float) -> list[Vector2]:
        radius = count * spacing / (2.0 * math.pi)
        return [
            Vector2(
                radius * math.cos(2.0 * math.pi * i / count),
                radius * math.sin(2.0 * math.pi * i / count),
            )
            for i in range(count)
        ]


__all__ = ["FormationManager"]
