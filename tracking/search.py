"""Camera acquisition search pattern: raster + spiral + uncertainty-directed.

Backward compatible: SearchPattern(pan_speed, row_step).step(pan, tilt,
pan_range, tilt_range, dt) behaves as before (raster). New:
  mode="raster"|"spiral"|"adaptive" (adaptive = spiral around focus when set,
  else raster), focus support for reacq, coverage overlap helper.
"""

from __future__ import annotations

import math


class SearchPattern:
    """Scan the camera's valid pan/tilt range while searching."""

    def __init__(self, pan_speed: float = 240.0, row_step: float = 160.0,
                 mode: str = "raster", overlap: float = 0.2):
        self.pan_speed = max(1.0, float(pan_speed))
        self.row_step = max(1.0, float(row_step))
        self.mode = str(mode) if str(mode) in ("raster", "spiral", "adaptive") else "raster"
        self.overlap = float(min(max(overlap, 0.0), 0.8))
        self._pan_direction = 1.0
        self._tilt_direction = 1.0
        # Spiral state (angle/radius in px space, center = focus or range center)
        self._spiral_a = 0.0
        self._spiral_r = 0.0
        self._focus: tuple[float, float] | None = None
        self._focus_radius = 0.0
        self.visited_cells: set[tuple[int, int]] = set()
        self.steps = 0

    def reset(self) -> None:
        self._pan_direction = 1.0
        self._tilt_direction = 1.0
        self._spiral_a = 0.0
        self._spiral_r = 0.0
        self.visited_cells.clear()
        self.steps = 0

    def set_focus(self, pan: float, tilt: float, radius_px: float) -> None:
        """Set uncertainty-directed reacq focus (predicted pos + 3-sigma radius)."""
        try:
            self._focus = (float(pan), float(tilt))
            self._focus_radius = max(20.0, float(radius_px))
            self._spiral_a = 0.0
            self._spiral_r = 0.0
        except Exception:
            pass

    def clear_focus(self) -> None:
        self._focus = None

    @staticmethod
    def coverage_row_step(fov_px: float, overlap: float = 0.2) -> float:
        """Guaranteed-coverage row step: FOV*(1-overlap)."""
        return max(10.0, float(fov_px) * (1.0 - float(min(max(overlap, 0.0), 0.8))))

    def _raster(self, pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt):
        distance = self.pan_speed * max(0.0, float(dt))
        if self._pan_direction > 0.0:
            next_pan = pan + distance
            at_edge = next_pan >= pan_hi
            if at_edge:
                next_pan = pan_hi
        else:
            next_pan = pan - distance
            at_edge = next_pan <= pan_lo
            if at_edge:
                next_pan = pan_lo
        next_tilt = tilt
        if at_edge:
            self._pan_direction *= -1.0
            next_tilt += self._tilt_direction * self.row_step
            if next_tilt >= tilt_hi:
                next_tilt = tilt_hi
                self._tilt_direction = -1.0
            elif next_tilt <= tilt_lo:
                next_tilt = tilt_lo
                self._tilt_direction = 1.0
        return float(next_pan), float(next_tilt)

    def _spiral(self, pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt):
        # Archimedean spiral around focus (or range center), expanding outward.
        cx = (pan_lo + pan_hi) / 2.0 if self._focus is None else self._focus[0]
        cy = (tilt_lo + tilt_hi) / 2.0 if self._focus is None else self._focus[1]
        # Angular speed keeps tangential speed ~= pan_speed
        r = max(20.0, self._spiral_r)
        omega = self.pan_speed / r
        self._spiral_a += omega * max(0.0, float(dt))
        # Radial growth: one row_step per revolution (guaranteed coverage)
        self._spiral_r += self.row_step * (omega * max(0.0, float(dt))) / (2 * math.pi)
        # Cap at range diagonal so spiral degrades to raster sweep when exhausted
        max_r = math.hypot(pan_hi - pan_lo, tilt_hi - tilt_lo) / 2.0 + 1.0
        if self._spiral_r > max_r:
            self._spiral_r = 0.0
            return self._raster(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        nx = cx + self._spiral_r * math.cos(self._spiral_a)
        ny = cy + self._spiral_r * math.sin(self._spiral_a)
        return float(min(max(nx, pan_lo), pan_hi)), float(min(max(ny, tilt_lo), tilt_hi))

    def step(
        self,
        pan: float,
        tilt: float,
        pan_range: tuple[float, float],
        tilt_range: tuple[float, float],
        dt: float,
    ) -> tuple[float, float]:
        """Return the next scan position inside the camera's valid ranges."""
        pan_lo, pan_hi = sorted((float(pan_range[0]), float(pan_range[1])))
        tilt_lo, tilt_hi = sorted((float(tilt_range[0]), float(tilt_range[1])))
        pan = min(max(float(pan), pan_lo), pan_hi)
        tilt = min(max(float(tilt), tilt_lo), tilt_hi)
        if self.mode == "spiral" or (self.mode == "adaptive" and self._focus is not None):
            nx, ny = self._spiral(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        else:
            nx, ny = self._raster(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        self.steps += 1
        try:
            cell = (int(nx // max(20.0, self.row_step)), int(ny // max(20.0, self.row_step)))
            self.visited_cells.add(cell)
        except Exception:
            pass
        return nx, ny

    @property
    def coverage(self) -> int:
        return len(self.visited_cells)
