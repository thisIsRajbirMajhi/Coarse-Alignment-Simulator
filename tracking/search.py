"""Camera acquisition search: raster + grid + spiral + uncertainty-directed.

Backward compatible: SearchPattern(pan_speed, row_step).step(pan, tilt,
pan_range, tilt_range, dt) behaves as before (raster). Modes:
  "raster"   — continuous boustrophedon sweep, skips fully-searched rows
  "grid"     — discrete cell sweep, always steers to nearest unsearched cell
  "spiral"   — Archimedean spiral around focus (or range center)
  "adaptive" — spiral around focus when set, else raster
  "auto"     — cycles raster -> grid -> spiral every `switch_interval_s`
               without a find, keeping ONE shared coverage map so a new
               method never re-searches ground already covered. A full sweep
               clears the map for the next pass.

Smart coverage: all modes share a visited-cell grid (cell = row_step).
Grid mode only targets unvisited cells; raster jumps over fully-visited
rows; spiral expands outward (no repeats within a sweep). `mark_found()`
resets the episode (call on acquisition).
"""

from __future__ import annotations

import math

_AUTO_ORDER = ("raster", "grid", "spiral")


class SearchPattern:
    """Scan the camera's valid pan/tilt range while searching."""

    def __init__(self, pan_speed: float = 240.0, row_step: float = 160.0,
                 mode: str = "raster", overlap: float = 0.2,
                 switch_interval_s: float = 8.0):
        self.pan_speed = max(1.0, float(pan_speed))
        self.row_step = max(1.0, float(row_step))
        self.mode = str(mode) if str(mode) in ("raster", "spiral", "adaptive", "grid", "auto") else "raster"
        self.overlap = float(min(max(overlap, 0.0), 0.8))
        self.switch_interval_s = max(1.0, float(switch_interval_s))
        self._pan_direction = 1.0
        self._tilt_direction = 1.0
        # Spiral state (angle/radius in px space, center = focus or range center)
        self._spiral_a = 0.0
        self._spiral_r = 0.0
        self._focus: tuple[float, float] | None = None
        self._focus_radius = 0.0
        # Shared smart-coverage map: cells already swept by ANY method.
        self.visited_cells: set[tuple[int, int]] = set()
        self.steps = 0
        # Auto-switch state.
        self._auto_idx = 0
        self._mode_time = 0.0
        self.switches = 0

    # -- episode lifecycle -------------------------------------------
    def reset(self) -> None:
        self._pan_direction = 1.0
        self._tilt_direction = 1.0
        self._spiral_a = 0.0
        self._spiral_r = 0.0
        self.visited_cells.clear()
        self.steps = 0
        self._auto_idx = 0
        self._mode_time = 0.0
        self.switches = 0

    def mark_found(self) -> None:
        """Target acquired — fresh episode (keeps config)."""
        self.reset()

    @property
    def active_mode(self) -> str:
        """Effective method right now ('auto' resolves to raster/grid/spiral)."""
        if self.mode == "auto":
            return _AUTO_ORDER[self._auto_idx % len(_AUTO_ORDER)]
        if self.mode == "adaptive":
            return "spiral" if self._focus is not None else "raster"
        return self.mode

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

    # -- shared coverage grid -----------------------------------------
    def _cell_size(self) -> float:
        return max(20.0, float(self.row_step))

    def _cell_of(self, pan: float, tilt: float) -> tuple[int, int]:
        cs = self._cell_size()
        return (int(math.floor(pan / cs)), int(math.floor(tilt / cs)))

    def _mark(self, pan: float, tilt: float) -> None:
        try:
            self.visited_cells.add(self._cell_of(pan, tilt))
        except Exception:
            pass

    def _grid_dims(self, pan_lo, pan_hi, tilt_lo, tilt_hi) -> tuple[int, int]:
        cs = self._cell_size()
        cols = max(1, int(math.ceil((pan_hi - pan_lo) / cs)) + 1)
        rows = max(1, int(math.ceil((tilt_hi - tilt_lo) / cs)) + 1)
        return cols, rows

    def _nearest_unvisited(self, pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi) -> tuple[float, float] | None:
        """Center of the unvisited cell closest to (pan, tilt), or None if swept."""
        cols, rows = self._grid_dims(pan_lo, pan_hi, tilt_lo, tilt_hi)
        best = None
        best_d2 = float("inf")
        for cj in range(rows):
            for ci in range(cols):
                if (ci, cj) in self.visited_cells:
                    continue
                # NOTE: global cell ids (floor(pos/cs)) vs local (ci,cj) differ by
                # offset; compare in position space via the local center, and
                # test membership with the matching global id.
                cx = pan_lo + (ci + 0.5) * self._cell_size()
                cy = tilt_lo + (cj + 0.5) * self._cell_size()
                if self._cell_of(cx, cy) in self.visited_cells:
                    continue
                d2 = (cx - pan) ** 2 + (cy - tilt) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best = (cx, cy)
        return best

    def _unvisited_focus(self, pan_lo, pan_hi, tilt_lo, tilt_hi) -> tuple[float, float] | None:
        """Centroid of unsearched ground — smart restart point for spiral."""
        cols, rows = self._grid_dims(pan_lo, pan_hi, tilt_lo, tilt_hi)
        sx = sy = n = 0.0
        for cj in range(rows):
            for ci in range(cols):
                cx = pan_lo + (ci + 0.5) * self._cell_size()
                cy = tilt_lo + (cj + 0.5) * self._cell_size()
                if self._cell_of(cx, cy) in self.visited_cells:
                    continue
                sx += cx
                sy += cy
                n += 1.0
        if n == 0:
            return None
        return (sx / n, sy / n)

    # -- methods ---------------------------------------------------------
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
            next_tilt = self._next_unvisited_row(tilt, pan_lo, pan_hi, tilt_lo, tilt_hi)
        return float(next_pan), float(next_tilt)

    def _next_unvisited_row(self, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi) -> float:
        """Step to the nearest unsearched row in the sweep direction.

        Jumps over fully-visited rows instead of re-scanning them. If every
        row is swept, the map clears for a fresh pass.
        """
        step = self.row_step
        # Probe forward first, then backward, up to the full height.
        span = (tilt_hi - tilt_lo) + step
        k = 1
        while k * step <= span + step:
            for direction in (self._tilt_direction, -self._tilt_direction):
                cand = tilt + direction * k * step
                if tilt_lo - 1e-6 <= cand <= tilt_hi + 1e-6:
                    if self._row_band_has_unvisited(cand, pan_lo, pan_hi):
                        self._tilt_direction = direction
                        return float(min(max(cand, tilt_lo), tilt_hi))
            k += 1
        # Everything swept — fresh pass.
        self.visited_cells.clear()
        self._tilt_direction = 1.0
        return float(min(max(tilt + step, tilt_lo), tilt_hi))

    def _row_band_has_unvisited(self, tilt, pan_lo, pan_hi) -> bool:
        """True if any cell overlapping the row band around `tilt` is unvisited."""
        cs = self._cell_size()
        half = self.row_step / 2.0
        # Walk cell rows overlapping the band; check columns spanning pan range.
        j0 = int(math.floor((tilt - half) / cs)) - 1
        j1 = int(math.floor((tilt + half) / cs)) + 1
        for cj in range(j0, j1 + 1):
            cy = (cj + 0.5) * cs
            if abs(cy - tilt) > half + cs / 2.0:
                continue
            # Any column overlapping [pan_lo, pan_hi]?
            ci0 = int(math.floor(pan_lo / cs)) - 1
            ci1 = int(math.floor(pan_hi / cs)) + 1
            # Only columns whose cell strictly overlaps [pan_lo, pan_hi]
            # (ghost cells outside the range must not count as unvisited).
            for ci in range(ci0, ci1 + 1):
                cx = (ci + 0.5) * cs
                if not (cx + cs / 2.0 > pan_lo and cx - cs / 2.0 < pan_hi):
                    continue
                if (ci, cj) not in self.visited_cells:
                    return True
        return False

    def _grid(self, pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt):
        """Hop between unsearched cell centers (nearest first)."""
        target = self._nearest_unvisited(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi)
        if target is None:
            # Full sweep done — fresh pass, keep sweeping without repeats gap.
            self.visited_cells.clear()
            target = self._nearest_unvisited(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi)
            if target is None:
                return float(pan), float(tilt)
        tx, ty = target
        tx = min(max(tx, pan_lo), pan_hi)
        ty = min(max(ty, tilt_lo), tilt_hi)
        dx, dy = tx - pan, ty - tilt
        dist = math.hypot(dx, dy)
        step_len = self.pan_speed * max(0.0, float(dt))
        if dist <= max(step_len, self._cell_size() / 2.0):
            nx, ny = tx, ty
        elif dist > 1e-9:
            nx, ny = pan + dx / dist * step_len, tilt + dy / dist * step_len
        else:
            nx, ny = pan, tilt
        return float(min(max(nx, pan_lo), pan_hi)), float(min(max(ny, tilt_lo), tilt_hi))

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

    def _maybe_auto_switch(self, dt, pan_lo, pan_hi, tilt_lo, tilt_hi) -> None:
        if self.mode != "auto":
            return
        self._mode_time += max(0.0, float(dt))
        if self._mode_time >= self.switch_interval_s:
            self._mode_time = 0.0
            self._auto_idx = (self._auto_idx + 1) % len(_AUTO_ORDER)
            self.switches += 1
            # New method inherits the coverage map (never re-search swept
            # ground). Restart spiral at the centroid of unsearched ground.
            self._spiral_a = 0.0
            self._spiral_r = 0.0
            focus = self._unvisited_focus(pan_lo, pan_hi, tilt_lo, tilt_hi)
            if focus is not None:
                self._focus = focus
                self._focus_radius = max(20.0, self.row_step)

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
        self._maybe_auto_switch(dt, pan_lo, pan_hi, tilt_lo, tilt_hi)
        effective = self.active_mode
        if effective == "spiral":
            nx, ny = self._spiral(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        elif effective == "grid":
            nx, ny = self._grid(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        elif self.mode == "adaptive" and self._focus is not None:
            nx, ny = self._spiral(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        else:
            nx, ny = self._raster(pan, tilt, pan_lo, pan_hi, tilt_lo, tilt_hi, dt)
        self.steps += 1
        self._mark(nx, ny)
        return nx, ny

    @property
    def coverage(self) -> int:
        return len(self.visited_cells)
