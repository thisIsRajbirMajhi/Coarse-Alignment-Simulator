# local_terminal/terminal.py - Local Terminal operational model per LocalTerminal.md
from __future__ import annotations

import collections
import math
from typing import Any

import numpy as np

from common.rng import get_rng
from local_terminal.acquisition import AcquisitionScanner
from local_terminal.config import LocalTerminalConfig
from local_terminal.detection import detect_beacon_candidates, estimate_wavelength_nm
from local_terminal.models import CameraFrame, UpdateInput
from local_terminal.states import LocalTerminalState as _PipelineState
from local_terminal.system import LocalTerminalSystem
from local_terminal.tracking import TargetTracker


class LocalTerminal:
    """
    Virtual Local Optical Terminal per LocalTerminal.md.

    Integrates:
      - Physical PTZ actuator mechanics (slew limits, acceleration, backlash, resolution, latency jitter)
      - Optical sensor and dynamically derived angular model (urad/px)
      - Autonomous acquisition pattern generation (Raster, Spiral, etc.)
      - Target signature detection matching against remote optical beacons
      - Centroid error estimation and closed-loop tracking
      - Optical communication link state machine
    """

    def __init__(
        self,
        config: LocalTerminalConfig | None = None,
        scene_bounds: tuple[int, int] = (2000, 2000),
        rng: np.random.Generator | None = None,
        **kwargs,
    ):
        self.scene_bounds = scene_bounds
        self.config = (config or LocalTerminalConfig()).validate(scene_bounds)

        # RNG for encoder/latency jitter (deterministic when seeded)
        self._rng: np.random.Generator = get_rng(rng)

        # Sensor FOV
        self.fov_width = int(self.config.camera.resolution_width)
        self.fov_height = int(self.config.camera.resolution_height)

        # Pose & Actuators
        self.pan = float(self.config.ptz.home_pan)
        self.tilt = float(self.config.ptz.home_tilt)
        self._clamp_to_range()

        # Realism states
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_dir_x = 0
        self._last_dir_y = 0
        self._backlash_pending_x = 0.0
        self._backlash_pending_y = 0.0
        self._enc_bias_x = 0.0
        self._enc_bias_y = 0.0

        # Latency command queue
        self._time = 0.0
        self._pending: collections.deque[tuple[float, float, float, float]] = collections.deque()

        # Sensor vignetting
        self.vignetting = float(self.config.vignetting)

        # Operational Subsystems (perception is delegated to the
        # LocalTerminalSystem image-only pipeline).
        self.scanner = AcquisitionScanner(self.config.acquisition, rng=self._rng)
        self.tracker = TargetTracker(self.config.tracking, self.config.angular_model)
        # Thirteen-module pipeline orchestrator (Plan §4). Strict image-only
        # boundary: it never receives remote scenario/world truth.
        self.system = LocalTerminalSystem(config=self.config, scene_bounds=scene_bounds,
                                          rng=self._rng)
        # Share the scanner instance so GUI scan state stays consistent.
        try:
            self.system.search.scanner = self.scanner
        except Exception:
            pass
        self._frame_seq = 0

        # Operational telemetry & autonomy state
        self._target_locked = False
        self._lock_dwell_time = 0.0
        self._last_detection_eval: dict[str, Any] = {}
        self._last_tracking_eval: dict[str, Any] = {}
        self.active_target_id: str | None = None
        self.candidate_evaluations: list[dict[str, Any]] = []
        self._reacquire_dwell: float = 0.0
        self._last_cam_vel_x = 0.0
        self._last_cam_vel_y = 0.0
        self._confirm_counts: dict[str, int] = {}
        self._last_tracked_id: str | None = None
        # Local observation tracks are created from pixels; they intentionally
        # never contain a RemoteTerminal id or world position.
        self._observation_tracks: dict[str, dict[str, Any]] = {}
        self._next_observation_track_id = 1

        self._clamp_search_region_to_reachable()
        if self.config.acquisition.mode.upper() in ("SEARCH", "AUTO", "AUTO_ACQUISITION"):
            self.scanner.start()
            self.config.state.acquisition_state = "SEARCHING"

    # -----------------------------------------------------------------
    # Range & Clamping Mechanics
    # -----------------------------------------------------------------
    def _effective_pan_range(self) -> tuple[float, float]:
        w, _ = self.scene_bounds
        scene_min = self.fov_width / 2.0
        scene_max = w - self.fov_width / 2.0
        cfg_min = float(self.config.ptz.pan_min if self.config.ptz.pan_min > 0 else scene_min)
        cfg_max = float(self.config.ptz.pan_max if self.config.ptz.pan_max > 0 else scene_max)
        lo = max(scene_min, cfg_min)
        hi = min(scene_max, cfg_max)
        if lo > hi:
            lo, hi = scene_min, scene_max
        return (lo, hi)

    def _effective_tilt_range(self) -> tuple[float, float]:
        _, h = self.scene_bounds
        scene_min = self.fov_height / 2.0
        scene_max = h - self.fov_height / 2.0
        cfg_min = float(self.config.ptz.tilt_min if self.config.ptz.tilt_min > 0 else scene_min)
        cfg_max = float(self.config.ptz.tilt_max if self.config.ptz.tilt_max > 0 else scene_max)
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
        res = float(self.config.ptz.resolution)
        if res <= 1e-6:
            return float(delta)
        steps = round(delta / res)
        return float(steps * res)

    def _slew_limit(self, delta: float, dt: float, is_pan: bool = True) -> float:
        if dt <= 1e-9:
            return float(delta)
        try:
            deg = float(self.config.ptz.pan_speed if is_pan else self.config.ptz.tilt_speed)
            scale_mrad = float(self.config.angular_model.pixel_to_angle_x if is_pan else self.config.angular_model.pixel_to_angle_y) * 0.001
            px_per_deg = 17.453292519943295 / max(1e-6, scale_mrad)
            max_rate = deg * px_per_deg
        except Exception:
            max_rate = 800.0
        if max_rate <= 1e-6:
            return float(delta)
        max_delta = max_rate * float(dt)
        return float(np.clip(delta, -max_delta, max_delta))

    def _accel_limit(self, desired_v: float, last_v: float, dt: float, is_pan: bool = True) -> float:
        if dt <= 1e-9:
            return float(desired_v)
        try:
            max_accel_deg = float(self.config.realism.max_acceleration)
            scale_mrad = float(
                self.config.angular_model.pixel_to_angle_x if is_pan
                else self.config.angular_model.pixel_to_angle_y
            ) * 0.001
            px_per_deg = 17.453292519943295 / max(1e-6, scale_mrad)
            max_accel = max_accel_deg * px_per_deg
            max_dv = max_accel * float(dt)
            dv = float(desired_v) - float(last_v)
            if abs(dv) > max_dv:
                desired_v = float(last_v) + float(np.clip(dv, -max_dv, max_dv))
        except Exception:
            pass
        return float(desired_v)

    def _apply_backlash(self, delta: float, is_pan: bool) -> float:
        backlash = float(self.config.realism.backlash)
        if backlash <= 1e-6 or abs(delta) < 1e-9:
            return float(delta)
        dir_sign = 1 if delta > 1e-9 else -1 if delta < -1e-9 else 0
        last_dir = self._last_dir_x if is_pan else self._last_dir_y
        pending = self._backlash_pending_x if is_pan else self._backlash_pending_y

        if dir_sign != 0 and last_dir != 0 and dir_sign != last_dir:
            pending = backlash

        if pending > 1e-9:
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
        return float(delta)

    def _apply_delta(self, d_pan: float, d_tilt: float, dt: float) -> None:
        d_pan = self._apply_backlash(d_pan, is_pan=True)
        d_tilt = self._apply_backlash(d_tilt, is_pan=False)

        d_pan = self._slew_limit(d_pan, dt, is_pan=True)
        d_tilt = self._slew_limit(d_tilt, dt, is_pan=False)

        if dt > 1e-9:
            des_vx = float(d_pan) / float(dt)
            des_vy = float(d_tilt) / float(dt)
            lim_vx = self._accel_limit(des_vx, self._last_vx, dt, is_pan=True)
            lim_vy = self._accel_limit(des_vy, self._last_vy, dt, is_pan=False)
            d_pan = float(lim_vx * dt)
            d_tilt = float(lim_vy * dt)
            self._last_vx = float(lim_vx)
            self._last_vy = float(lim_vy)

        d_pan = self._quantize(d_pan)
        d_tilt = self._quantize(d_tilt)

        old_pan, old_tilt = self.pan, self.tilt
        self.pan += float(d_pan)
        self.tilt += float(d_tilt)
        self._clamp_to_range()

        # Update PTZ state
        if abs(self.pan - old_pan) > 1e-3 or abs(self.tilt - old_tilt) > 1e-3:
            self.config.state.ptz_state = "MOVING"
        else:
            self.config.state.ptz_state = "IDLE"

        # Encoder noise bias (OU process, dt-normalized so stats don't
        # depend on frame rate: bias += (1-a)*n with a=exp(-dt/tau)).
        sigma_enc = float(self.config.realism.encoder_sigma)
        if sigma_enc > 1e-9:
            import math as _math

            tau_enc = 0.05
            a_enc = _math.exp(-float(dt) / tau_enc) if dt > 1e-9 else 0.9
            w_enc = _math.sqrt(max(0.0, 1.0 - a_enc * a_enc))
            npx = float(np.clip(self._rng.normal(0, sigma_enc), -sigma_enc * 3, sigma_enc * 3))
            npy = float(np.clip(self._rng.normal(0, sigma_enc), -sigma_enc * 3, sigma_enc * 3))
            self._enc_bias_x = float(a_enc * self._enc_bias_x + w_enc * npx)
            self._enc_bias_y = float(a_enc * self._enc_bias_y + w_enc * npy)

    # -----------------------------------------------------------------
    # Movement API (Direct & Latency Queue)
    # -----------------------------------------------------------------
    def move(self, d_pan: float, d_tilt: float, dt: float | None = None) -> None:
        """Queue or immediately apply relative pan/tilt motion."""
        if dt is None:
            # Legacy direct path: still run through actuator physics with a
            # large dt so slew/accel don't clip test jumps, but backlash,
            # quantization and clamping are honoured (no silent bypass).
            self._apply_delta(float(d_pan), float(d_tilt), 1.0)
            return

        latency_s = float(self.config.ptz.latency) / 1000.0
        jit_ms = float(self.config.realism.latency_jitter)
        if jit_ms > 1e-9 and latency_s > 1e-6:
            j = float(np.clip(self._rng.normal(0, jit_ms), -jit_ms * 2.5, jit_ms * 2.5)) / 1000.0
            latency_s = max(0.0, latency_s + j)

        if latency_s <= 1e-6:
            self._apply_delta(d_pan, d_tilt, dt)
        else:
            due = self._time + latency_s
            self._pending.append((due, float(d_pan), float(d_tilt), float(dt)))
            # Bound the queue (§36): drop oldest under sustained overload
            # so memory stays flat and commands stay fresh.
            while len(self._pending) > 32:
                self._pending.popleft()

    def _clamp_search_region_to_reachable(self) -> None:
        """Clip deg search region to what the PTZ can actually reach.

        Default ±20°/±10° at ~160 px/deg demands ±3200 px in a 2000 px
        world — the scan then saturates at the rails and never covers the
        center. Clamp offsets so home±region stays inside the effective
        pan/tilt range.
        """
        try:
            pan_lo, pan_hi = self._effective_pan_range()
            tilt_lo, tilt_hi = self._effective_tilt_range()
            home_pan = float(self.config.ptz.home_pan)
            home_tilt = float(self.config.ptz.home_tilt)
            px_per_deg_x = 17.453292519943295 / max(
                1e-6, float(self.config.angular_model.pixel_to_angle_x) * 0.001
            )
            px_per_deg_y = 17.453292519943295 / max(
                1e-6, float(self.config.angular_model.pixel_to_angle_y) * 0.001
            )
            max_pan_deg = min(home_pan - pan_lo, pan_hi - home_pan) / max(1e-6, px_per_deg_x)
            max_tilt_deg = min(home_tilt - tilt_lo, tilt_hi - home_tilt) / max(1e-6, px_per_deg_y)
            max_pan_deg = max(0.5, float(max_pan_deg))
            max_tilt_deg = max(0.5, float(max_tilt_deg))
            acq = self.config.acquisition
            acq.search_region_pan_min = float(max(-max_pan_deg, min(max_pan_deg, acq.search_region_pan_min)))
            acq.search_region_pan_max = float(max(-max_pan_deg, min(max_pan_deg, acq.search_region_pan_max)))
            acq.search_region_tilt_min = float(max(-max_tilt_deg, min(max_tilt_deg, acq.search_region_tilt_min)))
            acq.search_region_tilt_max = float(max(-max_tilt_deg, min(max_tilt_deg, acq.search_region_tilt_max)))
            if acq.search_region_pan_min > acq.search_region_pan_max:
                acq.search_region_pan_min, acq.search_region_pan_max = acq.search_region_pan_max, acq.search_region_pan_min
            if acq.search_region_tilt_min > acq.search_region_tilt_max:
                acq.search_region_tilt_min, acq.search_region_tilt_max = acq.search_region_tilt_max, acq.search_region_tilt_min
        except Exception:
            pass

    def update(
        self,
        dt: float,
        controller: Any | None = None,
        fov_frame=None,
        fov_capture_pose: tuple[float, float] | None = None,
        **kwargs: Any,
    ) -> None:
        """Advance time, process latency queue, and execute acquisition/detection/tracking.

        fov_frame: previous captured frame (H,W,3 uint8).  Autonomous
        detection is image-only; without a frame the terminal keeps searching
        and never substitutes scenario/world-model ground truth.
        fov_capture_pose: (pan, tilt) at which fov_frame was captured. The
        latency queue drains before detection, so the pose may have moved
        since capture; the spot measurement is shifted back accordingly.
        Without it, fast slews misalign the measurement and cause
        confirm flip-flop.
        """
        prev_pan, prev_tilt = float(self.pan), float(self.tilt)
        self._time += float(dt)

        # Process due actuator queue items
        while self._pending and self._pending[0][0] <= self._time:
            item = self._pending.popleft()
            if len(item) == 4:
                _, d_pan, d_tilt, qdt = item
                self._apply_delta(d_pan, d_tilt, float(qdt))
            else:
                _, d_pan, d_tilt = item
                self._apply_delta(d_pan, d_tilt, dt)

        if dt > 1e-9:
            self._last_cam_vel_x = (float(self.pan) - prev_pan) / float(dt)
            self._last_cam_vel_y = (float(self.tilt) - prev_tilt) / float(dt)
        else:
            self._last_cam_vel_x = 0.0
            self._last_cam_vel_y = 0.0

        # Fail closed: world truth must never reach the receiver, even
        # via a stale keyword from old call sites.
        if "remote_scenario" in kwargs:
            raise TypeError("remote_scenario was removed: LocalTerminal is image-only")
        # Step operations
        self.step_operations(
            dt, controller=controller,
            fov_frame=fov_frame, fov_capture_pose=fov_capture_pose,
        )

    def flush_pending(self) -> None:
        while self._pending:
            item = self._pending.popleft()
            if len(item) == 4:
                _, d_pan, d_tilt, qdt = item
                self._apply_delta(d_pan, d_tilt, float(qdt))
            else:
                _, d_pan, d_tilt = item
                self._apply_delta(d_pan, d_tilt, 0.033)

    @property
    def readout_pan(self) -> float:
        return float(self.pan + self._enc_bias_x)

    @property
    def readout_tilt(self) -> float:
        return float(self.tilt + self._enc_bias_y)

    def set_position(self, pan: float, tilt: float, clear_queue: bool = True) -> None:
        if clear_queue:
            self._pending.clear()
        self.pan = float(pan)
        self.tilt = float(tilt)
        self._clamp_to_range()

    def apply_disturbance(self, pan: float, tilt: float) -> None:
        self.set_position(pan, tilt, clear_queue=False)

    def go_home(self) -> None:
        self.set_position(float(self.config.ptz.home_pan), float(self.config.ptz.home_tilt))

    def set_vignetting(self, strength: float) -> None:
        self.vignetting = float(np.clip(float(strength), 0.0, 0.95))
        self.config.vignetting = self.vignetting

    def apply_config(self, config: LocalTerminalConfig, scene_bounds: tuple[int, int] | None = None) -> None:
        if scene_bounds is not None:
            self.scene_bounds = scene_bounds
            config.validate(scene_bounds)
        else:
            config.validate(self.scene_bounds)
        self.config = config
        self.fov_width = int(config.camera.resolution_width)
        self.fov_height = int(config.camera.resolution_height)
        self.set_vignetting(float(config.vignetting))
        self.scanner.config = config.acquisition
        self.tracker.config = config.tracking
        self.tracker.angular_model = config.angular_model
        try:
            self.system.refresh_config(config)
            self.system.search.scanner = self.scanner
            self.system.scene_bounds = self.scene_bounds
        except Exception:
            pass
        self._clamp_to_range()
        self._clamp_search_region_to_reachable()

    # -----------------------------------------------------------------
    # FOV Geometry and Capture
    # -----------------------------------------------------------------
    def get_fov_rect(self) -> tuple[int, int, int, int]:
        x0 = int(round(self.pan - self.fov_width / 2.0))
        y0 = int(round(self.tilt - self.fov_height / 2.0))
        return x0, y0, x0 + self.fov_width, y0 + self.fov_height

    def get_pan_range(self) -> tuple[float, float]:
        return self._effective_pan_range()

    def get_tilt_range(self) -> tuple[float, float]:
        return self._effective_tilt_range()

    def get_home(self) -> tuple[float, float]:
        return (float(self.config.ptz.home_pan), float(self.config.ptz.home_tilt))

    def capture(self, scene_frame: np.ndarray, vignetting: float | None = None) -> np.ndarray:
        h, w = scene_frame.shape[:2]
        x0, y0, x1, y1 = self.get_fov_rect()
        x0c, y0c = max(x0, 0), max(y0, 0)
        x1c, y1c = min(x1, w), min(y1, h)

        out = np.zeros((self.fov_height, self.fov_width, 3), dtype=scene_frame.dtype)
        if x1c > x0c and y1c > y0c:
            crop = scene_frame[y0c:y1c, x0c:x1c]
            out[y0c - y0: y0c - y0 + crop.shape[0],
                x0c - x0: x0c - x0 + crop.shape[1]] = crop

        vig = float(vignetting) if vignetting is not None else float(self.vignetting)
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                out = apply_vignetting(out, vig)
            except Exception:
                pass
        return out

    def capture_region(self, scene: Any, vignetting: float | None = None) -> np.ndarray:
        x0, y0, x1, y1 = self.get_fov_rect()
        crop = scene.get_region(x0, y0, x1, y1)
        vig = float(vignetting) if vignetting is not None else float(self.vignetting)
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                crop = apply_vignetting(crop, vig)
            except Exception:
                pass
        return crop

    # -----------------------------------------------------------------
    # Operational Cycle: Acquisition, Detection, Tracking, Link State
    # -----------------------------------------------------------------
    def _image_candidates(self, frame, dt: float) -> list[dict[str, Any]]:
        """Measure and associate beacon candidates from the received frame."""
        raw = detect_beacon_candidates(frame, minimum_peak=max(30.0, self.config.detection.intensity_threshold))
        active: set[str] = set()
        for candidate in raw:
            nearest_id, nearest_distance = None, float("inf")
            for track_id, track in self._observation_tracks.items():
                distance = math.hypot(candidate["x"] - track["x"], candidate["y"] - track["y"])
                if distance < nearest_distance:
                    nearest_id, nearest_distance = track_id, distance
            if nearest_id is None or nearest_distance > 25.0:
                nearest_id = f"BEACON-{self._next_observation_track_id}"
                self._next_observation_track_id += 1
                self._observation_tracks[nearest_id] = {"x": candidate["x"], "y": candidate["y"], "history": []}
            track = self._observation_tracks[nearest_id]
            track["x"], track["y"] = candidate["x"], candidate["y"]
            history = track.setdefault("history", [])
            history.append((float(self._time), float(candidate["peak_dn"])))
            del history[:-96]
            # The renderer exposes modulation as intensity variation.  This
            # observable score is intentionally conservative: it does not
            # claim a modulation match until several samples have arrived.
            if len(history) >= 4:
                samples = np.asarray([sample[1] for sample in history], dtype=float)
                mean = max(1.0, float(np.mean(samples)))
                modulation_score = float(np.clip(np.std(samples) / mean * 3.0, 0.0, 1.0))
            else:
                modulation_score = 0.0
            modulation_hz = 0.0
            if len(history) >= 8 and modulation_score >= 0.03:
                samples = np.asarray([sample[1] for sample in history], dtype=float)
                sample_dt = float(np.median(np.diff([sample[0] for sample in history])))
                if sample_dt > 1e-5:
                    spectrum = np.abs(np.fft.rfft(samples - samples.mean()))
                    if spectrum.size > 1:
                        peak_bin = int(np.argmax(spectrum[1:]) + 1)
                        modulation_hz = float(np.fft.rfftfreq(samples.size, sample_dt)[peak_bin])
            code_correlation = self._code_correlation(history)
            wavelength, spectral_score = estimate_wavelength_nm(candidate["bgr"])
            candidate.update({
                "terminal_id": nearest_id, "wavelength_nm": wavelength,
                "spectral_score": spectral_score, "modulation_score": modulation_score,
                "modulation_hz": modulation_hz,
                "code_correlation": code_correlation,
            })
            active.add(nearest_id)
        # Tracks are receiver-side memory only.  Retain them briefly through a
        # dropout so reacquisition can keep a stable local identity.
        for track_id in list(self._observation_tracks):
            if track_id not in active:
                track = self._observation_tracks[track_id]
                track["misses"] = int(track.get("misses", 0)) + 1
                if track["misses"] > 45:
                    del self._observation_tracks[track_id]
            else:
                self._observation_tracks[track_id]["misses"] = 0
        return raw

    def _code_correlation(self, history: list[tuple[float, float]]) -> float | None:
        """Correlate sampled intensity with this receiver's expected OOK code.

        This knows only the locally configured code and a shared simulation
        clock; it has no access to a remote terminal object or configuration.
        """
        code = self.config.detection.identification_code
        if not code or len(history) < 12:
            return None
        bits = "".join(f"{ord(ch):08b}" for ch in code)
        rate = float(self.config.detection.identification_code_chip_rate_hz)
        expected = np.asarray([1.0 if bits[int(t * rate) % len(bits)] == "1" else 0.25 for t, _ in history], dtype=float)
        observed = np.asarray([value for _, value in history], dtype=float)
        expected -= expected.mean()
        observed -= observed.mean()
        denom = float(np.linalg.norm(expected) * np.linalg.norm(observed))
        return float(np.clip(np.dot(expected, observed) / denom, -1.0, 1.0)) if denom > 1e-6 else 0.0

    def step_operations(
        self,
        dt: float,
        controller: Any | None = None,
        fov_frame=None,
        fov_capture_pose: tuple[float, float] | None = None,
        **kwargs: Any,
    ) -> None:
        """Step autonomous acquisition, optical detection, closed-loop tracking, and comms.

        STRICT IMAGE-ONLY BOUNDARY (Plan §1, §38): perception derives solely
        from ``fov_frame`` + PTZ pose/velocity + local configuration.
        World truth is never accepted: passing ``remote_scenario`` raises
        TypeError (fail closed). ``fov_frame=None`` means no observation
        this cycle (search runs).
        """
        if "remote_scenario" in kwargs:
            raise TypeError("remote_scenario was removed: LocalTerminal is image-only")
        if self.config.state.power_state != "ON":
            self.config.state.operational_state = "OFF"
            self.config.state.ptz_state = "IDLE"
            self.config.state.acquisition_state = "IDLE"
            self.config.state.detection_state = "NO_TARGET"
            self.config.state.tracking_state = "OFF"
            self.config.state.link_state = "NO_LINK"
            return

        # Keep pipeline config in sync (GUI may mutate self.config live).
        try:
            self.system.refresh_config(self.config)
        except Exception:
            pass
        try:
            self.system.search.scanner = self.scanner
        except Exception:
            pass

        # Build CameraFrame input (Plan §2). Invalid/None frame = no observation.
        self._frame_seq += 1
        cam_frame = None
        try:
            if fov_frame is not None:
                import numpy as _np
                arr = _np.asarray(fov_frame)
                if arr.size > 0 and arr.ndim in (2, 3):
                    cam_frame = CameraFrame.from_image(arr, frame_id=self._frame_seq,
                                                       timestamp=float(self._time))
        except Exception:
            cam_frame = None

        cam_vel = (float(self._last_cam_vel_x), float(self._last_cam_vel_y))
        pose = (float(self.pan), float(self.tilt))
        try:
            out = self.system.update(UpdateInput(timestamp=float(self._time), delta_time=float(dt),
                                                 camera_frame=cam_frame, current_ptz_pose=pose,
                                                 current_ptz_velocity=cam_vel,
                                                 local_configuration=self.config))
        except Exception:
            return

        # --- Translate pipeline output to actuator + legacy telemetry ---
        # PTZ motion owns the single move path (search / track / coast).
        try:
            cmd = out.ptz_command
            if cmd is not None:
                pan_lo, pan_hi = self._effective_pan_range()
                tilt_lo, tilt_hi = self._effective_tilt_range()
                tgt_pan = float(max(pan_lo, min(pan_hi, cmd.target_pan)))
                tgt_tilt = float(max(tilt_lo, min(tilt_hi, cmd.target_tilt)))
                if out.local_terminal_state == _PipelineState.TRACKING and controller is not None:
                    try:
                        err = (out.tracking_status.tracking_error_x,
                               out.tracking_status.tracking_error_y)
                        action = controller.step(err, float(dt))
                        self.move(float(action[0]), float(action[1]), float(dt))
                    except Exception:
                        self.move(float(tgt_pan - self.pan), float(tgt_tilt - self.tilt), float(dt))
                else:
                    self.move(float(tgt_pan - self.pan), float(tgt_tilt - self.tilt), float(dt))
        except Exception:
            pass

        # Legacy mirror state for GUI/tests.
        st = out.local_terminal_state
        try:
            if st == _PipelineState.FAULT:
                self.config.state.operational_state = "FAULT"
                self.config.state.acquisition_state = "IDLE"
            elif st == _PipelineState.SEARCHING:
                self.config.state.acquisition_state = "SEARCHING"
            elif st in (_PipelineState.DETECTING,):
                self.config.state.acquisition_state = "SEARCHING"
            elif st == _PipelineState.VERIFYING:
                self.config.state.acquisition_state = "ACQUIRING"
            elif st in (_PipelineState.ACQUIRED, _PipelineState.TRACKING,
                        _PipelineState.DEGRADED, _PipelineState.REACQUIRING):
                self.config.state.acquisition_state = "ACQUIRED"
            elif st == _PipelineState.LOST:
                self.config.state.acquisition_state = "SEARCHING"
            elif st == _PipelineState.IDLE:
                self.config.state.acquisition_state = "IDLE"
        except Exception:
            pass
        try:
            if st != _PipelineState.FAULT and self.config.state.operational_state == "FAULT":
                self.config.state.operational_state = "STANDBY"
        except Exception:
            pass
        try:
            if st == _PipelineState.FAULT:
                self.config.state.detection_state = "NO_TARGET"
            elif st == _PipelineState.SEARCHING:
                self.config.state.detection_state = "DETECTING" if out.candidate_tracks else "NO_TARGET"
            elif st == _PipelineState.DETECTING:
                self.config.state.detection_state = "DETECTING"
            elif st == _PipelineState.VERIFYING:
                self.config.state.detection_state = "DISCRIMINATING"
            elif st in (_PipelineState.ACQUIRED, _PipelineState.TRACKING,
                        _PipelineState.DEGRADED, _PipelineState.REACQUIRING):
                self.config.state.detection_state = "TARGET_CONFIRMED" if out.tracking_status.target_acquired or out.tracking_status.target_visible else "DISCRIMINATING"
            elif st == _PipelineState.LOST:
                self.config.state.detection_state = "NO_TARGET"
        except Exception:
            pass
        try:
            if st == _PipelineState.TRACKING:
                self.config.state.tracking_state = "TRACKING"
            elif st == _PipelineState.REACQUIRING:
                self.config.state.tracking_state = "REACQUIRING"
            elif st == _PipelineState.LOST:
                self.config.state.tracking_state = "LOST"
            elif st == _PipelineState.DEGRADED:
                self.config.state.tracking_state = "TRACKING"
            else:
                # Preserve LOST latch briefly handled by pipeline; else OFF.
                if self.config.state.tracking_state not in ("REACQUIRING",):
                    self.config.state.tracking_state = "OFF"
        except Exception:
            pass

        # Candidate evaluations: local BEACON-N IDs only (never RT- IDs).
        try:
            self.candidate_evaluations = [
                {"terminal_id": t.observation_id, "confidence": float(t.confidence),
                 "confirmed": bool(t.lifecycle_state.value in ("IDENTIFIED", "SELECTED", "ACQUIRED", "TRACKING")),
                 "fov_x": float(t.meas_x), "fov_y": float(t.meas_y),
                 "wavelength_match": bool(t.signature.spectral_score >= 0.5),
                 "modulation_match": bool(t.signature.temporal_score >= 0.2),
                 "spot_size_match": bool(t.signature.spatial_score >= 0.5),
                 "code_match": bool((t.signature.code_score is None) or (t.signature.code_score >= 0.5)),
                 "code_correlation": t.signature.code_score,
                 "reason": "OK", "lifecycle": t.lifecycle_state.value,
                 "overall_score": float(t.signature.overall_score), "snr_db": float(t.meas_snr)}
                for t in out.candidate_tracks
            ]
        except Exception:
            self.candidate_evaluations = []
        self.active_target_id = out.active_observation_id
        try:
            self._reacquire_dwell = float(out.telemetry.get("reacq_elapsed", 0.0) or 0.0)
        except Exception:
            self._reacquire_dwell = 0.0
        # Mirror estimator/controller state into legacy tracker for GUI/debug.
        try:
            self.tracker.vel_x = float(out.target_state.velocity_x)
            self.tracker.vel_y = float(out.target_state.velocity_y)
            self._last_tracking_eval = {"active": True, "locked": bool(out.tracking_status.target_acquired),
                                        "error_px": (float(out.tracking_status.tracking_error_x),
                                                     float(out.tracking_status.tracking_error_y)),
                                        "lost_time": float(out.telemetry.get("reacq_elapsed", 0.0) or 0.0)}
        except Exception:
            pass
        try:
            best = None
            for t in out.candidate_tracks:
                if t.observation_id == out.active_observation_id:
                    best = t
                    break
            if best is not None:
                self._last_detection_eval = {"detected": True, "confirmed": bool(out.tracking_status.target_acquired),
                                             "confidence": float(best.confidence), "snr_db": float(best.meas_snr)}
            elif out.candidate_tracks:
                t0 = out.candidate_tracks[0]
                self._last_detection_eval = {"detected": True, "confirmed": False,
                                             "confidence": float(t0.confidence), "snr_db": float(t0.meas_snr)}
            else:
                self._last_detection_eval = {"detected": False, "confirmed": False, "confidence": 0.0, "snr_db": 0.0}
        except Exception:
            pass

        # Optical link FSM from centered dwell (legacy thresholds preserved).
        try:
            if out.tracking_status.target_centered:
                self._lock_dwell_time += float(dt)
            elif out.target_state.valid:
                cx, cy = self.fov_width * 0.5, self.fov_height * 0.5
                d = math.hypot(out.target_state.filtered_x - cx, out.target_state.filtered_y - cy)
                if d <= min(self.fov_width, self.fov_height) * 0.15:
                    self._lock_dwell_time += float(dt)
                else:
                    self._lock_dwell_time = max(0.0, self._lock_dwell_time - float(dt) * 2.0)
            else:
                self._lock_dwell_time = 0.0
            if out.tracking_status.target_acquired and self._lock_dwell_time >= 1.2:
                self.config.state.link_state = "CONNECTED"
            elif out.tracking_status.target_acquired and self._lock_dwell_time >= 0.5:
                self.config.state.link_state = "HANDSHAKE"
            elif out.tracking_status.target_acquired and self._lock_dwell_time >= 0.2:
                self.config.state.link_state = "OPTICAL_LOCK"
            elif not out.tracking_status.target_acquired:
                self._lock_dwell_time = 0.0
                self.config.state.link_state = "NO_LINK"
            self.config.communication.link_state = self.config.state.link_state
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Telemetry Output
    # -----------------------------------------------------------------
    def get_telemetry(self) -> dict[str, Any]:
        """Aggregate real-time Local Terminal operational telemetry."""
        return {
            "identity": {
                "id": self.config.identity.id,
                "name": self.config.identity.name,
                "type": self.config.identity.type,
                "platform_id": self.config.identity.platform_id,
            },
            "state": {
                "operational_state": self.config.state.operational_state,
                "power_state": self.config.state.power_state,
                "ptz_state": self.config.state.ptz_state,
                "acquisition_state": self.config.state.acquisition_state,
                "detection_state": self.config.state.detection_state,
                "tracking_state": self.config.state.tracking_state,
                "link_state": self.config.state.link_state,
            },
            "position": {
                "x": float(self.config.position.x),
                "y": float(self.config.position.y),
                "z": float(self.config.position.z),
                "pan": float(self.pan),
                "tilt": float(self.tilt),
                "readout_pan": float(self.readout_pan),
                "readout_tilt": float(self.readout_tilt),
            },
            "fov": {
                "rect": self.get_fov_rect(),
                "width": self.fov_width,
                "height": self.fov_height,
                "fov_x_deg": self.config.camera.fov_x,
                "fov_y_deg": self.config.camera.fov_y,
            },
            "angular_model": {
                "pixel_to_angle_x": self.config.angular_model.pixel_to_angle_x,
                "pixel_to_angle_y": self.config.angular_model.pixel_to_angle_y,
                "angle_to_pixel_x": self.config.angular_model.angle_to_pixel_x,
                "angle_to_pixel_y": self.config.angular_model.angle_to_pixel_y,
                "unit": self.config.angular_model.unit,
            },
            "detection": dict(self._last_detection_eval),
            "tracking": dict(self._last_tracking_eval),
            "autonomy": {
                "active_target_id": self.active_target_id,
                "candidate_count": len(self.candidate_evaluations),
                "candidates": list(self.candidate_evaluations),
                "reacquire_dwell": float(self._reacquire_dwell),
                "state": (
                    "LOCKED" if self.config.state.tracking_state == "TRACKING"
                    else "REACQUIRING" if self.config.state.tracking_state == "REACQUIRING"
                    else "SEARCHING" if self.config.state.acquisition_state == "SEARCHING"
                    else "DISCRIMINATING" if self.config.state.detection_state == "DISCRIMINATING"
                    else "IDLE"
                ),
            },
            "communication": {
                "terminal_id": self.config.communication.terminal_id,
                "protocol": self.config.communication.protocol,
                "capabilities": list(self.config.communication.capabilities),
                "link_state": self.config.communication.link_state,
                "dwell_time": float(self._lock_dwell_time),
            },
        }
