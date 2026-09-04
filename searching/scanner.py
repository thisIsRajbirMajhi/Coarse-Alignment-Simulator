# searching/scanner.py - Active-search scan geometries — drives camera when SEARCHING/LOST

from __future__ import annotations

import math
import time
from enum import Enum

class ScanPattern(Enum):
    SPIRAL = "spiral"
    RASTER = "raster"
    RANDOM = "random"

class SearchingStrategy:
    """
    Active-search strategy — proposes search offsets for camera sweep.

    All methods are pure (no state) and return a (d_pan, d_tilt) delta in px
    for the next frame. Caller decides how to apply (e.g., camera.move).

    Maths:
      spiral: r = k·sqrt(n), θ = n·golden_angle → (r·cosθ, r·sinθ)
      raster: serpentine grid with step = fov_dim / 3
      random: uniform jitter within ±scan_radius
    """

    @staticmethod
    def spiral_offset(step: int, k: float = 6.0) -> tuple[float, float]:
        """Archimedean spiral with golden-angle increment — uniform coverage."""
        r = k * math.sqrt(max(0, int(step)))
        theta = int(step) * 2.399963229728653  # golden angle rad
        return (r * math.cos(theta), r * math.sin(theta))

    @staticmethod
    def raster_offset(step: int, fov_w: float = 250.0, fov_h: float = 250.0, cols: int = 3) -> tuple[float, float]:
        """Serpentine raster — sweeps left→right, right→left."""
        step = int(step)
        row = step // int(cols)
        col = step % int(cols)
        # serpentine: odd rows reversed
        if row % 2 == 1:
            col = int(cols) - 1 - col
        x = (col - (int(cols) - 1) / 2) * (fov_w / 2.5)
        y = (row - 2) * (fov_h / 2.5)
        return (float(x), float(y))

    @staticmethod
    def random_offset(scan_radius: float = 120.0, rng=None) -> tuple[float, float]:
        """Uniform random within ±scan_radius — for stochastic search."""
        import numpy as np

        if rng is None:
            rng = np.random.default_rng(0)
        # use provided rng if it has uniform, else numpy
        try:
            dx = float(rng.uniform(-float(scan_radius), float(scan_radius)))
            dy = float(rng.uniform(-float(scan_radius), float(scan_radius)))
        except Exception:
            import random

            dx = random.uniform(-float(scan_radius), float(scan_radius))
            dy = random.uniform(-float(scan_radius), float(scan_radius))
        return (dx, dy)

    @staticmethod
    def next_offset(pattern: ScanPattern | str, step: int, **kwargs) -> tuple[float, float]:
        """Dispatch to pattern."""
        pat = pattern.value if isinstance(pattern, ScanPattern) else str(pattern)
        if pat == ScanPattern.SPIRAL.value:
            return SearchingStrategy.spiral_offset(int(step), **{k: v for k, v in kwargs.items() if k in ("k",)})
        if pat == ScanPattern.RASTER.value:
            return SearchingStrategy.raster_offset(int(step), **{k: v for k, v in kwargs.items() if k in ("fov_w", "fov_h", "cols")})
        return SearchingStrategy.random_offset(**kwargs)


class Scanner:
    """
    Stateful autonomous scanner — P1 blind search driver.

    Holds RNG, step counter, dwell logic. Random pattern moves camera
    until target found, then pauses when TRACKING (caller checks status).
    Respects dwell_frames: holds at each scan cell for N ticks before stepping.
    """

    def __init__(
        self,
        pattern: ScanPattern | str = ScanPattern.RANDOM,
        scan_radius: float = 90.0,
        dwell_frames: int = 2,
        seed: int | None = None,
        k: float = 6.0,
    ):
        self.pattern = ScanPattern(pattern) if isinstance(pattern, str) else pattern  # type: ignore
        if isinstance(self.pattern, str):
            try:
                self.pattern = ScanPattern(self.pattern)
            except Exception:
                self.pattern = ScanPattern.RANDOM
        self.scan_radius = float(scan_radius)
        self.dwell_frames = int(max(1, dwell_frames))
        self.k = float(k)
        self._step: int = 0
        self._dwell_counter: int = 0
        self._cached_offset: tuple[float, float] | None = None
        # reproducible but time-varying seed if not provided
        if seed is None:
            seed = int(time.time() * 1000) % 999999
        import numpy as np

        self._rng = np.random.default_rng(int(seed))
        self._last_step_time: float = 0.0
        self._waypoint: tuple[float, float] | None = None

    def reset(self) -> None:
        """Reset scan on entering SEARCHING (clears dwell/offset)."""
        self._step = 0
        self._dwell_counter = 0
        self._cached_offset = None
        self._waypoint: tuple[float, float] | None = None

    def next(
        self,
        dt: float = 0.033,
        fov_w: float = 640.0,
        fov_h: float = 480.0,
        current_pan: float | None = None,
        current_tilt: float | None = None,
        scene_bounds: tuple[int, int] | None = None,
    ) -> tuple[float, float]:
        """
        Return (d_pan, d_tilt) delta in px for this tick (slew-limited by caller via camera.move).

        Random: waypoint-based uniform sampling (covers world) with dwell.
        Spiral/Raster: step-based with dwell hold.
        If current_pan/tilt + scene_bounds provided, RANDOM uses waypoint pursuit
        (guarantees eventual coverage); otherwise falls back to jitter walk.
        """
        # dwell: hold same offset for dwell_frames ticks
        if self._cached_offset is not None and self._dwell_counter < self.dwell_frames - 1:
            self._dwell_counter += 1
            # for random waypoint mode, keep moving toward waypoint during dwell
            if self.pattern == ScanPattern.RANDOM and current_pan is not None and hasattr(self, "_waypoint") and self._waypoint is not None:
                try:
                    wx, wy = self._waypoint
                    dx = float(wx) - float(current_pan)
                    dy = float(wy) - float(current_tilt)
                    # normalize to slew-friendly step (camera.move will also clamp)
                    dist = math.hypot(dx, dy)
                    if dist < 20.0:  # reached waypoint
                        self._waypoint = None
                        self._dwell_counter = 999  # force new waypoint next call
                        return (0.0, 0.0)
                    # step toward waypoint, at most 80px per tick (before slew)
                    scale = 40.0 / max(dist, 40.0)
                    return (dx * scale, dy * scale)
                except Exception:
                    pass
                jitter = 8.0
                jx = float(self._rng.uniform(-jitter, jitter)) * 0.3
                jy = float(self._rng.uniform(-jitter, jitter)) * 0.3
                return (float(self._cached_offset[0]) * 0.15 + jx, float(self._cached_offset[1]) * 0.15 + jy)
            if self.pattern == ScanPattern.RANDOM:
                import numpy as np

                jitter = 8.0
                jx = float(self._rng.uniform(-jitter, jitter)) * 0.3
                jy = float(self._rng.uniform(-jitter, jitter)) * 0.3
                return (float(self._cached_offset[0]) * 0.15 + jx, float(self._cached_offset[1]) * 0.15 + jy)
            return (0.0, 0.0)

        # step to next cell
        self._step += 1
        self._dwell_counter = 0

        if self.pattern == ScanPattern.RANDOM:
            # Waypoint pursuit if we know where camera is — uniform coverage per spec
            if current_pan is not None and current_tilt is not None and scene_bounds is not None:
                try:
                    # generate new waypoint if needed or reached
                    need_new = False
                    if not hasattr(self, "_waypoint") or self._waypoint is None:
                        need_new = True
                    else:
                        wx, wy = self._waypoint  # type: ignore
                        if math.hypot(wx - float(current_pan), wy - float(current_tilt)) < 25.0:
                            need_new = True
                    if need_new:
                        sw, sh = scene_bounds
                        # uniform in scene interior (avoid edges by FOV/2)
                        import numpy as np

                        fx, fy = float(fov_w), float(fov_h)
                        lo_x, hi_x = fx / 2 + 20, sw - fx / 2 - 20
                        lo_y, hi_y = fy / 2 + 20, sh - fy / 2 - 20
                        lo_x, hi_x = max(0, lo_x), max(lo_x + 1, hi_x)
                        lo_y, hi_y = max(0, lo_y), max(lo_y + 1, hi_y)
                        wx = float(self._rng.uniform(lo_x, hi_x))
                        wy = float(self._rng.uniform(lo_y, hi_y))
                        self._waypoint = (wx, wy)
                    wx, wy = self._waypoint  # type: ignore
                    dx = float(wx) - float(current_pan)
                    dy = float(wy) - float(current_tilt)
                    dist = math.hypot(dx, dy)
                    if dist < 1e-6:
                        self._waypoint = None
                        return (0.0, 0.0)
                    # step 40px toward waypoint (slew will clamp to ~26)
                    scale = min(1.0, 40.0 / dist)
                    off = (dx * scale, dy * scale)
                    self._cached_offset = off
                    return off
                except Exception:
                    pass
            # fallback jitter walk (no position aware)
            dx, dy = SearchingStrategy.random_offset(self.scan_radius, self._rng)
            scale = float(dt) / 0.033
            dx *= min(scale, 1.5)
            dy *= min(scale, 1.5)
            if self._cached_offset is not None:
                dx = dx * 0.6 + self._cached_offset[0] * 0.4
                dy = dy * 0.6 + self._cached_offset[1] * 0.4
            self._cached_offset = (float(dx), float(dy))
            return self._cached_offset
        elif self.pattern == ScanPattern.SPIRAL:
            off = SearchingStrategy.spiral_offset(self._step, self.k)
            self._cached_offset = off
            return off
        else:  # raster
            off = SearchingStrategy.raster_offset(self._step, fov_w, fov_h)
            self._cached_offset = off
            return off

    def set_pattern(self, pattern: ScanPattern | str) -> None:
        try:
            pat = ScanPattern(pattern) if isinstance(pattern, str) else pattern  # type: ignore
            if isinstance(pat, str):
                pat = ScanPattern(pat)
            self.pattern = pat
            self.reset()
        except Exception:
            pass