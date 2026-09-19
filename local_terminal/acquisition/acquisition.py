# local_terminal/acquisition.py - Acquisition scan pattern generator per LocalTerminal.md
from __future__ import annotations

import math
import random
from typing import Any

from local_terminal.config import AcquisitionConfig


class AcquisitionScanner:
    """
    Acquisition pattern generator:
      - RANDOM: Autonomous smooth pseudo-random waypoint exploration with sector dwell.
      - RASTER: Alternating horizontal sweeps stepped vertically (exact integer rows).
      - SPIRAL: Archimedean spiral expanding outward.
      - SECTOR: Azimuthal sweeps.
      - GRID: Discrete lattice points.

    Timeout-wrap semantics (uniform entry, per-pattern state):
      - RASTER/SECTOR/FIGURE_8/GRID derive pose from persistent counters, so a
        timeout wrap only restarts the elapsed clock — the sweep continues.
      - SPIRAL resets radius/angle to re-expand from center.
      - RANDOM picks a fresh waypoint.
    Visited-sector memory (8x8 over the search region) biases RANDOM toward
    unexplored sectors and resumes RASTER at the first unvisited row.
    """

    # Visited-sector grid resolution (S3).
    SECTORS = 8

    def __init__(self, config: AcquisitionConfig | None = None, rng: Any | None = None):
        self.config = (config or AcquisitionConfig()).validate()
        self.active = False
        self.elapsed_time = 0.0
        self.current_pan_offset = 0.0
        self.current_tilt_offset = 0.0

        # Pattern internal state
        self._raster_dir = 1.0
        self._raster_tilt = 0.0
        self._raster_row = 0
        self._raster_rows = 1
        self._spiral_angle = 0.0
        self._spiral_radius = 0.0
        self._grid_row = 0
        self._grid_col = 0
        self._visited: set[tuple[int, int]] = set()

        # Random search state
        self._rng = rng or random.Random(42)
        self._random_target_pan = 0.0
        self._random_target_tilt = 0.0
        self._random_dwell = 0.0

    def _sector_of(self, pan: float, tilt: float) -> tuple[int, int]:
        """Quantize a region offset into the visited-sector grid."""
        p_min = self.config.search_region_pan_min
        p_max = self.config.search_region_pan_max
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max
        n = max(1, self.SECTORS)
        cx = min(n - 1, max(0, int((pan - p_min) / max(1e-6, p_max - p_min) * n)))
        cy = min(n - 1, max(0, int((tilt - t_min) / max(1e-6, t_max - t_min) * n)))
        return (cx, cy)

    def _mark_visited(self) -> None:
        self._visited.add(self._sector_of(self.current_pan_offset, self.current_tilt_offset))
        if len(self._visited) > self.SECTORS * self.SECTORS + 8:
            # Bound memory; drop arbitrary oldest-ish entries.
            for _ in range(len(self._visited) - self.SECTORS * self.SECTORS):
                self._visited.pop()

    def _raster_row_count(self) -> int:
        """Exact integer row count so the sweep provably covers edge to edge."""
        t_span = max(1.0, self.config.search_region_tilt_max - self.config.search_region_tilt_min)
        step = max(1.0, t_span / 8.0)
        return max(1, int(round(t_span / step)))

    def _pick_random_waypoint(self) -> None:
        p_min = self.config.search_region_pan_min
        p_max = self.config.search_region_pan_max
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max
        # Prefer unvisited sectors; reset the memory once fully covered.
        if len(self._visited) >= self.SECTORS * self.SECTORS:
            self._visited.clear()
        best = None
        for _ in range(8):
            if hasattr(self._rng, "uniform"):
                cand = (float(self._rng.uniform(p_min, p_max)),
                        float(self._rng.uniform(t_min, t_max)))
            else:
                cand = (random.uniform(p_min, p_max), random.uniform(t_min, t_max))
            if self._sector_of(*cand) not in self._visited:
                best = cand
                break
            best = cand
        self._random_target_pan, self._random_target_tilt = best
        self._random_dwell = 0.0

    def start(self) -> None:
        self.active = True
        self.elapsed_time = 0.0
        self._raster_dir = 1.0
        self.current_pan_offset = self.config.search_region_pan_min
        self.current_tilt_offset = self.config.search_region_tilt_min
        self._raster_tilt = self.config.search_region_tilt_min
        self._raster_rows = self._raster_row_count()
        # Resume at the first unvisited row when memory says earlier rows
        # were already swept (suspend→resume continuity).
        self._raster_row = 0
        for r in range(self._raster_rows):
            tilt = self._row_tilt(r)
            if self._sector_of(self.config.search_region_pan_min, tilt) not in self._visited:
                self._raster_row = r
                break
        self._raster_tilt = self._row_tilt(self._raster_row)
        self.current_tilt_offset = self._raster_tilt
        self._spiral_angle = 0.0
        self._spiral_radius = 0.0
        self._grid_row = 0
        self._grid_col = 0
        self._pick_random_waypoint()

    def _row_tilt(self, row: int) -> float:
        """Exact tilt for raster row (covers t_min..t_max inclusive)."""
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max
        rows = max(1, self._raster_rows)
        if rows <= 1:
            return (t_min + t_max) * 0.5
        return t_min + (max(0, min(rows - 1, row)) / (rows - 1)) * (t_max - t_min)

    def start_at(self, pan_deg: float, tilt_deg: float) -> None:
        """Resume scan around a deg offset (reacquisition) instead of region edge.

        Keeps the camera near last-known position so nearby targets are
        re-found quickly instead of jumping to p_min/t_min.
        """
        p_min = self.config.search_region_pan_min
        p_max = self.config.search_region_pan_max
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max
        pan_deg = float(max(p_min, min(p_max, pan_deg)))
        tilt_deg = float(max(t_min, min(t_max, tilt_deg)))
        self.active = True
        # Do NOT reset elapsed_time here — preserves timeout continuity.
        self.current_pan_offset = pan_deg
        self.current_tilt_offset = tilt_deg
        self._raster_rows = self._raster_row_count()
        self._raster_tilt = tilt_deg
        self._raster_dir = 1.0
        # Snap the row index to the nearest exact row for continuity.
        try:
            t_min = self.config.search_region_tilt_min
            t_max = self.config.search_region_tilt_max
            rows = max(1, self._raster_rows)
            frac = (tilt_deg - t_min) / max(1e-6, t_max - t_min) if rows > 1 else 0.0
            self._raster_row = max(0, min(rows - 1, int(round(frac * (rows - 1)))))
        except (TypeError, ValueError):
            self._raster_row = 0
        # Seed spiral at current radius/angle so it expands outward locally.
        self._spiral_radius = float(min(abs(pan_deg), abs(tilt_deg), max(p_max - p_min, t_max - t_min) * 0.25))
        self._spiral_angle = math.atan2(tilt_deg, pan_deg) if (pan_deg or tilt_deg) else 0.0
        self._random_target_pan = pan_deg
        self._random_target_tilt = tilt_deg
        self._random_dwell = 0.0
        self._grid_row = 0
        self._grid_col = 0

    def stop(self) -> None:
        self.active = False

    def reset(self) -> None:
        self.stop()
        self.elapsed_time = 0.0
        self.current_pan_offset = 0.0
        self.current_tilt_offset = 0.0
        self._pick_random_waypoint()

    def update(self, dt: float, current_pan: float = 0.0, current_tilt: float = 0.0) -> tuple[float, float, bool]:
        """
        Step the acquisition pattern.
        Returns:
          (target_pan_deg_offset, target_tilt_deg_offset, timed_out)
        """
        if not self.active:
            return 0.0, 0.0, False

        self.elapsed_time += dt
        timed_out = self.elapsed_time >= self.config.timeout
        if timed_out:
            self.elapsed_time = self.elapsed_time % max(1e-3, self.config.timeout)
            if self.config.search_pattern.upper() == "SPIRAL":
                self._spiral_radius = 0.0
                self._spiral_angle = 0.0
            elif self.config.search_pattern.upper() == "RANDOM":
                self._pick_random_waypoint()

        speed = float(self.config.search_speed)  # deg/s
        pattern = self.config.search_pattern.upper()

        p_min = self.config.search_region_pan_min
        p_max = self.config.search_region_pan_max
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max

        p_span = max(1.0, p_max - p_min)
        t_span = max(1.0, t_max - t_min)

        if pattern == "RANDOM":
            # Autonomous smooth exploration towards randomized waypoints with dwell
            dx = self._random_target_pan - self.current_pan_offset
            dy = self._random_target_tilt - self.current_tilt_offset
            dist = math.hypot(dx, dy)

            if dist < 0.5:
                # Reached waypoint: dwell to sample optical spectrum
                self._random_dwell += dt
                if self._random_dwell >= 0.4:
                    self._pick_random_waypoint()
            else:
                step = min(dist, speed * dt)
                self.current_pan_offset += (dx / dist) * step
                self.current_tilt_offset += (dy / dist) * step

        elif pattern == "RASTER":
            # Pan moves horizontally at search speed; tilt advances one exact
            # row per sweep so edge-to-edge coverage is guaranteed.
            self.current_pan_offset += self._raster_dir * speed * dt
            if self.current_pan_offset >= p_max:
                self.current_pan_offset = p_max
                self._raster_dir = -1.0
                # Step tilt down/up
                self._raster_row += 1
                if self._raster_row >= self._raster_rows:
                    self._raster_row = 0
                self._raster_tilt = self._row_tilt(self._raster_row)
            elif self.current_pan_offset <= p_min:
                self.current_pan_offset = p_min
                self._raster_dir = 1.0
                self._raster_row += 1
                if self._raster_row >= self._raster_rows:
                    self._raster_row = 0
                self._raster_tilt = self._row_tilt(self._raster_row)
            self.current_tilt_offset = self._raster_tilt

        elif pattern == "SPIRAL":
            # Time-parametric Archimedean spiral: constant angular rate,
            # radius grows linearly to r_max over `timeout` seconds.
            # Old form omega=speed/max(1,r) spun ~15 rad/s at center.
            r_max = max(p_span, t_span) * 0.5
            timeout = max(1.0, float(self.config.timeout))
            # One full sweep every ~8 s, radius completes at timeout.
            omega = 2.0 * math.pi / 8.0
            self._spiral_angle += omega * dt
            frac = min(1.0, self.elapsed_time / timeout)
            self._spiral_radius = r_max * frac
            self.current_pan_offset = self._spiral_radius * math.cos(self._spiral_angle)
            self.current_tilt_offset = self._spiral_radius * math.sin(self._spiral_angle) * (t_span / max(1e-6, p_span))
            if timed_out:
                self._spiral_radius = 0.0
                self._spiral_angle = 0.0

        elif pattern == "SECTOR":
            # Azimuthal sweep back and forth
            self.current_pan_offset += self._raster_dir * speed * dt
            if self.current_pan_offset >= p_max:
                self.current_pan_offset = p_max
                self._raster_dir = -1.0
            elif self.current_pan_offset <= p_min:
                self.current_pan_offset = p_min
                self._raster_dir = 1.0
            self.current_tilt_offset = (t_min + t_max) * 0.5

        elif pattern in ("FIGURE_8", "FIGURE-8", "FIG8", "FIGURE 8"):
            # Lissajous figure-8 sweep: x = A*sin(w t), y = B*sin(2 w t).
            # Covers the 2D region smoothly with a ~12 s period, crossing
            # the center twice per period (no edge dwell like raster).
            A = p_span * 0.5
            B = t_span * 0.5
            w = 2.0 * math.pi / 12.0
            t = self.elapsed_time
            self.current_pan_offset = A * math.sin(w * t)
            self.current_tilt_offset = B * math.sin(2.0 * w * t)

        else:  # GRID or CUSTOM — true 2D lattice, not pan-only sweep
            n_cols = max(2, min(12, int(p_span / max(0.5, speed * 0.5)) + 2))
            n_rows = max(2, min(12, int(t_span / max(0.5, speed * 0.5)) + 2))
            # Advance one cell per dwell interval so each lattice point is visited.
            dwell = 0.4
            steps = int(self.elapsed_time / max(1e-3, dwell))
            self._grid_col = (steps % n_cols)
            self._grid_row = ((steps // n_cols) % n_rows)
            self.current_pan_offset = p_min + (self._grid_col / max(1, n_cols - 1)) * p_span
            self.current_tilt_offset = t_min + (self._grid_row / max(1, n_rows - 1)) * t_span

        self._mark_visited()
        return self.current_pan_offset, self.current_tilt_offset, timed_out
