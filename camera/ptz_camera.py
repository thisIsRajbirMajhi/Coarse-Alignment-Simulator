# camera/ptz_camera.py - Virtual pan-tilt camera with full mechanics simulation

from __future__ import annotations

import collections
import math
import time

import numpy as np

from camera.config import CameraConfig
from camera.optics import pixel_to_mrad, pixel_to_urad

class PTZCamera:
    """
    Virtual pan-tilt camera — FOV cropping with actuator-realistic mechanics.

    Parameters via CameraConfig (11):
      FOV: fov_width, fov_height
      Pan-Tilt: pan_min/max, tilt_min/max, home_pan/tilt, max_slew_rate, resolution, latency_ms
      Display: viewport_width/height, god_width/height (used by GUI, stored here for snapshot)
      Units: pixel_scale_mrad (px → mrad)
      Optics: vignetting (sensor/image-space radial falloff, follows camera FOV)

    Mechanics:
      - Slew limiting: |delta| ≤ max_slew_rate * dt  (per axis)
      - Resolution: delta quantized to nearest resolution step
      - Latency: commands queued for latency_ms, executed on update(dt)
      - Ranges: pan/tilt clamped to [pan_min, pan_max] ∩ [fov/2, W-fov/2]
      - Vignetting: radial darkening centered on FOV (image-space), NOT world centre.
        Applied at capture stage so it follows camera pan/tilt.
    """

    def __init__(
        self,
        fov_width: int = 250,
        fov_height: int = 250,
        pan: float = 0.0,
        tilt: float = 0.0,
        scene_bounds: tuple[int, int] = (1000, 1000),
        config: CameraConfig | None = None,
        vignetting: float = 0.0,
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

        # Vignetting — image-space (sensor) effect, follows camera FOV.
        # Stored here so capture() can apply without Scene world-baking.
        # vignetting param overrides config if explicitly passed, else check
        # config.vignetting (if CameraConfig carries it) or default 0.
        _vign = float(vignetting)
        if _vign == 0.0 and config is not None and hasattr(config, "vignetting"):
            try:
                _vign = float(getattr(config, "vignetting", 0.0) or 0.0)
            except:
                _vign = 0.0
        if _vign == 0.0 and config is not None and hasattr(config, "vignetting_strength"):
            try:
                _vign = float(getattr(config, "vignetting_strength", 0.0) or 0.0)
            except:
                _vign = 0.0
        self.vignetting: float = float(np.clip(_vign, 0.0, 0.92))

        # Internal time for latency queue (seconds)
        self._time: float = 0.0
        # Queue of pending moves: deque of (execute_time, d_pan, d_tilt, dt)
        self._pending: collections.deque[tuple[float, float, float, float]] = collections.deque()
        # Effective pan/tilt — clamped to both scene-derived and configured ranges
        self.pan = float(pan)
        self.tilt = float(tilt)
        self._clamp_to_range()

        # Realism state — acceleration, backlash, encoder
        self._last_vx: float = 0.0
        self._last_vy: float = 0.0
        self._last_dir_x: int = 0
        self._last_dir_y: int = 0
        self._backlash_pending_x: float = 0.0
        self._backlash_pending_y: float = 0.0

        # Keep FOV in sync with config
        self._sync_fov_from_config()

    # Private — helpers for mechanics

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
        steps = round(delta / res)
        return float(steps * res)

    def _slew_limit(self, delta: float, dt: float, is_pan: bool = True) -> float:
        # Single source: derived max_slew_rate already validated, but recompute from deg for correctness
        try:
            if is_pan:
                deg = float(self.config.max_pan_speed_deg)
            else:
                deg = float(self.config.max_tilt_speed_deg)
            # Use axis-specific scale for accuracy
            scale = float(self.config.pixel_scale_mrad) if is_pan else float(getattr(self.config, "pixel_scale_mrad_y", self.config.pixel_scale_mrad))
            px_per_deg = 17.453292519943295 / max(1e-6, scale)
            max_rate = deg * px_per_deg
        except:
            max_rate = float(self.config.max_slew_rate)
        if max_rate <= 1e-6:
            return float(delta)
        max_delta = max_rate * float(dt)
        return float(np.clip(delta, -max_delta, max_delta))

    def _accel_limit(self, desired_v: float, last_v: float, dt: float) -> float:
        """Limit acceleration in px/s² derived from max_accel_deg."""
        try:
            max_accel_deg = float(getattr(self.config, "max_accel_deg", 120.0))
            scale = float(self.config.pixel_scale_mrad)
            px_per_deg = 17.453292519943295 / max(1e-6, scale)
            max_accel = max_accel_deg * px_per_deg  # px/s²
            max_dv = max_accel * float(dt)
            dv = float(desired_v) - float(last_v)
            if abs(dv) > max_dv:
                desired_v = float(last_v) + float(np.clip(dv, -max_dv, max_dv))
        except Exception:
            pass
        return float(desired_v)

    def _apply_backlash(self, delta: float, is_pan: bool) -> float:
        """Backlash deadband on direction reversal — requires extra travel before moving."""
        try:
            backlash = float(getattr(self.config, "backlash_px", 0.25))
        except Exception:
            backlash = 0.0
        if backlash <= 1e-6 or abs(delta) < 1e-9:
            return float(delta)
        # Track direction
        dir_sign = 1 if delta > 1e-9 else -1 if delta < -1e-9 else 0
        last_dir = self._last_dir_x if is_pan else self._last_dir_y
        pending = self._backlash_pending_x if is_pan else self._backlash_pending_y
        if dir_sign != 0 and last_dir != 0 and dir_sign != last_dir:
            # Direction reversal → need to traverse backlash
            pending = backlash
        if pending > 1e-9:
            # Consume delta to overcome backlash
            if abs(delta) >= pending:
                delta = float(delta - math.copysign(pending, delta))
                pending = 0.0
            else:
                pending -= abs(delta)
                delta = 0.0
        if dir_sign != 0:
            if is_pan:
                self._last_dir_x = dir_sign
                self._backlash_pending_x = pending
            else:
                self._last_dir_y = dir_sign
                self._backlash_pending_y = pending
        else:
            if is_pan:
                self._backlash_pending_x = pending
            else:
                self._backlash_pending_y = pending
        return float(delta)

    def _apply_delta(self, d_pan: float, d_tilt: float, dt: float) -> None:
        # Backlash first (static deadband)
        d_pan = self._apply_backlash(d_pan, is_pan=True)
        d_tilt = self._apply_backlash(d_tilt, is_pan=False)
        # Slew (velocity) limit
        d_pan = self._slew_limit(d_pan, dt, is_pan=True)
        d_tilt = self._slew_limit(d_tilt, dt, is_pan=False)
        # Acceleration limit — convert delta→velocity, limit, back to delta
        if dt > 1e-9:
            des_vx = float(d_pan) / float(dt)
            des_vy = float(d_tilt) / float(dt)
            lim_vx = self._accel_limit(des_vx, self._last_vx, dt)
            lim_vy = self._accel_limit(des_vy, self._last_vy, dt)
            d_pan = float(lim_vx * dt)
            d_tilt = float(lim_vy * dt)
            self._last_vx = float(lim_vx)
            self._last_vy = float(lim_vy)
        # Quantize to encoder resolution
        d_pan = self._quantize(d_pan)
        d_tilt = self._quantize(d_tilt)
        self.pan += float(d_pan)
        self.tilt += float(d_tilt)
        self._clamp_to_range()
        # Encoder noise — small readout error (does not affect true pan/tilt much, but adds measurement jitter)
        try:
            sigma_enc = float(getattr(self.config, "encoder_sigma_px", 0.04))
            if sigma_enc > 1e-9 and (abs(d_pan) > 1e-6 or abs(d_tilt) > 1e-6):
                # Only when moving, add tiny measurement noise to pan/tilt reading (not command)
                # Store true pan but report noisy via property? Keep simple: add to pan/tilt with small sigma
                # To keep deterministic for tests with sigma 0.04, use truncated Gaussian ±3σ
                npx = float(np.clip(np.random.normal(0, sigma_enc), -sigma_enc*3, sigma_enc*3))
                npy = float(np.clip(np.random.normal(0, sigma_enc), -sigma_enc*3, sigma_enc*3))
                # Apply as measurement bias, not cumulative drift — add then clamp
                # We model as small random walk bias 0.3×sigma
                self.pan += npx * 0.3
                self.tilt += npy * 0.3
                self._clamp_to_range()
        except Exception:
            pass

    # Public — movement with latency queue (with jitter)

    def move(self, d_pan: float, d_tilt: float, dt: float | None = None) -> None:
        """
        Queue or apply relative pan/tilt correction.

        - If latency_ms == 0 and dt is not None, applies with slew+accel/backlash+quantize+clamp.
        - If latency_ms > 0, queues for execution after latency_ms + jitter.
        - If dt is None (legacy direct call, e.g., tests), applies immediately
          without slew/accel limiting (only quantize+clamp) for back-compat.
        """
        if dt is None:
            # Legacy direct path — no slew/accel (tests expect large jumps)
            d_pan = self._quantize(d_pan)
            d_tilt = self._quantize(d_tilt)
            self.pan += float(d_pan)
            self.tilt += float(d_tilt)
            self._clamp_to_range()
            return
        latency_s = float(self.config.latency_ms) / 1000.0
        # Latency jitter: N(0, jitter_ms) clipped ±3σ, per-command
        try:
            jit_ms = float(getattr(self.config, "latency_jitter_ms", 1.2))
            if jit_ms > 1e-9 and latency_s > 1e-6:
                j = float(np.clip(np.random.normal(0, jit_ms), -jit_ms*2.5, jit_ms*2.5)) / 1000.0
                latency_s = max(0.0, latency_s + j)
        except Exception:
            pass
        if latency_s <= 1e-6:
            self._apply_delta(d_pan, d_tilt, dt)
        else:
            due = self._time + latency_s
            self._pending.append((due, float(d_pan), float(d_tilt), float(dt)))

    def update(self, dt: float) -> None:
        """
        Advance internal time and execute due pending moves.

        Call once per tick — processes latency queue with per-command dt for correct
        slew/accel limiting (uses dt of the tick where command was enqueued).
        """
        self._time += float(dt)
        while self._pending and self._pending[0][0] <= self._time:
            item = self._pending.popleft()
            if len(item) == 4:
                _, d_pan, d_tilt, qdt = item
                self._apply_delta(d_pan, d_tilt, float(qdt))
            else:
                _, d_pan, d_tilt = item  # back-compat
                self._apply_delta(d_pan, d_tilt, dt)

    def flush_pending(self) -> None:
        """Immediately execute all queued moves (used on reset)."""
        while self._pending:
            item = self._pending.popleft()
            if len(item) == 4:
                _, d_pan, d_tilt, qdt = item
                self._apply_delta(d_pan, d_tilt, float(qdt))
            else:
                _, d_pan, d_tilt = item
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

    def set_vignetting(self, strength: float) -> None:
        """Set vignetting strength (0..0.92) for camera image-space effect."""
        self.vignetting = float(np.clip(float(strength), 0.0, 0.92))

    def apply_config(self, config: CameraConfig, scene_bounds: tuple[int,int] | None = None) -> None:
        """
        Hot-apply a new CameraConfig (preserves pan/tilt, updates FOV/ranges).

        If scene_bounds provided, re-validates ranges against new scene.
        Also syncs vignetting if config carries it (for camera-stage vignetting).
        """
        if scene_bounds is not None:
            self.scene_bounds = scene_bounds
            config.validate(scene_bounds)
        else:
            config.validate(self.scene_bounds)
        self.config = config
        self._sync_fov_from_config()
        # Sync vignetting if present on config (camera-stage migration)
        if hasattr(config, "vignetting"):
            try:
                self.set_vignetting(float(getattr(config, "vignetting", self.vignetting) or 0.0))
            except:
                pass
        if hasattr(config, "vignetting_strength"):
            try:
                self.set_vignetting(float(getattr(config, "vignetting_strength", self.vignetting) or 0.0))
            except:
                pass
        # Re-clamp current pan/tilt to new ranges
        self._clamp_to_range()
        # Clear stale pending that may exceed new limits
        # (keep queue but will be clamped on execution)

    # Public — FOV rect and capture (pure cropping, no mechanics)

    def get_fov_rect(self) -> tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) of current FOV window in scene coords."""
        x0 = int(round(self.pan - self.fov_width / 2))
        y0 = int(round(self.tilt - self.fov_height / 2))
        return x0, y0, x0 + self.fov_width, y0 + self.fov_height

    def get_pan_range(self) -> tuple[float, float]:
        return self._effective_pan_range()

    def get_tilt_range(self) -> tuple[float, float]:
        return self._effective_tilt_range()

    def get_home(self) -> tuple[float, float]:
        return (float(self.config.home_pan), float(self.config.home_tilt))

    def capture(self, scene_frame: np.ndarray, vignetting: float | None = None) -> np.ndarray:
        """
        Crop the camera's current FOV window out of the full scene frame.

        Applies vignetting at camera image stage (sensor-space) so dark corners
        follow the camera FOV, not the world centre. Pass vignetting strength
        explicitly (0..0.92) or rely on self.vignetting set via set_vignetting().
        """
        h, w = scene_frame.shape[:2]
        x0, y0, x1, y1 = self.get_fov_rect()
        x0c, y0c = max(x0, 0), max(y0, 0)
        x1c, y1c = min(x1, w), min(y1, h)

        out = np.zeros((self.fov_height, self.fov_width, 3), dtype=scene_frame.dtype)
        if x1c > x0c and y1c > y0c:
            crop = scene_frame[y0c:y1c, x0c:x1c]
            out[y0c - y0: y0c - y0 + crop.shape[0],
                x0c - x0: x0c - x0 + crop.shape[1]] = crop

        # Vignetting — image-space (follows camera)
        vig = float(vignetting) if vignetting is not None else float(self.vignetting)
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                out = apply_vignetting(out, vig)
            except Exception:
                pass
        return out

    def capture_region(self, scene, vignetting: float | None = None) -> np.ndarray:
        """
        Optimized capture directly from Scene without rebuilding full 5000×5000.

        Uses Scene.get_region(x0,y0,x1,y1) to crop first (1.2M pixels for 640×640)
        then applies vignetting. This avoids the 5000×5000 float32 rebuild every
        33 ms. Prefer this over capture(scene.get_frame()) in hot loop.
        """
        x0, y0, x1, y1 = self.get_fov_rect()
        # Scene.get_region handles dynamic stars/haze on cropped region only
        if hasattr(scene, "get_region"):
            out = scene.get_region(x0, y0, x1, y1)
        elif hasattr(scene, "get_cropped_frame"):
            out = scene.get_cropped_frame(x0, y0, x1, y1)
        else:
            # Fallback old path
            out = self.capture(scene.get_frame(), vignetting=0)
            # vignetting will be applied below once
            vig = float(vignetting) if vignetting is not None else float(self.vignetting)
            if vig > 1e-3:
                try:
                    from environment.vignetting import apply_vignetting
                    out = apply_vignetting(out, vig)
                except Exception:
                    pass
            return out

        vig = float(vignetting) if vignetting is not None else float(self.vignetting)
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                out = apply_vignetting(out, vig)
            except Exception:
                pass
        return out

    # Reporting — angular errors

    def pixel_error_to_mrad(self, px_error: float) -> float:
        return pixel_to_mrad(px_error, self.config.pixel_scale_mrad)

    def pixel_error_to_mrad_xy(self, px_x: float, px_y: float) -> tuple[float, float]:
        from camera.optics import pixel_to_mrad_xy
        sx = float(self.config.pixel_scale_mrad)
        sy = float(getattr(self.config, "pixel_scale_mrad_y", sx))
        return pixel_to_mrad_xy(px_x, px_y, sx, sy)

    def pixel_error_to_urad(self, px_error: float) -> float:
        return pixel_to_urad(px_error, self.config.pixel_scale_mrad)

    def pending_queue_len(self) -> int:
        return len(self._pending)