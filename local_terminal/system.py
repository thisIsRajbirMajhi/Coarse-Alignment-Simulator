# local_terminal/system.py - Orchestrator: Search->Detect->Identify->Acquire->Track->Reacquire.
#
# STRICT BOUNDARY: update() receives ONLY UpdateInput (timestamp, deltaTime,
# cameraFrame, currentPTZPose, currentPTZVelocity, localConfiguration).
# It must NEVER receive remote position/velocity/ID/beaconState/signature/
# world coordinates. All perception derives from the image.
#
# Phase-2 additions:
#   Step 4b — BeamCharacterizer  (optical properties from image)
#   Step 4c — SignalAnalyzer + FrameDecoder + IdentityMatcher (comm path)
#   Step 4d — CandidateLifecycle.apply_identity_result (identity-driven lifecycle)
#   Step 7b — Continuous identity verification during TRACKING
from __future__ import annotations

import math
from typing import Any

from local_terminal.acquisition_mgr import AcquisitionConfig2, AcquisitionManager
from local_terminal.association import CandidateAssociationManager
from local_terminal.candidate_detector import CandidateDetector
from local_terminal.estimator import TrackStateEstimator
from local_terminal.frame_decoder import FrameDecoder
from local_terminal.frame_processor import FrameProcessor
from local_terminal.identity_matcher import IdentityMatcher, TargetProfile
from local_terminal.lifecycle import CandidateLifecycleManager
from local_terminal.models import (
    AcquisitionResult,
    BeamProfile,
    CameraFrame,
    CandidateTrack,
    OpticalMeasurement,
    PTZCommand,
    SearchCommand,
    SignalMeasurement,
    SignalState,
    TargetIdentificationSignature,
    TargetPayloadConfig,
    TargetState,
    TrackingStatus,
    UpdateInput,
    UpdateOutput,
)
from local_terminal.reacquisition import ReacquisitionConfig, ReacquisitionManager
from local_terminal.search_manager import SearchManager
from local_terminal.signal_analyzer import SignalAnalyzer
from local_terminal.signature import SignatureAnalyzer
from local_terminal.state_machine import LocalStateMachine
from local_terminal.states import CandidateState, LocalTerminalState
from local_terminal.telemetry_mgr import TelemetryManager
from local_terminal.tracking_controller import TrackingController


class LocalTerminalSystem:
    """Thirteen-module pipeline with clear input/output contracts (§4)."""

    CENTER_TOL_PX = 5.0
    # Sensor-failure policy (§36): N consecutive invalid frames -> FAULT.
    # 90 frames ≈ 3 s at 30 Hz: brief dropouts coast via REACQUIRING, only a
    # sustained outage latches FAULT. Recovery on first valid frame.
    FAULT_AFTER_INVALID = 90

    def __init__(self, config: Any = None, scene_bounds: tuple[int, int] = (2000, 2000),
                 rng: Any = None, seed: int | None = None):
        from common.rng import get_rng
        self._rng = get_rng(rng, seed if seed is not None else 42)
        self.config = config
        self.scene_bounds = scene_bounds
        self.tracks: dict[str, CandidateTrack] = {}
        self.frame_id = 0
        self.time = 0.0
        self.active_observation_id: str | None = None
        self._confirm_streak: dict[str, int] = {}
        self._centered_latched = False
        self._lock_dwell = 0.0
        self._bad_frame_streak = 0
        self._hold_time = 0.0
        self._hold_cooldown = 0.0

        sig = self._build_signature(config)
        self.signature_cfg = sig
        self.frame_processor = FrameProcessor()
        self.detector = CandidateDetector(config)
        self.association = CandidateAssociationManager()
        self.signature = SignatureAnalyzer(sig)
        self.lifecycle = CandidateLifecycleManager()
        acq_cfg = self._build_acq(config)
        self.acquisition = AcquisitionManager(acq_cfg)
        trk_cfg = getattr(config, "tracking", None) if config is not None else None
        ang = getattr(config, "angular_model", None) if config is not None else None
        self.controller = TrackingController(trk_cfg, ang)
        self.estimator = TrackStateEstimator(
            smoothing=float(getattr(trk_cfg, "smoothing", 0.2) or 0.2),
            prediction_horizon=float(getattr(trk_cfg, "prediction_horizon", 0.15) or 0.15))
        acq_raw = getattr(config, "acquisition", None) if config is not None else None
        self.search = SearchManager(acq_raw, rng=self._rng)
        self.reacq = ReacquisitionManager(ReacquisitionConfig(
            lost_target_timeout=1.5))
        mode = str(getattr(acq_raw, "mode", "AUTO") or "AUTO").upper()
        init = (LocalTerminalState.SEARCHING if mode in ("SEARCH", "AUTO", "AUTO_ACQUISITION")
                else LocalTerminalState.IDLE)
        self.state_machine = LocalStateMachine(init)
        if init == LocalTerminalState.SEARCHING:
            try:
                self.search.start()
            except Exception:
                pass
        self.telemetry = TelemetryManager()
        self.last_output: UpdateOutput | None = None
        # thresholds (§24, configurable)
        self.acquisition_threshold = float(sig.minimum_score)
        self.tracking_retention_threshold = 0.70
        self.reacquisition_threshold = 0.80
        # Phase-2: communication path components
        self._signal_analyzer = SignalAnalyzer()
        self._frame_decoder = FrameDecoder()
        self._target_profile: TargetProfile = self._build_target_profile(config)
        self._id_matcher = IdentityMatcher(self._target_profile)
        exp_id = str(getattr(self._target_profile, "expected_terminal_id", "") or "").strip()
        require_id = bool(exp_id and exp_id != "0")
        self.lifecycle.legacy_optical_identification_enabled = bool(
            getattr(self._target_profile, "legacy_optical_identification_enabled", False)
        ) or (not require_id)
        self._id_check_counter: int = 0   # for periodic identity re-check during tracking


    # -- config helpers -------------------------------------------------
    def _build_signature(self, config: Any) -> TargetIdentificationSignature:
        try:
            det = getattr(config, "detection", None)
            if det is not None:
                return TargetIdentificationSignature.from_detection_config(det)
        except Exception:
            pass
        return TargetIdentificationSignature()

    def _build_acq(self, config: Any) -> AcquisitionConfig2:
        try:
            det = getattr(config, "detection", None)
            acq = getattr(config, "acquisition", None)
            timeout = float(getattr(acq, "timeout", 30.0) or 30.0) if acq is not None else 30.0
            tp = self._build_target_profile(config)
            exp_id = str(getattr(tp, "expected_terminal_id", "") or "").strip()
            require_id = bool(exp_id and exp_id != "0")
            legacy_opt = bool(getattr(tp, "legacy_optical_identification_enabled", False)) or (not require_id)
            if det is not None:
                acq_cfg = AcquisitionConfig2.from_detection(det, timeout)
                acq_cfg.require_identity_match = require_id
                acq_cfg.expected_terminal_id = exp_id
                acq_cfg.legacy_optical_mode = legacy_opt
                return acq_cfg
        except Exception:
            pass
        return AcquisitionConfig2()

    def _build_target_profile(self, config: Any) -> TargetProfile:
        """Build TargetProfile from config; falls back to wildcard (accept any)."""
        try:
            tp = getattr(config, "target_payload", getattr(config, "target_profile", None))
            if tp is not None:
                if isinstance(tp, TargetProfile):
                    return tp.validate()
                elif isinstance(tp, dict):
                    return TargetProfile.from_dict(tp)
            det = getattr(config, "detection", None)
            if det is not None and hasattr(det, "build_target_profile"):
                return det.build_target_profile()
            elif det is not None:
                code = str(getattr(det, "identification_code", "") or "").strip()
                if code:
                    return TargetProfile(expected_terminal_id=code).validate()
        except Exception:
            pass
        return TargetProfile()  # wildcard: accept any terminal

    def refresh_config(self, config: Any) -> None:
        self.config = config
        self.signature_cfg = self._build_signature(config)
        self.signature.signature = self.signature_cfg
        self.acquisition.config = self._build_acq(config)
        try:
            self.detector.config = config
        except Exception:
            pass
        try:
            trk = getattr(config, "tracking", None)
            ang = getattr(config, "angular_model", None)
            if trk is not None:
                self.controller.config = trk
                self.estimator.smoothing = float(getattr(trk, "smoothing", 0.2) or 0.2)
                self.estimator.prediction_horizon = float(getattr(trk, "prediction_horizon", 0.15) or 0.15)
            if ang is not None:
                self.controller.angular_model = ang
        except Exception:
            pass
        try:
            self.search.scanner.config = getattr(config, "acquisition", self.search.scanner.config)
        except Exception:
            pass
        self.acquisition_threshold = float(self.signature_cfg.minimum_score)
        # Phase-2: refresh identity pipeline
        try:
            self._target_profile = self._build_target_profile(config)
            self._id_matcher.update_profile(self._target_profile)
            exp_id = str(getattr(self._target_profile, "expected_terminal_id", "") or "").strip()
            require_id = bool(exp_id and exp_id != "0")
            self.lifecycle.legacy_optical_identification_enabled = bool(
                getattr(self._target_profile, "legacy_optical_identification_enabled", False)
            ) or (not require_id)
        except Exception:
            pass


    # -- main step ------------------------------------------------------
    def update(self, inp: UpdateInput) -> UpdateOutput:
        # sanitize (§36: never NaN)
        try:
            dt = float(inp.delta_time)
        except Exception:
            dt = 0.033
        if not math.isfinite(dt) or dt <= 0:
            dt = 0.033
        dt = max(1e-4, min(dt, 0.2))
        try:
            ts = float(inp.timestamp)
        except Exception:
            ts = self.time + dt
        if not math.isfinite(ts):
            ts = self.time + dt
        # Monotonic guard (§36): stale/out-of-order timestamps must not
        # corrupt age/confirm windows — clamp forward, never backward.
        try:
            if ts < self.time:
                ts = self.time + dt
            # Cap huge jumps (e.g. clock glitch) to 5 frames worth.
            if ts > self.time + 5.0 * dt + 1e-6 and self.frame_id > 0:
                ts = self.time + dt
        except Exception:
            pass
        self.time = ts
        self.frame_id += 1

        cfg = inp.local_configuration if inp.local_configuration is not None else self.config
        if cfg is not None and cfg is not self.config:
            self.refresh_config(cfg)
        else:
            cfg = self.config

        power_on = True
        try:
            power_on = str(getattr(getattr(cfg, "state", None), "power_state", "ON")).upper() == "ON"
        except Exception:
            pass

        frame: CameraFrame | None = inp.camera_frame
        fov_w, fov_h = 640, 480
        try:
            fov_w = int(getattr(getattr(cfg, "camera", None), "resolution_width", 640) or 640)
            fov_h = int(getattr(getattr(cfg, "camera", None), "resolution_height", 480) or 480)
        except Exception:
            pass
        if frame is not None and frame.valid():
            fov_w, fov_h = int(frame.width), int(frame.height)
        # Sensor-health streak (§36): None / zero-sized / empty frames count
        # as invalid. Sustained outage -> FAULT; any valid frame recovers.
        frame_ok = bool(power_on and frame is not None and frame.valid())
        try:
            self._bad_frame_streak = 0 if frame_ok else int(self._bad_frame_streak) + 1
        except Exception:
            self._bad_frame_streak = 0 if frame_ok else 1
        sensor_fault = bool(self._bad_frame_streak >= self.FAULT_AFTER_INVALID)

        # 1-3. Frame -> detections (concurrent with search; §5)
        processed = None
        detections: list = []
        if power_on and frame is not None and frame.valid():
            try:
                processed = self.frame_processor.process(frame)
            except Exception:
                processed = None
            try:
                self.detector.config = cfg
            except Exception:
                pass
            try:
                detections = self.detector.detect(processed, timestamp=ts, raw_frame=frame.image)
            except Exception:
                detections = []

        # 4. Association
        try:
            px_scale = 0.109
            try:
                px_scale = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_x", 109.0) or 109.0) * 0.001
            except Exception:
                pass
            self.tracks, _, unmatched = self.association.associate(detections, self.tracks, ts, dt)
            # score + lifecycle for hits; update FOV-space velocity for ALL
            # hit tracks so association prediction survives PTZ motion.
            # Own-ship compensation for velocity: FOV measurement moves
            # opposite to the camera, so v_world = d(meas)/dt + v_cam.
            # Without this, fast SEARCH sweeps poison est_vx and the
            # reacquisition prediction flings on loss.
            try:
                _cv = inp.current_ptz_velocity or (0.0, 0.0)
                cam_vx, cam_vy = float(_cv[0]), float(_cv[1])
                if not math.isfinite(cam_vx):
                    cam_vx = 0.0
                if not math.isfinite(cam_vy):
                    cam_vy = 0.0
            except Exception:
                cam_vx, cam_vy = 0.0, 0.0
            for tr in list(self.tracks.values()):
                if any(d is not None for d in detections) and tr.miss_count == 0 and tr.last_seen_timestamp == ts:
                    try:
                        prev_ex, prev_ey = tr.est_x, tr.est_y
                        inst_vx = (tr.meas_x - prev_ex) / max(dt, 1e-3) + cam_vx if (prev_ex or prev_ey) else 0.0
                        inst_vy = (tr.meas_y - prev_ey) / max(dt, 1e-3) + cam_vy if (prev_ex or prev_ey) else 0.0
                        inst_vx = max(-2000.0, min(2000.0, inst_vx))
                        inst_vy = max(-2000.0, min(2000.0, inst_vy))
                        tr.est_vx = 0.5 * inst_vx + 0.5 * tr.est_vx
                        tr.est_vy = 0.5 * inst_vy + 0.5 * tr.est_vy
                        tr.est_x, tr.est_y = tr.meas_x, tr.meas_y
                    except Exception:
                        pass
                    try:
                        self.signature.score_track(tr, pixel_to_angle_mrad=px_scale)
                        # EMA smoothing over the AM envelope: instantaneous
                        # minima must not veto an established signature.
                        raw_overall = float(tr.signature.overall_score)
                        prev_conf = float(tr.confidence) if tr.hit_count > 1 else raw_overall
                        ema = 0.35 * raw_overall + 0.65 * prev_conf
                        tr.signature.overall_score = float(ema)
                        tr.confidence = float(ema)
                    except Exception:
                        pass

                    # ── Step 4b: Beam Profile (optical characterisation) ─────────
                    try:
                        tr.beam_profile = BeamProfile(
                            power_dn=float(tr.meas_intensity),
                            snr_db=float(tr.meas_snr),
                            spot_mrad=float(tr.meas_spot_px * px_scale),
                            modulation_depth=float(tr.signature.temporal_score),
                        )
                    except Exception:
                        pass

                    # ── Step 4c: Communication path — signal + decode + identity ─
                    try:
                        hist = list(tr.temporal.intensity_history)
                        times = list(tr.temporal.timestamps) if tr.temporal.timestamps else []
                        chip_rate = float(getattr(self._target_profile, "chip_rate_hz", 8.0))
                        bg_est = float(getattr(processed, "background_estimate", 0.0) if processed else 0.0)
                        sig_meas = self._signal_analyzer.analyze(hist, times, chip_rate, bg_est)

                        # §8 & §27: OpticalMeasurement
                        tr.optical_measurement = OpticalMeasurement(
                            centroid_x=float(tr.meas_x),
                            centroid_y=float(tr.meas_y),
                            peak_intensity=float(tr.meas_intensity),
                            integrated_intensity=float(tr.meas_intensity * max(1.0, tr.meas_spot_px)),
                            snr=float(tr.meas_snr),
                            apparent_diameter=float(tr.meas_spot_px),
                            background_level=bg_est,
                            spectral_estimate=float(getattr(tr.signature, "spectral_score", 1.0) * 1550.0),
                            timestamp=float(ts),
                        )
                        # §9 & §27: SignalMeasurement
                        tr.signal_measurement = sig_meas
                        tr.optical_quality = float(tr.signature.overall_score)
                        tr.signal_quality = float(sig_meas.signal_quality)
                        tr.filtered_position = (float(tr.est_x), float(tr.est_y))
                        tr.predicted_position = (float(tr.est_x + tr.est_vx * dt), float(tr.est_y + tr.est_vy * dt))
                        tr.velocity = (float(tr.est_vx), float(tr.est_vy))
                        tr.acceleration = (float(tr.est_ax), float(tr.est_ay))

                        # Update SignalState from signal measurement
                        ss = tr.signal_state
                        ss.chip_rate_hz = float(sig_meas.estimated_chip_rate_hz)
                        ss.modulation_depth = float(sig_meas.modulation_depth)
                        ss.chip_snr_db = float(sig_meas.chip_snr_db)
                        ss.bit_error_estimate = float(sig_meas.bit_error_estimate)
                        ss.num_chip_samples = int(sig_meas.num_samples)
                        if sig_meas.sufficient_data:
                            ss.state = "DECODING"
                        elif sig_meas.num_samples >= 20:
                            ss.state = "SAMPLING"

                        # §12: Frame decoder
                        df = self._frame_decoder.update(
                            tr.observation_id, sig_meas, tr._decoded_frame)
                        tr._decoded_frame = df
                        ss.frame_valid = bool(df.valid)
                        ss.decoded_terminal_id_byte = int(df.terminal_id_byte)
                        ss.decoded_network_id = int(df.network_id)
                        ss.decoded_sequence = int(df.sequence_number)
                        ss.decoded_capabilities = int(df.capabilities)
                        ss.decode_confidence = float(df.confidence)
                        ss.consecutive_valid = int(df.consecutive_valid)
                        ss.total_attempts = int(df.attempt_count)
                        ss.total_successes = int(df.success_count)
                        if df.valid:
                            ss.state = "VALID"

                        # §14: Identity validator
                        decision = self._id_matcher.match(tr.observation_id, df)
                        tr._identity_decision = decision
                        ss.identity_matched = bool(decision.matched)
                        ss.identity_reason = str(decision.reason)
                        ss.identity_confidence = float(decision.confidence)

                        # Populate §27 candidate track fields
                        tr.decoded_terminal_id = str(df.terminal_id) or str(df.terminal_id_str)
                        tr.decoded_token = str(getattr(df, "token", ""))
                        tr.decoded_wavelength_nm = float(getattr(df, "wavelength_nm", 0.0))
                        tr.sequence_number = int(df.sequence_number)
                        tr.identity_state = str(decision.status)
                        tr.identity_confidence = float(decision.confidence)
                        if df.valid and df.crc_ok:
                            tr.valid_frame_count += 1
                            tr.last_valid_frame_time = float(ts)
                            tr.last_valid_sequence = int(df.sequence_number)
                            tr.latest_frame = df.frame
                        elif sig_meas.sufficient_data:
                            tr.invalid_frame_count += 1

                        tr.synchronization_state = {
                            "synced": bool(df.valid or (sig_meas.sufficient_data and sig_meas.num_samples >= 20)),
                            "confidence": float(df.confidence),
                        }

                        # Hard-reject impostors immediately (§14, §17)
                        if tr.is_impostor:
                            tr.lifecycle_state = CandidateState.REJECTED
                    except Exception:
                        pass

                    sig_ok, _ = self.signature.confirmed(tr)
                    score_ok = tr.signature.overall_score >= self.signature_cfg.minimum_score

                    # Multi-frame persistence (§16), windowed not consecutive:
                    # an AM dip must not reset the count. The acquisition
                    # window is authoritative; the streak mirrors it.
                    try:
                        win = self.acquisition._confirm_windows.get(tr.observation_id, [])
                        need = max(1, self.signature_cfg.minimum_confirmations)
                        persist_ok = sum(1 for v in win[-8:] if v >= 0) >= need
                    except Exception:
                        persist_ok = False
                    if sig_ok and score_ok:
                        self._confirm_streak[tr.observation_id] = self._confirm_streak.get(tr.observation_id, 0) + 1
                    elif tr.miss_count == 0 and tr.hit_count > 1:
                        pass  # keep streak through dips; misses reset below
                    else:
                        self._confirm_streak[tr.observation_id] = 0
                    persist_ok = persist_ok or (self._confirm_streak.get(tr.observation_id, 0) >= max(1, self.signature_cfg.minimum_confirmations))
                    self.lifecycle.update_on_hit(tr, sig_ok and persist_ok, score_ok and persist_ok)
                    tr.uncertainty = max(0.1, 2.0 / (1.0 + tr.hit_count))
            # misses (tolerate <=3-frame gaps: keep streak, lifecycle coasts)
            seen_ids = {t.observation_id for t in self.tracks.values() if t.last_seen_timestamp == ts}
            for tr in list(self.tracks.values()):
                if tr.observation_id not in seen_ids:
                    self.lifecycle.update_on_miss(tr)
                    if tr.miss_count > 3:
                        self._confirm_streak[tr.observation_id] = 0
            # purge expired/rejected beyond grace
            for tid in list(self.tracks.keys()):
                if self.tracks[tid].lifecycle_state in (CandidateState.EXPIRED, CandidateState.REJECTED):
                    if self.tracks[tid].miss_count > 60:
                        del self.tracks[tid]
                        self._confirm_streak.pop(tid, None)
            # Overload cap (§36: too many candidates): hard bound at 96
            # tracks so memory/compute stay flat no matter the clutter.
            # Ranked by SIGNAL VALUE (confidence first, staleness penalized)
            # so a newborn high-quality beacon outranks established junk:
            # lifecycle seniority alone would starve a true beacon that
            # appears while the cap is full of clutter. The active lock is
            # never culled. 96x96 association ≈ 9k cost evals/frame — trivial.
            try:
                if len(self.tracks) > 96:
                    _rank = {
                        CandidateState.TRACKING: 9, CandidateState.ACQUIRED: 8,
                        CandidateState.SELECTED: 7, CandidateState.IDENTIFIED: 6,
                        CandidateState.REACQUIRING: 5, CandidateState.DEGRADED: 4,
                        CandidateState.VALIDATING: 3, CandidateState.TENTATIVE: 2,
                        CandidateState.SEEN: 1, CandidateState.LOST: 0,
                        CandidateState.REJECTED: -1, CandidateState.EXPIRED: -2,
                    }

                    def _value(t: CandidateTrack) -> tuple:
                        return (float(t.confidence) * 10.0
                                + _rank.get(t.lifecycle_state, 0) * 0.5
                                + min(int(t.hit_count), 10) * 0.1
                                - max(0, int(t.miss_count)) * 1.0,
                                int(t.hit_count))
                    ordered = sorted(self.tracks.values(), key=_value, reverse=True)
                    keep_ids = {t.observation_id for t in ordered[:96]}
                    if self.active_observation_id is not None:
                        keep_ids.add(self.active_observation_id)
                    for tid in list(self.tracks.keys()):
                        if tid not in keep_ids:
                            try:
                                del self.tracks[tid]
                            except KeyError:
                                pass
                            self._confirm_streak.pop(tid, None)
                            try:
                                self.acquisition._confirm_windows.pop(tid, None)
                            except Exception:
                                pass
            except Exception:
                pass
        except Exception:
            unmatched = []

        alive = [t for t in self.tracks.values()
                 if t.lifecycle_state not in (CandidateState.EXPIRED, CandidateState.REJECTED, CandidateState.LOST)]
        has_candidates = len(alive) > 0
        has_identified = any(t.lifecycle_state in (CandidateState.IDENTIFIED, CandidateState.SELECTED,
                                                   CandidateState.ACQUIRED, CandidateState.TRACKING,
                                                   CandidateState.DEGRADED, CandidateState.REACQUIRING)
                             for t in alive)

        # 5. Selection + acquisition (§§17-18). Sticky selection: the
        # active track is preferred while competitive so a single-frame
        # decoy spike cannot steal acquisition (§17 hysteresis).
        selection = None
        try:
            selection = self.acquisition.select(alive)
            if (selection is not None and self.active_observation_id is not None
                    and selection.observation_id != self.active_observation_id):
                active_alive = self.tracks.get(self.active_observation_id)
                if (active_alive is not None and active_alive in alive
                        and active_alive.miss_count <= 2
                        and active_alive.signature.overall_score >= selection.signature.overall_score - 0.15):
                    selection = active_alive
        except Exception:
            selection = None
        acq_result = AcquisitionResult(acquired=False, timestamp=ts)
        try:
            # Maintain an existing lock from the ACTIVE track: confirming
            # only the best selection lets a bright decoy veto the lock
            # for a frame (§17). New acquisitions use `selection`.
            active_alive = (self.tracks.get(self.active_observation_id)
                            if self.active_observation_id else None)
            if active_alive is not None and active_alive in alive and active_alive.miss_count <= 2:
                confirm_target = active_alive
            else:
                confirm_target = selection
            # A missed frame is not a confirmation: stale scores must not
            # re-confirm. Brief gaps are bridged by latched_acquired below.
            if confirm_target is not None and confirm_target.miss_count == 0:
                acq_result = self.acquisition.confirm(confirm_target, ts)
                selection = confirm_target
            elif confirm_target is not None:
                # record the gap so the window drains during outages
                self.acquisition.confirm(None, ts)
                if confirm_target.observation_id in self.acquisition._confirm_windows:
                    self.acquisition._confirm_windows[confirm_target.observation_id].append(-1.0)
        except Exception:
            pass

        # sticky active id with hysteresis (2-frame handover)
        # Latch acquisition through brief single-frame dropouts: if the
        # active track missed this frame but missed <=2, keep acquired.
        latched_acquired = False
        if selection is not None and self.active_observation_id == selection.observation_id:
            if selection.miss_count <= 2 and self._confirm_streak.get(selection.observation_id, 0) >= 1:
                latched_acquired = True
        if (acq_result.acquired or latched_acquired) and selection is not None:
            if self.active_observation_id is None or self.active_observation_id == selection.observation_id:
                self.active_observation_id = selection.observation_id
                if latched_acquired and not acq_result.acquired:
                    acq_result = AcquisitionResult(acquired=True, observation_id=selection.observation_id,
                                                   confidence=float(selection.signature.overall_score),
                                                   timestamp=float(ts))
            else:
                # require 2 consecutive confirmations before switching identity
                streak = self._confirm_streak.get(selection.observation_id, 0)
                if streak >= 2:
                    self.active_observation_id = selection.observation_id
            try:
                self.search.suspend()
            except Exception:
                pass
        elif has_identified:
            # An acceptable candidate is visible: suspend search immediately
            # (§5) so the scan does not drag the target out of FOV while
            # persistence builds.
            try:
                self.search.suspend()
            except Exception:
                pass
        # keep active during coast; drop only on timeout/LOST

        active_track = self.tracks.get(self.active_observation_id) if self.active_observation_id else None
        if active_track is not None and active_track.lifecycle_state in (CandidateState.LOST, CandidateState.EXPIRED):
            self.active_observation_id = None
            active_track = None
            # Track died before the reacq timer fired: release the timer so
            # the state machine can fall through LOST -> SEARCHING (§28)
            # instead of freezing in REACQUIRING.
            if self.reacq.active:
                self.reacq.reset()

        # 6. Tracking vs reacquisition vs search
        target_state = TargetState(valid=False, timestamp=ts)
        ptz_cmd: PTZCommand | None = None
        search_cmd: SearchCommand | None = None
        tracking_ok = False
        degraded = False
        reacquiring = self.reacq.active
        # If the timer was just released with no active track, report the
        # timeout so REACQUIRING -> LOST fires this cycle.
        reacq_timeout = bool(not reacquiring and self.state_machine.state == LocalTerminalState.REACQUIRING
                             and self.active_observation_id is None)

        trk_mode = "AUTO"
        try:
            trk_mode = str(getattr(getattr(cfg, "tracking", None), "mode", "AUTO") or "AUTO").upper()
        except Exception:
            pass
        can_track = trk_mode in ("AUTO", "TRACKING")
        acq_mode = "AUTO"
        try:
            acq_mode = str(getattr(getattr(cfg, "acquisition", None), "mode", "AUTO") or "AUTO").upper()
        except Exception:
            pass
        is_search_mode = acq_mode in ("AUTO", "SEARCH", "AUTO_ACQUISITION")

        cam_vel = inp.current_ptz_velocity or (0.0, 0.0)
        center = (fov_w * 0.5, fov_h * 0.5)

        if power_on and can_track and acq_result.acquired and selection is not None and selection.miss_count <= 2:
            # --- TRACKING (§§20-21), miss-tolerant: coast through <=2-frame
            # dropouts (AM envelope minima) using last estimate (§25) ---
            if self.reacq.active:
                self.reacq.reset()
            self._loss_streak = 0
            reacquiring = False
            track_for_est = selection
            try:
                target_state = self.estimator.update(track_for_est, dt, ts, camera_vel=cam_vel)
            except Exception:
                target_state = TargetState(valid=False, timestamp=ts)
            # If this frame was a miss, hold last filtered estimate valid.
            if selection.last_seen_timestamp != ts:
                target_state.valid = True
                degraded = True
            # error from FILTERED estimate vs FOV center
            err_x = target_state.filtered_x - center[0]
            err_y = target_state.filtered_y - center[1]
            if not math.isfinite(err_x):
                err_x = 0.0
            if not math.isfinite(err_y):
                err_y = 0.0
            try:
                res = self.controller.update(dt, True, (target_state.filtered_x, target_state.filtered_y),
                                             (fov_w, fov_h), camera_vel=cam_vel)
                perr_x, perr_y = res.get("error_px", (err_x, err_y))
            except Exception:
                perr_x, perr_y = err_x, err_y
            # centering with hysteresis (§23)
            dist = math.hypot(perr_x, perr_y)
            if dist <= self.CENTER_TOL_PX:
                self._centered_latched = True
            elif dist > self.CENTER_TOL_PX * 2.0:
                self._centered_latched = False
            self._lock_dwell = self._lock_dwell + dt if self._centered_latched else max(0.0, self._lock_dwell - dt * 2)
            # signature retention (§24)
            conf = selection.signature.overall_score
            if conf < self.tracking_retention_threshold:
                degraded = True
                selection.lifecycle_state = CandidateState.DEGRADED
            else:
                if selection.lifecycle_state in (CandidateState.ACQUIRED, CandidateState.SELECTED,
                                                 CandidateState.IDENTIFIED, CandidateState.DEGRADED):
                    selection.lifecycle_state = CandidateState.TRACKING
                tracking_ok = True

            # ── Step 7b: Continuous identity verification (Phase-2) ──────────
            # Every frame we check whether the decoded identity is still valid.
            # If it fails for max_identity_fail_streak consecutive frames →
            # impostor-swap or link loss → force REACQUIRING.
            try:
                ss = selection.signal_state
                max_streak = int(getattr(self._target_profile, "max_identity_fail_streak", 10))
                # Only check when we have an active identity profile (non-wildcard)
                profile_has_id = (int(self._target_profile.expected_terminal_id_byte) != 0)
                if profile_has_id and ss.state in ("VALID", "DECODING"):
                    if not ss.identity_matched and ss.identity_reason not in ("NO_DATA", "BUILDING"):
                        ss.identity_fail_streak += 1
                    else:
                        ss.identity_fail_streak = 0
                    if ss.identity_fail_streak >= max_streak:
                        # Identity lost or swapped → force reacquisition
                        degraded = True
                        tracking_ok = False
                        selection.lifecycle_state = CandidateState.DEGRADED
                        ss.state = "LOST"
            except Exception:
                pass

            try:
                cx, cy = self.controller.compute_control(float(perr_x), float(perr_y), dt)
            except Exception:
                cx, cy = 0.0, 0.0
            cur_pan, cur_tilt = inp.current_ptz_pose or (0.0, 0.0)
            ptz_cmd = PTZCommand(target_pan=float(cur_pan) + float(cx),
                                 target_tilt=float(cur_tilt) + float(cy),
                                 pan_velocity=float(cx) / max(dt, 1e-3),
                                 tilt_velocity=float(cy) / max(dt, 1e-3))
        elif power_on and self.active_observation_id is not None:

            # --- loss path: DEGRADED -> REACQUIRING -> LOST (§§25-27) ---
            # Require 3 consecutive non-acquired frames before declaring
            # reacquisition so single-frame decoy spikes do not trip it.
            self._loss_streak = int(getattr(self, "_loss_streak", 0)) + 1
            prev = self.tracks.get(self.active_observation_id)
            if prev is not None and not self.reacq.active and self._loss_streak >= 3:
                try:
                    cur_p, cur_t = inp.current_ptz_pose or (0.0, 0.0)
                    self._reacq_anchor_pan = float(cur_p)
                    self._reacq_anchor_tilt = float(cur_t)
                    self.reacq.begin((float(prev.est_x), float(prev.est_y)),
                                     (float(prev.est_vx), float(prev.est_vy)),
                                     prev.observation_id, float(prev.signature.overall_score))
                except Exception:
                    pass
            if self.reacq.active:
                # Identity-gated merge: reappearing beacon keeps its old lock
                # instead of spawning a fresh BEACON-N (§27/§30).
                try:
                    from local_terminal.reacquisition import can_merge_reacquisition as _can_merge
                    if prev is not None:
                        for _cand in (alive or []):
                            try:
                                if _cand.observation_id == self.active_observation_id:
                                    continue
                                if _can_merge(prev, _cand,
                                              predicted_pos=getattr(self.reacq, "last_known", None)):
                                    self.active_observation_id = _cand.observation_id
                                    prev = _cand
                                    self._loss_streak = 0
                                    self.reacq.reset()
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
                if self.reacq.active:
                    timed_out = self.reacq.step(dt)
                    # NOTE: predict() mutates last_known — it is called exactly
                    # once per frame in the coast branch below (§26). Do not
                    # predict here or the coast double-steps.
                else:
                    timed_out = False
                if timed_out:
                    reacq_timeout = True
                    self.reacq.reset()
                    if prev is not None:
                        prev.lifecycle_state = CandidateState.LOST
                    self.active_observation_id = None
                    self._confirm_streak.clear()
                    try:
                        self.estimator.reset()
                        self.controller.reset()
                    except Exception:
                        pass
                    if is_search_mode:
                        try:
                            # Resume the global sweep near the last predicted
                            # direction (§26 stage 5) instead of jumping to
                            # the region edge — seamless REACQ → SEARCH.
                            px, py = 0.0, 0.0
                            try:
                                if self.reacq.last_known is not None:
                                    px = float(self.reacq.last_known[0]) - float(center[0])
                                    py = float(self.reacq.last_known[1]) - float(center[1])
                                    sx0 = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_x", 109.0) or 109.0) * 0.001
                                    sy0 = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_y", 109.0) or 109.0) * 0.001
                                    ppx0 = 17.453292519943295 / max(1e-6, sx0)
                                    ppy0 = 17.453292519943295 / max(1e-6, sy0)
                                    px = px / max(1.0, ppx0)
                                    py = py / max(1.0, ppy0)
                            except Exception:
                                px, py = 0.0, 0.0
                            try:
                                p_min = float(self.search.scanner.config.search_region_pan_min)
                                p_max = float(self.search.scanner.config.search_region_pan_max)
                                t_min = float(self.search.scanner.config.search_region_tilt_min)
                                t_max = float(self.search.scanner.config.search_region_tilt_max)
                                px = max(p_min, min(p_max, px))
                                py = max(t_min, min(t_max, py))
                            except Exception:
                                pass
                            self.search.start_at(float(px), float(py))
                        except Exception:
                            pass
                elif self.reacq.active:
                    reacquiring = True
                    degraded = True
                    if prev is not None:
                        prev.lifecycle_state = CandidateState.REACQUIRING
                    # Predictive coast + expanding local spiral (§26):
                    # hold the predicted direction, then dither around it
                    # with a stage radius (±2° → ±5° → ±10°) so a drifting
                    # target is re-swept instead of waiting passively.
                    try:
                        pred = self.reacq.predict(dt)
                    except Exception:
                        pred = None
                    try:
                        sx = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_x", 109.0) or 109.0) * 0.001
                        sy = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_y", 109.0) or 109.0) * 0.001
                        ppx = 17.453292519943295 / max(1e-6, sx)
                        ppy = 17.453292519943295 / max(1e-6, sy)
                    except Exception:
                        ppx, ppy = 160.0, 160.0
                    try:
                        stage = self.reacq.stage()
                        stage_r_deg = float(getattr(stage, "radius_deg", 2.0))
                    except Exception:
                        stage_r_deg = 2.0
                    try:
                        base_vx = float(self.controller.vel_x)
                        base_vy = float(self.controller.vel_y)
                    except Exception:
                        base_vx, base_vy = 0.0, 0.0
                    # FOV-space prediction error: drive PTZ so the predicted
                    # point returns to FOV center (scene px == FOV px units).
                    if pred is not None:
                        perr_x = float(pred[0]) - float(center[0])
                        perr_y = float(pred[1]) - float(center[1])
                    else:
                        perr_x, perr_y = base_vx * dt, base_vy * dt
                    if not math.isfinite(perr_x):
                        perr_x = 0.0
                    if not math.isfinite(perr_y):
                        perr_y = 0.0
                    # Expanding spiral dither around prediction; one
                    # revolution ~1.2 s, radius grows with stage. Clamped
                    # so the sweep stays smooth (no teleport).
                    import math as _math
                    _ang = (self.reacq.elapsed * 2.0 * _math.pi / 1.2)
                    _r_px = min(120.0, stage_r_deg * min(ppx, ppy) * 0.25)
                    dith_x = _r_px * _math.cos(_ang)
                    dith_y = _r_px * _math.sin(_ang) * 0.75
                    # 0.8 prediction gain + dither; per-step clamp keeps
                    # motion inside PTZ slew capability for smoothness.
                    try:
                        deg = float(getattr(getattr(cfg, "ptz", None), "pan_speed", 8.0) or 8.0)
                        max_step = deg * ppx * dt
                    except Exception:
                        max_step = 40.0
                    anchor_p = float(getattr(self, "_reacq_anchor_pan", float(cur_pan if 'cur_pan' in locals() else 500.0)))
                    anchor_t = float(getattr(self, "_reacq_anchor_tilt", float(cur_tilt if 'cur_tilt' in locals() else 500.0)))
                    desired_p = anchor_p + 0.8 * perr_x + dith_x * 0.5
                    desired_t = anchor_t + 0.8 * perr_y + dith_y * 0.5
                    cur_pan, cur_tilt = inp.current_ptz_pose or (0.0, 0.0)
                    cx = max(-max_step, min(max_step, desired_p - float(cur_pan)))
                    cy = max(-max_step, min(max_step, desired_t - float(cur_tilt)))
                    ptz_cmd = PTZCommand(target_pan=float(cur_pan) + float(cx),
                                         target_tilt=float(cur_tilt) + float(cy),
                                         pan_velocity=float(cx) / max(dt, 1e-3),
                                         tilt_velocity=float(cy) / max(dt, 1e-3))
                else:
                    # Merged this frame: lock handed to the reobserved track.
                    # Hold position; confirmation resumes next cycle.
                    degraded = True
                    reacquiring = False
            else:
                degraded = True
        else:
            # --- SEARCH (§5): move->capture->detect->evaluate loop ---
            # Hold position while unconfirmed candidates are being validated
            # so the scan does not drag a tentative target out of FOV before
            # temporal persistence can build. The hold is BOUNDED: stale
            # VALIDATING tracks (age>2 s, never promoting — typically
            # clutter/stars) release the sweep, otherwise one bright star
            # would freeze the search forever with the true target outside.
            if power_on and is_search_mode and not (acq_result.acquired):
                holdable = [t for t in alive if t.lifecycle_state in (
                    CandidateState.SEEN, CandidateState.TENTATIVE,
                    CandidateState.SIGNAL_DETECTED, CandidateState.DECODING,
                    CandidateState.IDENTITY_UNKNOWN,
                    CandidateState.IDENTIFIED, CandidateState.SELECTED,
                    CandidateState.ACQUIRED, CandidateState.TRACKING,
                    CandidateState.DEGRADED, CandidateState.REACQUIRING) or (
                    t.lifecycle_state == CandidateState.VALIDATING and t.age < 2.0)]
                # Anti-pin watchdog: an UNCONFIRMED pool (stars/clutter scoring
                # ~0.7 but never identifying) must not freeze the sweep forever.
                # Confirmed candidates hold indefinitely; unconfirmed ones get
                # at most 1.5 s of hold per 1.0 s of forced sweep so coverage
                # always progresses. Obvious junk (best overall < 0.35) never
                # holds at all.
                _confirmed_hold = [t for t in holdable if t.lifecycle_state in (
                    CandidateState.SIGNAL_DETECTED, CandidateState.DECODING,
                    CandidateState.IDENTITY_UNKNOWN,
                    CandidateState.IDENTIFIED, CandidateState.SELECTED,
                    CandidateState.ACQUIRED, CandidateState.TRACKING,
                    CandidateState.DEGRADED, CandidateState.REACQUIRING)]
                do_hold = bool(holdable)
                if do_hold and not _confirmed_hold:
                    try:
                        _best_score = max(float(t.signature.overall_score) for t in holdable)
                    except Exception:
                        _best_score = 0.0
                    if _best_score < 0.35:
                        do_hold = False
                    elif float(getattr(self, "_hold_cooldown", 0.0)) > 0.0:
                        do_hold = False
                        try:
                            self._hold_cooldown = max(0.0, float(self._hold_cooldown) - dt)
                        except Exception:
                            pass
                    else:
                        try:
                            self._hold_time = float(getattr(self, "_hold_time", 0.0)) + dt
                        except Exception:
                            self._hold_time = dt
                        if float(self._hold_time) > 1.5:
                            self._hold_time = 0.0
                            self._hold_cooldown = 1.0
                            do_hold = False
                else:
                    try:
                        self._hold_time = 0.0
                        if _confirmed_hold:
                            self._hold_cooldown = 0.0
                    except Exception:
                        pass
                if do_hold:
                    try:
                        self.search.suspend()
                    except Exception:
                        pass
                    search_cmd = SearchCommand()
                    # Coarse acquisition servo (§11): keep the candidate cluster
                    # framed while persistence builds. EXPLORE vs EXPLOIT:
                    # a confirmed candidate is chased directly, but scores
                    # are immature pre-identification (single-frame spectral
                    # ties), so an unconfirmed pool is servoed by centroid —
                    # chasing max-score then drags the camera to edge clutter
                    # while the true beacon sits at center.
                    try:
                        _confirmed = [t for t in holdable if t.lifecycle_state in (
                            CandidateState.SIGNAL_DETECTED, CandidateState.DECODING,
                            CandidateState.IDENTITY_UNKNOWN,
                            CandidateState.IDENTIFIED, CandidateState.SELECTED,
                            CandidateState.ACQUIRED, CandidateState.TRACKING,
                            CandidateState.DEGRADED, CandidateState.REACQUIRING)]
                        if _confirmed:
                            _tgt = max(_confirmed, key=lambda t: (
                                float(t.signature.overall_score), int(t.hit_count)))
                            bx, by = float(_tgt.meas_x), float(_tgt.meas_y)
                        else:
                            bx = sum(float(t.meas_x) for t in holdable) / max(1, len(holdable))
                            by = sum(float(t.meas_y) for t in holdable) / max(1, len(holdable))
                        ex, ey = bx - float(center[0]), by - float(center[1])
                        dz = 5.0
                        if abs(ex) < dz:
                            ex = 0.0
                        if abs(ey) < dz:
                            ey = 0.0
                        # gentle gain + per-step clamp for smooth approach
                        gx, gy = 0.35 * ex, 0.35 * ey
                        try:
                            _deg = float(getattr(getattr(cfg, "ptz", None), "pan_speed", 8.0) or 8.0)
                            _sx = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_x", 109.0) or 109.0) * 0.001
                            _ppx = 17.453292519943295 / max(1e-6, _sx)
                            _cap = max(6.0, min(60.0, _deg * _ppx * dt * 1.2))
                        except Exception:
                            _cap = 30.0
                        gx = max(-_cap, min(_cap, gx))
                        gy = max(-_cap, min(_cap, gy))
                    except Exception:
                        gx, gy = 0.0, 0.0
                    cur_pan, cur_tilt = inp.current_ptz_pose or (0.0, 0.0)
                    ptz_cmd = PTZCommand(target_pan=float(cur_pan) + float(gx),
                                         target_tilt=float(cur_tilt) + float(gy),
                                         pan_velocity=float(gx) / max(dt, 1e-3),
                                         tilt_velocity=float(gy) / max(dt, 1e-3))
                else:
                    try:
                        if not self.search.scanner.active:
                            self.search.start()
                        else:
                            self.search.resume()
                        search_cmd, timed_out = self.search.step(dt)
                        # convert deg offsets to absolute px pose
                        try:
                            home_pan = float(getattr(getattr(cfg, "ptz", None), "home_pan", 1000.0) or 1000.0)
                            home_tilt = float(getattr(getattr(cfg, "ptz", None), "home_tilt", 1000.0) or 1000.0)
                            sx = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_x", 109.0) or 109.0) * 0.001
                            sy = float(getattr(getattr(cfg, "angular_model", None), "pixel_to_angle_y", 109.0) or 109.0) * 0.001
                            ppx = 17.453292519943295 / max(1e-6, sx)
                            ppy = 17.453292519943295 / max(1e-6, sy)
                        except Exception:
                            home_pan, home_tilt, ppx, ppy = 1000.0, 1000.0, 160.0, 160.0
                        cur_pan, cur_tilt = inp.current_ptz_pose or (0.0, 0.0)
                        tgt_pan = home_pan + search_cmd.desired_pan * ppx
                        tgt_tilt = home_tilt + search_cmd.desired_tilt * ppy
                        # Rate-limit the sweep step to PTZ slew capability
                        # so SEARCH motion is smooth (no saturation judder
                        # when search_speed > actuator speed).
                        try:
                            _pdeg = float(getattr(getattr(cfg, "ptz", None), "pan_speed", 8.0) or 8.0)
                            _tdeg = float(getattr(getattr(cfg, "ptz", None), "tilt_speed", 8.0) or 8.0)
                            _capx = max(4.0, _pdeg * ppx * dt * 1.2)
                            _capy = max(4.0, _tdeg * ppy * dt * 1.2)
                            _dx = max(-_capx, min(_capx, float(tgt_pan) - float(cur_pan)))
                            _dy = max(-_capy, min(_capy, float(tgt_tilt) - float(cur_tilt)))
                            tgt_pan, tgt_tilt = float(cur_pan) + _dx, float(cur_tilt) + _dy
                        except Exception:
                            pass
                        ptz_cmd = PTZCommand(target_pan=float(tgt_pan), target_tilt=float(tgt_tilt),
                                             pan_velocity=0.0, tilt_velocity=0.0)
                    except Exception:
                        search_cmd = None

        # 7. Global state machine (§28) + sensor FAULT latch (§36)
        try:
            new_state = self.state_machine.step(
                has_candidates=has_candidates, has_identified=has_identified,
                acquired=bool(acq_result.acquired), tracking_ok=tracking_ok,
                degraded=degraded, reacquiring=reacquiring,
                reacq_timeout=reacq_timeout, power_on=power_on,
                sensor_fault=sensor_fault)
        except Exception:
            new_state = LocalTerminalState.SEARCHING
        if sensor_fault:
            # Fail safe: release the lock, stop the timers, hold position.
            # Tracks are retained for telemetry but no acquisition/tracking
            # may proceed on invalid frames.
            try:
                self.active_observation_id = None
                self._confirm_streak.clear()
                self.reacq.reset()
                self.estimator.reset()
                self.controller.reset()
                self.search.suspend()
            except Exception:
                pass
            try:
                cur_pan, cur_tilt = inp.current_ptz_pose or (0.0, 0.0)
                ptz_cmd = PTZCommand(target_pan=float(cur_pan),
                                     target_tilt=float(cur_tilt),
                                     pan_velocity=0.0, tilt_velocity=0.0)
            except Exception:
                pass

        # 8. Tracking status (§30) + link dwell
        try:
            err = (target_state.filtered_x - center[0], target_state.filtered_y - center[1]) if target_state.valid else (0.0, 0.0)
        except Exception:
            err = (0.0, 0.0)
        status = TrackingStatus(
            target_visible=bool(target_state.valid and active_track is not None and active_track.last_seen_timestamp == ts),
            target_identified=bool(has_identified),
            target_acquired=bool(acq_result.acquired),
            target_centered=bool(self._centered_latched and tracking_ok),
            confidence=float(target_state.confidence if target_state.valid else (active_track.confidence if active_track else 0.0)),
            snr=float(target_state.snr if target_state.valid else (active_track.meas_snr if active_track else 0.0)),
            tracking_error_x=float(err[0]), tracking_error_y=float(err[1]),
            state=new_state)

        out = UpdateOutput(local_terminal_state=new_state, search_command=search_cmd,
                           candidate_tracks=alive, active_observation_id=self.active_observation_id,
                           target_state=target_state, ptz_command=ptz_cmd,
                           tracking_status=status, telemetry={})
        try:
            out.telemetry = self.telemetry.build(out, {"frame_id": self.frame_id, "timestamp": ts,
                                                       "reacq_elapsed": self.reacq.elapsed,
                                                       "lock_dwell": self._lock_dwell})
        except Exception:
            pass
        self.last_output = out
        return out
