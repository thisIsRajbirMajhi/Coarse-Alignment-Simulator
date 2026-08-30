"""
Module: camera.ptz_camera
Purpose: Virtual pan-tilt camera with full mechanics simulation.
Public API: PTZCamera
Architecture:
  - constants.py : CAMERA_LIMITS/DEFAULTS (FOV, slew, resolution, latency, pan/tilt)
  - config.py    : CameraConfig (11 params, validated, scene-aware autos)
  - optics.py    : pixel ↔ mrad/µrad conversions
  - ptz_camera.py: PTZCamera — FOV cropping + pan/tilt mechanics + latency queue
Notes:
  - Pan/tilt stored as scene-center (x,y). FOV rect derived from center.
  - Mechanics: max slew rate caps delta per tick, resolution quantizes steps,
    latency queues moves, pan/tilt ranges clamp to scene + configured min/max.
  - Home/centre is default on start/reset.
  - Capture() remains sole external API — swappable without touching other modules.
"""

from __future__ import annotations

import collections
import math
import time

import numpy as np

from camera.config import CameraConfig
from camera.optics import pixel_to_mrad, pixel_to_urad

# ============================================================
# SECTION: PTZCamera — Full mechanics
# ============================================================

class PTZCamera:
    """
    Virtual pan-tilt camera — FOV cropping with actuator-realistic mechanics.

    Parameters via CameraConfig (11):
      FOV: fov_width, fov_height
      Pan-Tilt: pan_min/max, tilt_min/max, home_pan/tilt, max_slew_rate, resolution, latency_ms
      Display: viewport_width/height, god_width/height (used by GUI, stored here for snapshot)
      Units: pixel_scale_mrad (px → mrad)

    Mechanics:
      - Slew limiting: |delta| ≤ max_slew_rate * dt  (per axis)
      - Resolution: delta quantized to nearest resolution step
      - Latency: commands queued for latency_ms, executed on update(dt)
      - Ranges: pan/tilt clamped to [pan_min, pan_max] ∩ [fov/2, W-fov/2]
    """

    def __init__(
        self,
        fov_width: int = 250,
        fov_height: int = 250,
        pan: float = 0.0,
        tilt: float = 0.0,
        scene_bounds: tuple[int, int] = (1000, 1000),
        config: CameraConfig | None = None,
    ):
        # If config supplied, it drives construction (validated against scene)
        if config is not None:
            cfg = config.validate(scene_bounds)
            self.config = cfg
            self.fov_width = int(cfg.fov_width)
            self.fov_height = int(cfg.fov_height)
            self.scene_bounds = scene_bounds
            # Home/centre is default pan/tilt if not explicitly passed
            if pan == 0.0 and tilt == 0.0 and cfg.home_pan is not None:
                pan = float(cfg.home_pan)
                tilt = float(cfg.home_tilt)
        else:
            # Legacy path — preserve headless test behavior: unlimited slew, no quantization/latency
            self.config = CameraConfig(
                fov_width=int(fov_width), fov_height=int(fov_height),
                home_pan=float(pan) if pan != 0.0 else None,
                home_tilt=float(tilt) if tilt != 0.0 else None,
                max_slew_rate=1e6, resolution=0.0, latency_ms=0,
                viewport_width=400, viewport_height=300, god_width=400, god_height=300,
                pixel_scale_mrad=0.035,
            ).validate(scene_bounds)
            self.fov_width = int(fov_width)
            self.fov_height = int(fov_height)
            self.scene_bounds = scene_bounds

        # Internal time for latency queue (seconds)
        self._time: float = 0.0
        # Queue of pending moves: deque of (execute_time, d_pan, d_tilt)
        self._pending: collections.deque[tuple[float, float, float]] = collections.deque()
        # Effective pan/tilt — clamped to both scene-derived and configured ranges
        self.pan = float(pan)
        self.tilt = float(tilt)
        self._clamp_to_range()

        # Keep FOV in sync with config
        self._sync_fov_from_config()

    # ========================================================
    # Private — helpers for mechanics
    # ========================================================

    def _sync_fov_from_config(self) -> None:
        self.fov_width = int(self.config.fov_width)
        self.fov_height = int(self.config.fov_height)

    def _effective_pan_range(self) -> tuple[float, float]:
        # Configured range ∩ scene-derived range
        w, _ = self.scene_bounds
        scene_min = self.fov_width / 2
        scene_max = w - self.fov_width / 2
        cfg_min = float(self.config.pan_min if self.config.pan_min is not None else scene_min)
        cfg_max = float(self.config.pan_max if self.config.pan_max is not None else scene_max)
        # Intersect
        lo = max(scene_min, cfg_min)
        hi = min(scene_max, cfg_max)
        if lo > hi:
            lo, hi = scene_min, scene_max
        return (lo, hi)

    def _effective_tilt_range(self) -> tuple[float, float]:
        _, h = self.scene_bounds
        scene_min = self.fov_height / 2
        scene_max = h - self.fov_height / 2
        cfg_min = float(self.config.tilt_min if self.config.tilt_min is not None else scene_min)
        cfg_max = float(self.config.tilt_max if self.config.tilt_max is not None else scene_max)
        lo = max(scene_min, cfg_min)
        hi = min(scene_max, cfg_max)
        if lo > hi:
            lo, hi = scene_min, scene_max
        return (lo, hi)

    def _clamp_to_range(self) -> None:
        pan_lo, pan_hi = self._effective_pan_range()
        tilt_lo, tilt_hi = self._effective_tilt_range()
        self.pan = float(np.clip(self.pan, pan_lo, pan_hi))
        self.tilt = float(np.clip(self.tilt, tilt_lo, tilt_hi))

    def _quantize(self, delta: float) -> float:
        res = float(self.config.resolution)
        if res <= 1e-6:
            return float(delta)
        # Quantize to nearest resolution step (preserves sign)
        steps = round(delta / res)
        return float(steps * res)

    def _slew_limit(self, delta: float, dt: float) -> float:
        max_rate = float(self.config.max_slew_rate)
        if max_rate <= 1e-6:
            return float(delta)
        max_delta = max_rate * float(dt)
        return float(np.clip(delta, -max_delta, max_delta))

    def _apply_delta(self, d_pan: float, d_tilt: float, dt: float) -> None:
        # Slew limit then quantize
        d_pan = self._slew_limit(d_pan, dt)
        d_tilt = self._slew_limit(d_tilt, dt)
        d_pan = self._quantize(d_pan)
        d_tilt = self._quantize(d_tilt)
        self.pan += float(d_pan)
        self.tilt += float(d_tilt)
        self._clamp_to_range()

    # ========================================================
    # Public — movement with latency queue
    # ========================================================

    def move(self, d_pan: float, d_tilt: float, dt: float | None = None) -> None:
        """
        Queue or apply relative pan/tilt correction.

        - If latency_ms == 0 and dt is not None, applies with slew+quantize+clamp.
        - If latency_ms > 0, queues for execution after latency_ms.
        - If dt is None (legacy direct call, e.g., tests), applies immediately
          without slew limiting (only quantize+clamp) for back-compat.
        """
        # Legacy direct path — no slew limiting (tests expect large jumps)
        if dt is None:
            # Direct apply (quantize + clamp only, no slew, no latency queue)
            d_pan = self._quantize(d_pan)
            d_tilt = self._quantize(d_tilt)
            self.pan += float(d_pan)
            self.tilt += float(d_tilt)
            self._clamp_to_range()
            return
        latency_s = float(self.config.latency_ms) / 1000.0
        if latency_s <= 1e-6:
            self._apply_delta(d_pan, d_tilt, dt)
        else:
            due = self._time + latency_s
            self._pending.append((due, float(d_pan), float(d_tilt)))

    def update(self, dt: float) -> None:
        """
        Advance internal time and execute due pending moves.

        Call once per tick (main loop) — processes latency queue with
        per-command dt for correct slew limiting (uses dt of the tick).
        """
        self._time += float(dt)
        # Execute all due moves in order (FIFO)
        while self._pending and self._pending[0][0] <= self._time:
            _, d_pan, d_tilt = self._pending.popleft()
            # Use current tick dt for slew (approx; pending dt not stored, use passed dt)
            self._apply_delta(d_pan, d_tilt, dt)

    def flush_pending(self) -> None:
        """Immediately execute all queued moves (used on reset)."""
        while self._pending:
            _, d_pan, d_tilt = self._pending.popleft()
            self._apply_delta(d_pan, d_tilt, 0.033)

    def set_position(self, pan: float, tilt: float) -> None:
        """Set absolute pan/tilt, clamped to effective range (bypasses queue)."""
        # Clear pending to avoid jump after set
        self._pending.clear()
        self.pan = float(pan)
        self.tilt = float(tilt)
        self._clamp_to_range()

    def go_home(self) -> None:
        """Move to home/centre (configured or scene centre)."""
        self.set_position(float(self.config.home_pan), float(self.config.home_tilt))

    def apply_config(self, config: CameraConfig, scene_bounds: tuple[int,int] | None = None) -> None:
        """
        Hot-apply a new CameraConfig (preserves pan/tilt, updates FOV/ranges).

        If scene_bounds provided, re-validates ranges against new scene.
        """
        if scene_bounds is not None:
            self.scene_bounds = scene_bounds
            config.validate(scene_bounds)
        else:
            config.validate(self.scene_bounds)
        self.config = config
        self._sync_fov_from_config()
        # Re-clamp current pan/tilt to new ranges
        self._clamp_to_range()
        # Clear stale pending that may exceed new limits
        # (keep queue but will be clamped on execution)

    # ========================================================
    # Public — FOV rect and capture (pure cropping, no mechanics)
    # ========================================================

    def get_fov_rect(self) -> tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) of current FOV window in scene coords."""
        x0 = int(self.pan - self.fov_width / 2)
        y0 = int(self.tilt - self.fov_height / 2)
        return x0, y0, x0 + self.fov_width, y0 + self.fov_height

    def get_pan_range(self) -> tuple[float, float]:
        return self._effective_pan_range()

    def get_tilt_range(self) -> tuple[float, float]:
        return self._effective_tilt_range()

    def get_home(self) -> tuple[float, float]:
        return (float(self.config.home_pan), float(self.config.home_tilt))

    def capture(self, scene_frame: np.ndarray) -> np.ndarray:
        """Crop the camera's current FOV window out of the full scene frame."""
        h, w = scene_frame.shape[:2]
        x0, y0, x1, y1 = self.get_fov_rect()
        x0c, y0c = max(x0, 0), max(y0, 0)
        x1c, y1c = min(x1, w), min(y1, h)

        out = np.zeros((self.fov_height, self.fov_width, 3), dtype=scene_frame.dtype)
        if x1c > x0c and y1c > y0c:
            crop = scene_frame[y0c:y1c, x0c:x1c]
            out[y0c - y0: y0c - y0 + crop.shape[0],
                x0c - x0: x0c - x0 + crop.shape[1]] = crop
        return out

    # ========================================================
    # Reporting — angular errors
    # ========================================================

    def pixel_error_to_mrad(self, px_error: float) -> float:
        return pixel_to_mrad(px_error, self.config.pixel_scale_mrad)

    def pixel_error_to_urad(self, px_error: float) -> float:
        return pixel_to_urad(px_error, self.config.pixel_scale_mrad)

    def pending_queue_len(self) -> int:
        return len(self._pending)
