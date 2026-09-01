"""
Module: searching.scanner
Purpose: Active-search scan geometries — future drive for camera when SEARCHING.
Public API: ScanPattern, SearchingStrategy
Notes: Stateless helpers that propose next pan/tilt offset when no lock.
       Currently not wired into control loop (future upgrade), but isolated here
       so SEARCHING logic is extensible without touching tracking/state.py.
"""

from __future__ import annotations

import math
from enum import Enum

# ============================================================
# SECTION: ScanPattern — enum of sweep geometries
# ============================================================

class ScanPattern(Enum):
    SPIRAL = "spiral"
    RASTER = "raster"
    RANDOM = "random"

# ============================================================
# SECTION: SearchingStrategy — proposes search offsets
# ============================================================

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
