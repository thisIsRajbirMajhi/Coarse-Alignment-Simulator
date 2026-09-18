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
      - RASTER: Alternating horizontal sweeps stepped vertically.
      - SPIRAL: Archimedean spiral expanding outward.
      - SECTOR: Azimuthal sweeps.
      - GRID: Discrete lattice points.
    """

    def __init__(self, config: AcquisitionConfig | None = None, rng: Any | None = None):
        self.config = (config or AcquisitionConfig()).validate()
        self.active = False
        self.elapsed_time = 0.0
        self.current_pan_offset = 0.0
        self.current_tilt_offset = 0.0

        # Pattern internal state
        self._raster_dir = 1.0
        self._raster_tilt = 0.0
        self._spiral_angle = 0.0
        self._spiral_radius = 0.0

        # Random search state
        self._rng = rng or random.Random(42)
        self._random_target_pan = 0.0
        self._random_target_tilt = 0.0
        self._random_dwell = 0.0

    def _pick_random_waypoint(self) -> None:
        p_min = self.config.search_region_pan_min
        p_max = self.config.search_region_pan_max
        t_min = self.config.search_region_tilt_min
        t_max = self.config.search_region_tilt_max
        if hasattr(self._rng, "uniform"):
            self._random_target_pan = float(self._rng.uniform(p_min, p_max))
            self._random_target_tilt = float(self._rng.uniform(t_min, t_max))
        else:
            self._random_target_pan = random.uniform(p_min, p_max)
            self._random_target_tilt = random.uniform(t_min, t_max)
        self._random_dwell = 0.0

    def start(self) -> None:
        self.active = True
        self.elapsed_time = 0.0
        self._raster_dir = 1.0
        self.current_pan_offset = self.config.search_region_pan_min
        self.current_tilt_offset = self.config.search_region_tilt_min
        self._raster_tilt = self.config.search_region_tilt_min
        self._spiral_angle = 0.0
        self._spiral_radius = 0.0
        self._pick_random_waypoint()

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
            # Pan moves horizontally at search speed
            self.current_pan_offset += self._raster_dir * speed * dt
            if self.current_pan_offset >= p_max:
                self.current_pan_offset = p_max
                self._raster_dir = -1.0
                # Step tilt down/up
                self._raster_tilt += t_span * 0.15
                if self._raster_tilt > t_max:
                    self._raster_tilt = t_min
            elif self.current_pan_offset <= p_min:
                self.current_pan_offset = p_min
                self._raster_dir = 1.0
                self._raster_tilt += t_span * 0.15
                if self._raster_tilt > t_max:
                    self._raster_tilt = t_min
            self.current_tilt_offset = self._raster_tilt

        elif pattern == "SPIRAL":
            # Expanding Archimedean spiral: r = a * theta
            r_max = max(p_span, t_span) * 0.5
            dr = (speed * 0.1) * dt
            self._spiral_radius = min(r_max, self._spiral_radius + dr)
            omega = speed / max(1.0, self._spiral_radius)
            self._spiral_angle += omega * dt
            self.current_pan_offset = self._spiral_radius * math.cos(self._spiral_angle)
            self.current_tilt_offset = self._spiral_radius * math.sin(self._spiral_angle)
            if self._spiral_radius >= r_max and timed_out:
                self._spiral_radius = 0.0

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

        else:  # GRID or CUSTOM
            # Discrete steps
            period = max(1.0, p_span / max(0.1, speed))
            phase = (self.elapsed_time % period) / period
            self.current_pan_offset = p_min + phase * p_span
            self.current_tilt_offset = (t_min + t_max) * 0.5

        return self.current_pan_offset, self.current_tilt_offset, timed_out
