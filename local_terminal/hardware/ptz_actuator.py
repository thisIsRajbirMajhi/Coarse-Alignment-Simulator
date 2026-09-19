# local_terminal/ptz_actuator.py - Module 10: PTZ Actuator Model (§22).
from __future__ import annotations

import collections
import math

import numpy as np


class PTZActuatorModel:
    """Controller command -> latency -> accel limit -> speed limit ->
    backlash -> actual motion. Never teleports (§22)."""

    def __init__(self, ptz_config=None, realism_config=None, angular_model=None,
                 scene_bounds=(2000, 2000), fov_size=(640, 480), rng=None):
        self.ptz = ptz_config
        self.realism = realism_config
        self.angular = angular_model
        self.scene_bounds = scene_bounds
        self.fov_size = fov_size
        self._rng = rng if rng is not None else np.random.default_rng()
        self.pan = 0.0
        self.tilt = 0.0
        self._time = 0.0
        self._pending: collections.deque = collections.deque()
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_dir_x = 0
        self._last_dir_y = 0
        self._backlash_x = 0.0
        self._backlash_y = 0.0
        self._enc_x = 0.0
        self._enc_y = 0.0
        self.ptz_state = "IDLE"

    def bind(self, ptz_config=None, realism_config=None, angular_model=None,
             scene_bounds=None, fov_size=None):
        if ptz_config is not None:
            self.ptz = ptz_config
        if realism_config is not None:
            self.realism = realism_config
        if angular_model is not None:
            self.angular = angular_model
        if scene_bounds is not None:
            self.scene_bounds = scene_bounds
        if fov_size is not None:
            self.fov_size = fov_size

    # -- ranges ---------------------------------------------------------
    def _ranges(self):
        w, h = self.scene_bounds
        fw, fh = self.fov_size
        try:
            cmin = float(self.ptz.pan_min) if float(self.ptz.pan_min) > 0 else fw / 2.0
            cmax = float(self.ptz.pan_max) if float(self.ptz.pan_max) > 0 else w - fw / 2.0
        except Exception:
            cmin, cmax = fw / 2.0, w - fw / 2.0
        try:
            tmin = float(self.ptz.tilt_min) if float(self.ptz.tilt_min) > 0 else fh / 2.0
            tmax = float(self.ptz.tilt_max) if float(self.ptz.tilt_max) > 0 else h - fh / 2.0
        except Exception:
            tmin, tmax = fh / 2.0, h - fh / 2.0
        lo, hi = max(fw / 2.0, cmin), min(w - fw / 2.0, cmax)
        if lo > hi:
            lo, hi = fw / 2.0, w - fw / 2.0
        lo2, hi2 = max(fh / 2.0, tmin), min(h - fh / 2.0, tmax)
        if lo2 > hi2:
            lo2, hi2 = fh / 2.0, h - fh / 2.0
        return (lo, hi), (lo2, hi2)

    def _px_per_deg(self, is_pan: bool) -> float:
        try:
            scale = float(self.angular.pixel_to_angle_x if is_pan else self.angular.pixel_to_angle_y) * 0.001
            return 17.453292519943295 / max(1e-6, scale)
        except Exception:
            return 800.0

    def command_delta(self, d_pan: float, d_tilt: float, dt: float) -> None:
        dt = float(dt)
        try:
            latency_s = float(self.ptz.latency) / 1000.0
        except Exception:
            latency_s = 0.012
        try:
            jit = float(self.realism.latency_jitter)
        except Exception:
            jit = 0.0
        if jit > 1e-9 and latency_s > 1e-6:
            try:
                j = float(np.clip(self._rng.normal(0, jit), -jit * 2.5, jit * 2.5)) / 1000.0
                latency_s = max(0.0, latency_s + j)
            except Exception:
                pass
        if latency_s <= 1e-6:
            self._apply(float(d_pan), float(d_tilt), dt if dt > 1e-9 else 0.033)
        else:
            self._pending.append((self._time + latency_s, float(d_pan), float(d_tilt), float(dt)))
            while len(self._pending) > 32:
                self._pending.popleft()

    def advance(self, dt: float) -> tuple[float, float]:
        prev = (self.pan, self.tilt)
        self._time += float(dt)
        while self._pending and self._pending[0][0] <= self._time:
            _, dp, dtl, qdt = self._pending.popleft()
            self._apply(dp, dtl, qdt)
        if dt > 1e-9:
            vx = (self.pan - prev[0]) / dt
            vy = (self.tilt - prev[1]) / dt
        else:
            vx = vy = 0.0
        return vx, vy

    def _apply(self, d_pan: float, d_tilt: float, dt: float) -> None:
        # backlash
        try:
            bl = float(self.realism.backlash)
        except Exception:
            bl = 0.0
        d_pan = self._backlash(d_pan, True, bl)
        d_tilt = self._backlash(d_tilt, False, bl)
        # slew
        d_pan = self._slew(d_pan, dt, True)
        d_tilt = self._slew(d_tilt, dt, False)
        # accel
        if dt > 1e-9:
            des_vx, des_vy = d_pan / dt, d_tilt / dt
            lim_vx = self._accel(des_vx, self._last_vx, dt, True)
            lim_vy = self._accel(des_vy, self._last_vy, dt, False)
            d_pan, d_tilt = lim_vx * dt, lim_vy * dt
            self._last_vx, self._last_vy = lim_vx, lim_vy
        # quantize
        try:
            res = float(self.ptz.resolution)
        except Exception:
            res = 0.1
        if res > 1e-6:
            d_pan = round(d_pan / res) * res
            d_tilt = round(d_tilt / res) * res
        old = (self.pan, self.tilt)
        self.pan += d_pan
        self.tilt += d_tilt
        (plo, phi), (tlo, thi) = self._ranges()
        at_limit = False
        if self.pan <= plo or self.pan >= phi or self.tilt <= tlo or self.tilt >= thi:
            at_limit = True
        self.pan = float(np.clip(self.pan, plo, phi))
        self.tilt = float(np.clip(self.tilt, tlo, thi))
        if abs(self.pan - old[0]) > 1e-3 or abs(self.tilt - old[1]) > 1e-3:
            self.ptz_state = "LIMIT_REACHED" if at_limit else "MOVING"
        else:
            self.ptz_state = "AT_POSITION" if at_limit else "IDLE"
        # encoder OU noise
        try:
            sigma = float(self.realism.encoder_sigma)
        except Exception:
            sigma = 0.0
        if sigma > 1e-9 and dt > 1e-9:
            a = math.exp(-float(dt) / 0.05)
            w = math.sqrt(max(0.0, 1.0 - a * a))
            try:
                nx = float(np.clip(self._rng.normal(0, sigma), -sigma * 3, sigma * 3))
                ny = float(np.clip(self._rng.normal(0, sigma), -sigma * 3, sigma * 3))
                self._enc_x = a * self._enc_x + w * nx
                self._enc_y = a * self._enc_y + w * ny
            except Exception:
                pass

    def _backlash(self, delta: float, is_pan: bool, bl: float) -> float:
        if bl <= 1e-6 or abs(delta) < 1e-9:
            return delta
        s = 1 if delta > 0 else -1
        last = self._last_dir_x if is_pan else self._last_dir_y
        pend = self._backlash_x if is_pan else self._backlash_y
        if last != 0 and s != last:
            pend = bl
        if pend > 1e-9:
            if abs(delta) >= pend:
                delta = delta - math.copysign(pend, delta)
                pend = 0.0
            else:
                pend -= abs(delta)
                delta = 0.0
        if is_pan:
            self._last_dir_x, self._backlash_x = s, pend
        else:
            self._last_dir_y, self._backlash_y = s, pend
        return delta

    def _slew(self, delta: float, dt: float, is_pan: bool) -> float:
        if dt <= 1e-9:
            return delta
        try:
            deg = float(self.ptz.pan_speed if is_pan else self.ptz.tilt_speed)
        except Exception:
            deg = 5.0
        max_rate = deg * self._px_per_deg(is_pan)
        if max_rate <= 1e-6:
            return delta
        return float(np.clip(delta, -max_rate * dt, max_rate * dt))

    def _accel(self, desired_v: float, last_v: float, dt: float, is_pan: bool) -> float:
        if dt <= 1e-9:
            return desired_v
        try:
            max_deg = float(self.realism.max_acceleration)
        except Exception:
            return desired_v
        max_a = max_deg * self._px_per_deg(is_pan)
        dv = desired_v - last_v
        if abs(dv) > max_a * dt:
            desired_v = last_v + float(np.clip(dv, -max_a * dt, max_a * dt))
        return desired_v

    def flush(self) -> None:
        while self._pending:
            _, dp, dtl, qdt = self._pending.popleft()
            self._apply(dp, dtl, qdt if qdt > 1e-9 else 0.033)
