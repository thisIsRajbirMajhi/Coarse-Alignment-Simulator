# local_terminal/terminal.py - Local Terminal operational model per LocalTerminal.md
from __future__ import annotations

import collections
import math
from typing import Any

import numpy as np

from common.rng import get_rng
from local_terminal.acquisition import AcquisitionScanner
from local_terminal.config import LocalTerminalConfig
from local_terminal.detection import DetectionEngine
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

        # Operational Subsystems
        self.scanner = AcquisitionScanner(self.config.acquisition, rng=self._rng)
        self.detector = DetectionEngine(self.config.detection)
        self.tracker = TargetTracker(self.config.tracking, self.config.angular_model)

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
        remote_scenario: Any | None = None,
        controller: Any | None = None,
        fov_frame=None,
        fov_capture_pose: tuple[float, float] | None = None,
    ) -> None:
        """Advance time, process latency queue, and execute acquisition/detection/tracking.

        fov_frame: previous captured frame (H,W,3 uint8) for image-gated
        detection. Optional — without it detection falls back to analytic
        stubs so existing callers/tests are unaffected.
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

        # Step operations
        self.step_operations(
            dt, remote_scenario=remote_scenario, controller=controller,
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
        self.detector.config = config.detection
        self.tracker.config = config.tracking
        self.tracker.angular_model = config.angular_model
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
    def step_operations(
        self,
        dt: float,
        remote_scenario: Any | None = None,
        controller: Any | None = None,
        fov_frame=None,
        fov_capture_pose: tuple[float, float] | None = None,
    ) -> None:
        """Step autonomous acquisition, optical detection, closed-loop tracking, and comms.

        fov_frame: previous captured frame for image-gated detection
        (peak DN / SNR measured at each candidate spot). Optional.
        fov_capture_pose: pose at capture; compensates queue-drain motion.
        """
        if self.config.state.power_state != "ON":
            self.config.state.operational_state = "OFF"
            self.config.state.ptz_state = "IDLE"
            self.config.state.acquisition_state = "IDLE"
            self.config.state.detection_state = "NO_TARGET"
            self.config.state.tracking_state = "OFF"
            self.config.state.link_state = "NO_LINK"
            return

        x0, y0, x1, y1 = self.get_fov_rect()
        target_in_fov = False
        spot_center_fov: tuple[float, float] | None = None
        beacon_eval: dict[str, Any] = {
            "detected": False,
            "confirmed": False,
            "confidence": 0.0,
            "snr_db": 0.0,
        }
        self.candidate_evaluations.clear()

        # -------------------------------------------------------------
        # 1. Multi-Target Detection & Signature Discrimination
        # -------------------------------------------------------------
        if remote_scenario is not None:
            visible = []
            if hasattr(remote_scenario, "get_visible_terminals"):
                visible = remote_scenario.get_visible_terminals(self)
            elif hasattr(remote_scenario, "terminals"):
                visible = [t for t in remote_scenario.terminals if x0 <= t.x <= x1 and y0 <= t.y <= y1]

            evaluated_candidates = []
            for t in visible:
                b_cfg = getattr(t.config, "beacon", None)
                if b_cfg is None:
                    continue

                div_mrad = getattr(b_cfg, "divergence_mrad", None)
                if div_mrad is None:
                    div_mrad = getattr(b_cfg, "div_h_mrad", 3.0)

                mod_f = getattr(b_cfg, "mod_freq_khz", None)
                if mod_f is None:
                    pr = getattr(b_cfg, "pulse_rate_hz", None)
                    mod_f = pr * 0.001 if pr is not None else getattr(b_cfg, "pulse_rate_khz", 10.0)

                # Image-gated measurement: when a frame is available, use
                # measured peak/SNR at the candidate spot instead of stubs
                # so washed-out/occluded beacons correctly fail.
                spot_guess = (float(t.x - x0), float(t.y - y0))
                if fov_frame is not None and t.is_emitting:
                    try:
                        from local_terminal.detection import estimate_spot_brightness as _est
                        guess = spot_guess
                        if fov_capture_pose is not None:
                            import math as _math
                            dx = float(fov_capture_pose[0]) - float(self.pan)
                            dy = float(fov_capture_pose[1]) - float(self.tilt)
                            # Slewing fast: frame too stale to measure, use stubs.
                            if _math.hypot(dx, dy) > 25.0:
                                peak_dn, snr_db = 180.0, 15.0
                            else:
                                guess = (spot_guess[0] + dx, spot_guess[1] + dy)
                                peak_dn, snr_db = _est(fov_frame, guess)
                        else:
                            peak_dn, snr_db = _est(fov_frame, guess)
                        # Fall back to stubs only when measurement is degenerate
                        # (e.g. first frame not yet captured).
                        if peak_dn <= 0.0 and snr_db <= 0.0:
                            peak_dn, snr_db = 180.0, 15.0
                    except Exception:
                        peak_dn, snr_db = 180.0, 15.0
                else:
                    peak_dn = 180.0 if t.is_emitting else 0.0
                    snr_db = 15.0 if t.is_emitting else 0.0
                cand_eval = self.detector.evaluate_target(
                    in_fov=True,
                    beacon_power=b_cfg.power_w if t.is_emitting else 0.0,
                    beacon_wavelength=getattr(b_cfg, "wavelength_nm", 1550.0),
                    beacon_bandwidth=getattr(b_cfg, "bandwidth_nm", 10.0),
                    beacon_divergence_mrad=float(div_mrad),
                    modulation_type=getattr(b_cfg, "mod_type", "AM"),
                    modulation_freq_khz=float(mod_f),
                    estimated_snr_db=float(snr_db),
                    estimated_dn=float(peak_dn),
                )

                t_id = getattr(getattr(t.config, "identity", None), "id", f"RT-{id(t)}")

                # Apply target ID filter if user specified one
                id_filter = getattr(self.config.detection, "target_id_filter", "")
                if id_filter and id_filter.strip() and t_id != id_filter.strip():
                    cand_eval["confirmed"] = False
                    cand_eval["reason"] = f"Filtered out (expected {id_filter})"

                eval_entry = {
                    "terminal_id": t_id,
                    "terminal": t,
                    "pos": (float(t.x), float(t.y)),
                    "spot_fov": (float(t.x - x0), float(t.y - y0)),
                    "evaluation": cand_eval,
                    "confidence": float(cand_eval.get("confidence", 0.0)),
                    "confirmed": bool(cand_eval.get("confirmed", False)),
                }
                evaluated_candidates.append(eval_entry)

            self.candidate_evaluations = [
                {
                    "terminal_id": c["terminal_id"],
                    "confidence": c["confidence"],
                    "confirmed": c["confirmed"],
                    "fov_x": c["spot_fov"][0],
                    "fov_y": c["spot_fov"][1],
                    "wavelength_match": c["evaluation"].get("wavelength_match", False),
                    "modulation_match": c["evaluation"].get("modulation_match", False),
                    "spot_size_match": c["evaluation"].get("spot_size_match", False),
                    "reason": c["evaluation"].get("reason", "OK"),
                }
                for c in evaluated_candidates
            ]

            # Autonomous Candidate Selection & Identification with hysteresis:
            # a new target needs 2 consecutive confirmations to take over,
            # preventing flicker between equal-confidence candidates.
            target_candidate = None
            for c in evaluated_candidates:
                tid = c["terminal_id"]
                if c["confirmed"]:
                    self._confirm_counts[tid] = int(self._confirm_counts.get(tid, 0)) + 1
                else:
                    self._confirm_counts[tid] = 0
            for tid in list(self._confirm_counts.keys()):
                if all(tid != c["terminal_id"] for c in evaluated_candidates):
                    self._confirm_counts.pop(tid, None)

            # Case A: keep active target if still visible and confirmed.
            if self.active_target_id is not None:
                for c in evaluated_candidates:
                    if c["terminal_id"] == self.active_target_id:
                        if c["confirmed"]:
                            target_candidate = c
                        break
                if target_candidate is None and self.active_target_id is not None:
                    # Active vanished: keep id during coast, drop only on loss.
                    pass

            # Case B: track best confirmed candidate immediately for
            # responsiveness, but only reassign identity once stable
            # (2 consecutive frames) to avoid ID flicker.
            if target_candidate is None:
                confirmed_candidates = [c for c in evaluated_candidates if c["confirmed"]]
                if confirmed_candidates:
                    confirmed_candidates.sort(key=lambda c: c["confidence"], reverse=True)
                    best = confirmed_candidates[0]
                    target_candidate = best
                    if self.active_target_id is None or self._confirm_counts.get(best["terminal_id"], 0) >= 2:
                        self.active_target_id = target_candidate["terminal_id"]

            # FOV margin: edge grazes (within 15 px of the border) stay
            # DETECTING/DISCRIMINATING — confirming them causes
            # lock-then-instantly-lose churn as the spot exits mid-slew.
            _FOV_MARGIN = 15.0
            _margin_rejected_id: str | None = None
            if target_candidate is not None:
                _sx, _sy = target_candidate["spot_fov"]
                if not (_FOV_MARGIN <= _sx <= self.fov_width - _FOV_MARGIN
                        and _FOV_MARGIN <= _sy <= self.fov_height - _FOV_MARGIN):
                    _margin_rejected_id = target_candidate["terminal_id"]
                    target_candidate = None

            if target_candidate is not None:
                target_in_fov = True
                spot_center_fov = target_candidate["spot_fov"]
                beacon_eval = target_candidate["evaluation"]
            elif evaluated_candidates:
                # Decoys, non-matching candidates, or margin-rejected edge
                # grazes visible in FOV — never confirm from this branch.
                target_in_fov = True
                beacon_eval = dict(evaluated_candidates[0]["evaluation"])
                if _margin_rejected_id is not None:
                    beacon_eval["confirmed"] = False
                    beacon_eval["reason"] = "Spot too close to FOV edge"
                    # Keep identity sticky so the sweep continues toward it.
                    self.active_target_id = _margin_rejected_id
            else:
                beacon_eval = self.detector.evaluate_target(
                    in_fov=False, beacon_power=0.0, beacon_wavelength=1550,
                    beacon_bandwidth=10, beacon_divergence_mrad=3.0,
                    modulation_type="AM", modulation_freq_khz=10.0,
                )

        self._last_detection_eval = beacon_eval
        target_confirmed = bool(beacon_eval.get("confirmed", False))

        if target_confirmed:
            self.config.state.detection_state = "TARGET_CONFIRMED"
        elif self.candidate_evaluations:
            self.config.state.detection_state = "DISCRIMINATING"
        elif target_in_fov:
            self.config.state.detection_state = "DETECTING"
        else:
            self.config.state.detection_state = "NO_TARGET"

        # -------------------------------------------------------------
        # 2. Autonomous Acquisition & Scanning
        # -------------------------------------------------------------
        acq_mode = self.config.acquisition.mode.upper()
        is_autonomous_acq = acq_mode in ("AUTO", "SEARCH", "AUTO_ACQUISITION")

        if target_confirmed:
            self.config.state.acquisition_state = "ACQUIRED"
            self.scanner.stop()
            self._reacquire_dwell = 0.0
        elif is_autonomous_acq:
            # Never scan while the tracking loop owns motion (TRACKING or
            # REACQUIRING coast). Scanning on the first dropout frame used
            # to queue a rail-bound jump that fought the coast command.
            if self.config.state.tracking_state not in ("REACQUIRING", "TRACKING"):
                if self.config.state.acquisition_state != "SEARCHING":
                    self.scanner.start()
                    self.config.state.acquisition_state = "SEARCHING"

                d_pan_deg, d_tilt_deg, timed_out = self.scanner.update(dt)
                if timed_out and acq_mode == "SEARCH":
                    self.scanner.stop()
                    self.config.state.acquisition_state = "IDLE"
                else:
                    self._clamp_search_region_to_reachable()
                    scale_x = self.config.angular_model.pixel_to_angle_x * 0.001
                    scale_y = self.config.angular_model.pixel_to_angle_y * 0.001
                    px_per_deg_x = 17.453292519943295 / max(1e-6, scale_x)
                    px_per_deg_y = 17.453292519943295 / max(1e-6, scale_y)

                    target_pan = float(self.config.ptz.home_pan) + float(d_pan_deg) * px_per_deg_x
                    target_tilt = float(self.config.ptz.home_tilt) + float(d_tilt_deg) * px_per_deg_y
                    # Clamp scan goal to reachable range BEFORE stepping so the
                    # scanner doesn't wind up at the rails.
                    pan_lo, pan_hi = self._effective_pan_range()
                    tilt_lo, tilt_hi = self._effective_tilt_range()
                    target_pan = float(max(pan_lo, min(pan_hi, target_pan)))
                    target_tilt = float(max(tilt_lo, min(tilt_hi, target_tilt)))
                    step_pan = float(target_pan - self.pan)
                    step_tilt = float(target_tilt - self.tilt)
                    self.move(step_pan, step_tilt, dt)

        # -------------------------------------------------------------
        # 3. Continuous Autonomous Tracking & Reacquisition Loop
        # -------------------------------------------------------------
        trk_mode = self.config.tracking.mode.upper()
        can_track = trk_mode in ("AUTO", "TRACKING")

        if can_track and target_confirmed and spot_center_fov is not None:
            if self.config.state.tracking_state != "TRACKING":
                # Fresh lock: drop scan-velocity + stale servo history so the
                # first corrections go toward the target (accel limiter and
                # integral otherwise start from fast-scan state and can push
                # backwards). A new target id also re-inits the estimator.
                self._last_vx = 0.0
                self._last_vy = 0.0
                _new_id = target_candidate["terminal_id"] if target_candidate is not None else None
                if _new_id != getattr(self, "_last_tracked_id", None):
                    self.tracker.reset()
                    self._last_tracked_id = _new_id
            self.config.state.tracking_state = "TRACKING"
            self._reacquire_dwell = 0.0
            cam_vel = (float(getattr(self, "_last_cam_vel_x", 0.0)), float(getattr(self, "_last_cam_vel_y", 0.0)))
            tracking_res = self.tracker.update(dt, True, spot_center_fov, (self.fov_width, self.fov_height), camera_vel_px_s=cam_vel)
            self._last_tracking_eval = tracking_res

            err_px_x, err_px_y = tracking_res["error_px"]

            if controller is not None:
                try:
                    action = controller.step((err_px_x, err_px_y), dt)
                    self.move(float(action[0]), float(action[1]), dt)
                except Exception:
                    act_x, act_y = self.tracker.compute_control(err_px_x, err_px_y, dt)
                    self.move(act_x, act_y, dt)
            else:
                act_x, act_y = self.tracker.compute_control(err_px_x, err_px_y, dt)
                self.move(act_x, act_y, dt)

        elif self.config.state.tracking_state in ("TRACKING", "REACQUIRING") and not target_confirmed:
            # Autonomous reacquisition: coast along target velocity for up to 1.5s
            self._reacquire_dwell += dt
            tracking_res = self.tracker.update(dt, False, None, (self.fov_width, self.fov_height))
            self._last_tracking_eval = tracking_res

            if self._reacquire_dwell <= 1.5:
                self.config.state.tracking_state = "REACQUIRING"
                # Predictive velocity coasting
                coast_x = float(self.tracker.vel_x * dt)
                coast_y = float(self.tracker.vel_y * dt)
                self.move(coast_x, coast_y, dt)
            else:
                # Target lost: reset target and autonomously resume search
                # around last-known pose (not region edge) for fast re-find.
                self.active_target_id = None
                self._confirm_counts.clear()
                self._reacquire_dwell = 0.0
                self.config.state.tracking_state = "LOST"

                lost_action = self.config.tracking.lost_target_behavior.upper()
                self._last_vx = 0.0
                self._last_vy = 0.0
                self._last_tracked_id = None
                if lost_action in ("RESUME_SEARCH", "AUTO"):
                    try:
                        px_per_deg_x = 17.453292519943295 / max(
                            1e-6, float(self.config.angular_model.pixel_to_angle_x) * 0.001)
                        px_per_deg_y = 17.453292519943295 / max(
                            1e-6, float(self.config.angular_model.pixel_to_angle_y) * 0.001)
                        off_pan = (float(self.pan) - float(self.config.ptz.home_pan)) / px_per_deg_x
                        off_tilt = (float(self.tilt) - float(self.config.ptz.home_tilt)) / px_per_deg_y
                        self.scanner.start_at(off_pan, off_tilt)
                    except Exception:
                        self.scanner.start()
                    self.config.state.acquisition_state = "SEARCHING"
                    self.config.state.tracking_state = "OFF"
                elif lost_action == "RETURN_HOME":
                    self.go_home()
                    self.config.state.tracking_state = "OFF"
                elif lost_action == "HOLD_POSITION":
                    # Hold: keep last pose, stay LOST until a target re-confirms.
                    self.config.state.tracking_state = "LOST"
        else:
            if not target_confirmed:
                self.config.state.tracking_state = "OFF"

        # -------------------------------------------------------------
        # 4. Optical Communication Link State Machine
        # -------------------------------------------------------------
        if target_confirmed and spot_center_fov is not None:
            cx, cy = self.fov_width * 0.5, self.fov_height * 0.5
            dist_to_center = math.hypot(spot_center_fov[0] - cx, spot_center_fov[1] - cy)
            tol_px = min(self.fov_width, self.fov_height) * 0.15

            if dist_to_center <= tol_px:
                self._lock_dwell_time += dt
                if self._lock_dwell_time >= 1.2:
                    self.config.state.link_state = "CONNECTED"
                elif self._lock_dwell_time >= 0.5:
                    self.config.state.link_state = "HANDSHAKE"
                elif self._lock_dwell_time >= 0.2:
                    self.config.state.link_state = "OPTICAL_LOCK"
            else:
                self._lock_dwell_time = max(0.0, self._lock_dwell_time - dt * 2.0)
                if self._lock_dwell_time < 0.2:
                    self.config.state.link_state = "NO_LINK"
        else:
            self._lock_dwell_time = 0.0
            self.config.state.link_state = "NO_LINK"

        self.config.communication.link_state = self.config.state.link_state

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

