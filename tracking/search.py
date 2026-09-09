"""Deterministic camera acquisition search pattern."""

from __future__ import annotations


class SearchPattern:
    """Raster-scan the camera's valid pan/tilt range while searching."""

    def __init__(self, pan_speed: float = 240.0, row_step: float = 160.0):
        self.pan_speed = max(1.0, float(pan_speed))
        self.row_step = max(1.0, float(row_step))
        self._pan_direction = 1.0
        self._tilt_direction = 1.0

    def reset(self) -> None:
        self._pan_direction = 1.0
        self._tilt_direction = 1.0

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
