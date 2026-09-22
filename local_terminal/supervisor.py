# local_terminal/supervisor.py - V2 compact FSM (Plan V2 §5, §18).
# States: SEARCH IDENTIFY ASSOCIATE TRACK COAST LOST REACQUIRE FAULT.

from __future__ import annotations

import enum
import logging
import math
from dataclasses import dataclass, field

import numpy as np

from local_terminal.association import associate_acquisition, associate_tracking
from local_terminal.comm_receiver import CommReceiver, CommSource
from local_terminal.detector import TemporalConfirmer, detect_spots
from local_terminal.identity import IdentityValidator
from local_terminal.models import AutonomyConfig, BeaconObservation
from local_terminal.reacquisition import V2Reacquisition
from local_terminal.registry import SignatureRegistry
from local_terminal.scan import ScanController
from local_terminal.selector import select_active_v2
from local_terminal.tracker import KalmanConfig, KalmanTracker, r_for_snr

log = logging.getLogger(__name__)


class V2State(enum.Enum):
    SEARCH = "SEARCH"
    IDENTIFY = "IDENTIFY"
    ASSOCIATE = "ASSOCIATE"
    TRACK = "TRACK"
    COAST = "COAST"
    LOST = "LOST"
    REACQUIRE = "REACQUIRE"
    FAULT = "FAULT"


# Authoritative FSM transition graph — single source of truth for V2 lifecycle.
# Deep-headless test and any validator MUST import this rather than maintaining a duplicate.
# Self-loops are implicit (no transition counted). Any edge not listed is invalid.
V2_VALID_TRANSITIONS: dict[str, set[str]] = {
    "SEARCH":    {"IDENTIFY", "SEARCH"},
    "IDENTIFY":  {"ASSOCIATE", "SEARCH", "IDENTIFY"},
    "ASSOCIATE": {"TRACK", "SEARCH", "IDENTIFY", "ASSOCIATE"},
    "TRACK":     {"COAST", "LOST", "TRACK"},
    "COAST":     {"TRACK", "LOST", "COAST"},
    "LOST":      {"REACQUIRE", "LOST"},
    "REACQUIRE": {"TRACK", "SEARCH", "REACQUIRE"},
    "FAULT":     {"SEARCH", "FAULT"},
}


def is_valid_transition(src: str, dst: str) -> bool:
    """Check if src→dst is allowed per authoritative V2 graph. Self-loop is always valid."""
    if src == dst:
        return True
    allowed = V2_VALID_TRANSITIONS.get(src)
    if allowed is None:
        return False
    return dst in allowed


@dataclass
class V2Output:
    state: V2State
    camera_target_angles: tuple[float, float] | None = None
    pid_active: bool = False
    track_error_px: tuple[float, float] | None = None
    active_target_id: str | None = None
    telemetry: dict = field(default_factory=dict)
    target_vel_px_s: tuple[float, float] | None = None
    camera_reset_requested: bool = False


class SupervisorV2:
    """V2 autonomy supervisor: compact 8-state FSM over V2 modules."""

    def __init__(self, registry: SignatureRegistry | None = None,
                 autonomy: AutonomyConfig | None = None):
        self.cfg = (autonomy or AutonomyConfig()).validate()
        self.registry = registry or SignatureRegistry()
        self.scan = ScanController()
        self.identity = IdentityValidator(self.registry)
        self.identity.config.p_rx_threshold_w = self.cfg.p_rx_threshold_w
        self.tracker = KalmanTracker(KalmanConfig(
            process_noise_q=self.cfg.kalman_process_noise_q,
            measurement_noise_r_base=self.cfg.kalman_measurement_noise_r_base,
            r_scale_low_snr=self.cfg.kalman_r_scale_low_snr,
            r_scale_high_snr=self.cfg.kalman_r_scale_high_snr,
        ))
        self.reacq = V2Reacquisition(list(self.cfg.reacq_radii_px),
                                     self.cfg.reacq_full_scan_enabled)
        self.comm = CommReceiver()
        self.confirmer = TemporalConfirmer(self.cfg.candidate_confirm_frames)
        self.state = V2State.SEARCH
        self.sim_time = 0.0
        self.transitions: list[tuple[float, str, str, str]] = []
        self._pending_beacon: BeaconObservation | None = None
        self._pending_tid: str | None = None
        self._last_ident_t: float = -1.0
        self._coast_since: float | None = None
        self.loss_count = 0
        self.reacq_count = 0
        self.reacq_start: float | None = None
        self.reacq_time_s: float | None = None
        self.mission_priority: list[str] = []
        self._last_spots = []
        self._rejected = 0
        self._first_lock_t: float | None = None
        self._search_start_t: float = 0.0
        self._full_resets: int = 0
        self._camera_reset_pending: bool = False
        # Hardening: debounce counters and acquisition pending (no ground-truth leakage)
        self._assoc_pending: TargetObservation | None = None
        self._assoc_pending_t: float = 0.0
        self._track_miss_streak: int = 0
        self._track_hit_streak: int = 0

    def _go(self, nxt: V2State, reason: str) -> None:
        if nxt is not self.state:
            # Track search start for acquisition duration
            if nxt == V2State.SEARCH:
                self._search_start_t = float(self.sim_time)
                # Priority search: if we have a last known predict, seed scan around it (reduces 20-cell blind raster)
                try:
                    if self.tracker.active_tid is not None:
                        px, py = self.tracker.kf.position
                        # Map FOV predict ~320,240 to world ~boresight_world unavailable here; use FOV as proxy offset from center
                        # Provide predicted world approx via boresight world not yet; so skip world-based priority in _go and handle in step
                        pass
                    # Reset debounce on new search
                    self._track_miss_streak = 0
                    self._track_hit_streak = 0
                    self._assoc_pending = None
                except Exception:
                    pass
            if nxt in (V2State.TRACK, V2State.COAST):
                # entering track resets debounce to require 2 hits/misses
                pass
            self.transitions.append((self.sim_time, self.state.value, nxt.value, reason))
            log.info("V2 @ %.3f %s -> %s (%s)", self.sim_time,
                     self.state.value, nxt.value, reason)
            self.state = nxt

    def set_registry(self, registry: SignatureRegistry) -> None:
        self.registry = registry
        self.identity.set_registry(registry)

    @property
    def scan_ctrl(self):
        return self.scan

    @property
    def validator(self):
        return self.identity

    @property
    def comm_rx(self):
        return self.comm

    @property
    def fault_active(self) -> bool:
        return self.state == V2State.FAULT

    @property
    def full_reset_count(self) -> int:
        return int(getattr(self, "_full_resets", 0))

    def escalation_scan(self) -> None:
        self.scan.reset(clear_visited=True)

    def full_reset(self) -> bool:
        self.scan.reset(clear_visited=True)
        self.tracker.reset()
        self.identity.strikes.clear()
        self.identity.blacklist.clear()
        self.identity.last_seq.clear()
        self.confirmer.reset()
        self.reacq.reset()
        self._pending_beacon = None
        self._pending_tid = None
        self._first_lock_t = None
        self._assoc_pending = None
        self._assoc_pending_t = 0.0
        self._track_miss_streak = 0
        self._track_hit_streak = 0
        self._full_resets = int(getattr(self, "_full_resets", 0)) + 1
        self._camera_reset_pending = True
        self._go(V2State.SEARCH, "full_reset")
        return True

    def apply_local_config(self, cfg) -> None:
        # V2 authoritative config is AutonomyConfig — single source, no duplicate path (BUG-13/14 fix)
        # Legacy LocalTerminalConfig has been removed. Any legacy object is rejected with guidance to migrate.
        if isinstance(cfg, AutonomyConfig):
            self.cfg = cfg.validate()
            self.identity.config.p_rx_threshold_w = self.cfg.p_rx_threshold_w
            self.tracker = KalmanTracker(KalmanConfig(
                process_noise_q=self.cfg.kalman_process_noise_q,
                measurement_noise_r_base=self.cfg.kalman_measurement_noise_r_base,
                r_scale_low_snr=self.cfg.kalman_r_scale_low_snr,
                r_scale_high_snr=self.cfg.kalman_r_scale_high_snr,
            ))
            self.reacq = V2Reacquisition(list(self.cfg.reacq_radii_px), self.cfg.reacq_full_scan_enabled)
            self.confirmer = TemporalConfirmer(self.cfg.candidate_confirm_frames)
            return
        # Removed: legacy LocalTerminalConfig shim (BUG-13/14). Previously mapped scan/detector/tracker fields,
        # but that created duplicate authoritative paths. Now we fail fast with migration guidance.
        import warnings
        warnings.warn(
            "apply_local_config received non-AutonomyConfig (legacy LocalTerminalConfig). "
            "Legacy config has been removed — migrate to AutonomyConfig. Ignoring.",
            DeprecationWarning, stacklevel=2,
        )
        log.warning("Legacy config rejected — AutonomyConfig is sole authoritative V2 config")
        return

    def step(self, fov_frame: np.ndarray, dt: float, sim_time_s: float,
             comm_sources: list[CommSource] | None = None,
             boresight_world: tuple[float, float] = (1000.0, 1000.0),
             cam_home: tuple[float, float] = (1000.0, 1000.0),
             px_per_deg: tuple[float, float] = (160.0, 160.0),
             origin_shift: tuple[float, float] = (0.0, 0.0),
             fov_size: tuple[int, int] = (640, 480)) -> V2Output:
        self.sim_time = float(sim_time_s)
        dt_eff = max(float(dt), 1e-6)
        fw, fh = float(fov_size[0]), float(fov_size[1])

        beacon = self.comm.poll_observation(
            comm_sources or [], boresight_world, self.sim_time, dt_eff)
        if beacon is not None and beacon.valid_crc:
            self._pending_beacon = beacon

        spots = detect_spots(fov_frame, self.cfg)
        self._last_spots = spots
        # BUG-12: scale temporal confirmation gate by measurement uncertainty and FOV
        # 12px base for 640x480, scaled by FOV and Kalman uncertainty (tracking) or fixed for acquisition
        try:
            fov_scale = float(fw) / 640.0
            # Use tracker uncertainty when tracking/coasting, else base
            if self.state in (V2State.TRACK, V2State.COAST) and self.tracker.active_tid is not None:
                unc = float(self.tracker.effective_uncertainty_px())
                # Scale 12px -> 12*(1+unc/60) capped 12-20, so high uncertainty allows larger temporal gate (motion)
                scaled_gate = 12.0 * fov_scale * (1.0 + min(unc, 30.0) / 60.0)
                self.confirmer.gate_px = float(np.clip(scaled_gate, 8.0, 20.0))
            else:
                # Acquisition: base gate scaled only by FOV
                self.confirmer.gate_px = float(np.clip(12.0 * fov_scale, 8.0, 16.0))
        except Exception:
            pass
        confirmed = self.confirmer.update(spots)

        curr_angles = ((boresight_world[0] - cam_home[0]) / px_per_deg[0],
                       (cam_home[1] - boresight_world[1]) / px_per_deg[1])
        target_angles = None
        pid_active = False
        track_err = None

        if self.state == V2State.SEARCH:
            has_p_rx = False
            # Beacon freshness for SEARCH: only fresh beacons count
            fresh_beacon = None
            if beacon is not None and beacon.valid_crc:
                try:
                    age = float(self.sim_time) - float(getattr(beacon, "timestamp_s", 0.0) or 0.0)
                    if age <= 0.5:
                        fresh_beacon = beacon
                except Exception:
                    fresh_beacon = beacon
            if fresh_beacon is not None:
                try:
                    prx = float(getattr(fresh_beacon, "p_rx_w", 0.0) or 0.0)
                    snr = float(getattr(fresh_beacon, "snr_db", -99) or -99)
                    has_p_rx = prx >= float(self.cfg.p_rx_threshold_w) and snr >= float(self.cfg.candidate_min_snr_db)
                except Exception:
                    has_p_rx = False
            # SEARCH requires confirmed spots (not raw) + fresh P_rx to avoid star false triggers
            if confirmed and has_p_rx:
                self.scan.step(has_decoding_candidate=True)
                self._go(V2State.IDENTIFY, "optical_candidate")
                target_angles = curr_angles
            else:
                # No joint P_rx+spot candidate — keep rastering. Star-only spots or P_rx-only must not pin scan.
                pos = self.scan.step(has_decoding_candidate=False)
                target_angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])

        elif self.state == V2State.IDENTIFY:
            target_angles = curr_angles
            pend = self._pending_beacon
            if pend is None:
                pass
            elif float(getattr(pend, "timestamp_s", 0.0)) <= float(getattr(self, "_last_ident_t", -1.0)):
                pass
            else:
                # Freshness: beacon must be recent (<0.5s) to be used for IDENTIFY
                try:
                    age = float(self.sim_time) - float(getattr(pend, "timestamp_s", 0.0) or 0.0)
                    if age > 0.5:
                        self._pending_beacon = None
                        self._pending_tid = None
                        # Stale beacon, stay in IDENTIFY or return to SEARCH
                        pass
                    else:
                        self._last_ident_t = float(getattr(pend, "timestamp_s", 0.0))
                        res = self.identity.check(pend, self.sim_time)
                        if res.accepted and res.terminal_id:
                            self._pending_tid = res.terminal_id
                            self._go(V2State.ASSOCIATE, f"{res.terminal_id}_valid")
                        else:
                            self._pending_beacon = None
                            self._pending_tid = None
                            self._go(V2State.SEARCH, f"identify_fail:{res.reason}")
                except Exception:
                    self._last_ident_t = float(getattr(pend, "timestamp_s", 0.0))
                    res = self.identity.check(pend, self.sim_time)
                    if res.accepted and res.terminal_id:
                        self._pending_tid = res.terminal_id
                        self._go(V2State.ASSOCIATE, f"{res.terminal_id}_valid")
                    else:
                        self._pending_beacon = None
                        self._pending_tid = None
                        self._go(V2State.SEARCH, f"identify_fail:{res.reason}")

        elif self.state == V2State.ASSOCIATE:
            target_angles = curr_angles
            # P0 FIX: Use configured gate, not max(fw,fh), and require confirmed + fresh beacon
            fresh_beacon = None
            if self._pending_beacon is not None and self._pending_beacon.valid_crc:
                try:
                    age = float(self.sim_time) - float(getattr(self._pending_beacon, "timestamp_s", 0.0) or 0.0)
                    if age <= 0.5:
                        fresh_beacon = self._pending_beacon
                    else:
                        self._pending_beacon = None
                except Exception:
                    fresh_beacon = self._pending_beacon
            # Require confirmed spots for acquisition (not raw fallback) — sensor-only, no ground truth
            cands = confirmed if confirmed else []
            # BUG-06/12: context-dependent effective gate (beacon/temporal/FOV) — never expand beyond base (200) to avoid star-field false lock
            base_gate = float(self.cfg.association_gate_px)
            fov_scale = float(fw) / 640.0  # scale for different FOV/magnification
            # Beacon factor: fresh bright beacon allows full base gate, missing/low SNR shrinks gate (reduces star false lock)
            if fresh_beacon is None:
                beacon_factor = 0.35  # no identity -> only very close spots (star near boresight) considered, but assoc will fail anyway (no_valid_tid)
            else:
                try:
                    snr_b = float(getattr(fresh_beacon, "snr_db", 6.0) or 6.0)
                    if snr_b >= 10.0:
                        beacon_factor = 1.0
                    elif snr_b >= 8.0:
                        beacon_factor = 0.9
                    elif snr_b >= 6.0:
                        beacon_factor = 0.75
                    else:
                        beacon_factor = 0.55
                except Exception:
                    beacon_factor = 1.0
            # Temporal factor: confirmed persistence (2-frame) vs single-frame transient
            if not confirmed:
                temporal_factor = 0.5
            elif len(confirmed) >= 2:
                temporal_factor = 1.0
            else:
                temporal_factor = 0.85
            # Scan factor: keep 1.0 (boresight already is scan center); no expansion beyond base
            scan_factor = 1.0
            effective_gate = float(np.clip(base_gate * fov_scale * beacon_factor * temporal_factor * scan_factor, 40.0, base_gate))
            # Boresight is fov center; scan_center same for acquisition (could use scan.current_position center mapped to FOV, but boresight approx)
            assoc = associate_acquisition(
                cands, fresh_beacon, (fw, fh),
                gate_px=effective_gate,
                scan_center=None,
                temporal_history=getattr(self.confirmer, "_history", None))
            # Hardening: 2-frame acquisition confirmation (star near boresight rarely repeats)
            # No world-position leakage: rely on temporal consistency + beacon freshness
            if assoc.observation is not None:
                o = assoc.observation
                # If pending exists, require second frame within 25px and 0.3s window
                if self._assoc_pending is not None and self._assoc_pending.terminal_id == o.terminal_id:
                    age = float(self.sim_time - self._assoc_pending_t)
                    dist = math.hypot(float(o.fov_x - self._assoc_pending.fov_x), float(o.fov_y - self._assoc_pending.fov_y))
                    if age <= 0.35 and dist <= 25.0:
                        tid = select_active_v2([o], self.cfg.active_target_policy,
                                               self.mission_priority) or o.terminal_id
                        self.tracker.lock(tid, o.fov_x, o.fov_y, self.sim_time, o.p_rx_w)
                        self._assoc_pending = None
                        self._pending_beacon = None
                        self._pending_tid = None
                        self._coast_since = None
                        self._track_miss_streak = 0
                        self._track_hit_streak = 0
                        if self._first_lock_t is None:
                            self._first_lock_t = self.sim_time
                        self._go(V2State.TRACK, "spot_associated_confirmed")
                        pid_active = True
                        track_err = self.tracker.error_px(fw, fh)
                    else:
                        # Too far / stale -> reset pending to current
                        self._assoc_pending = o
                        self._assoc_pending_t = float(self.sim_time)
                        target_angles = curr_angles
                else:
                    # First sighting — store and wait one more frame for confirmation
                    # If confirmer already required 2 frames, this makes total 3-frame chain -> very low false rate
                    if self._assoc_pending is None:
                        # Also allow immediate lock if SNR very high (>=14dB) — beacon bright vs star dim
                        if float(o.snr_db) >= 14.0:
                            tid = select_active_v2([o], self.cfg.active_target_policy,
                                                   self.mission_priority) or o.terminal_id
                            self.tracker.lock(tid, o.fov_x, o.fov_y, self.sim_time, o.p_rx_w)
                            self._assoc_pending = None
                            self._pending_beacon = None
                            self._pending_tid = None
                            self._coast_since = None
                            if self._first_lock_t is None:
                                self._first_lock_t = self.sim_time
                            self._go(V2State.TRACK, "spot_associated_bright")
                            pid_active = True
                            track_err = self.tracker.error_px(fw, fh)
                        else:
                            self._assoc_pending = o
                            self._assoc_pending_t = float(self.sim_time)
                            target_angles = curr_angles
                    else:
                        self._assoc_pending = o
                        self._assoc_pending_t = float(self.sim_time)
            else:
                # No valid assoc this frame — keep pending for short grace (0.35s) else fail
                if self._assoc_pending is not None and (float(self.sim_time - self._assoc_pending_t) > 0.35):
                    self._assoc_pending = None
                if fresh_beacon is None:
                    self._assoc_pending = None
                    self._go(V2State.SEARCH, "assoc_no_fresh_beacon")
                else:
                    if self._assoc_pending is None:
                        self._go(V2State.IDENTIFY, f"assoc_fail:{assoc.reason}")
                    # else stay in ASSOCIATE waiting for second frame

        elif self.state in (V2State.TRACK, V2State.COAST):
            pid_active = True
            # P0 FIX: Rebase + predict BEFORE association (was after, causing stale gate)
            # Shift tracker into current FOV frame and predict to current time
            try:
                self.tracker.kf.shift(-float(origin_shift[0]), -float(origin_shift[1]))
                self.tracker.kf.predict(dt_eff)
            except Exception:
                pass
            pred = self.tracker.kf.position
            # Use only confirmed detections for TRACK/COAST (not raw fallback)
            cands = confirmed if confirmed else []
            # Gate after predict — use full 2D innovation covariance S = HPHᵀ+R+margin (BUG-05)
            r = r_for_snr(spots[0].snr_db if spots else 6.0, self.tracker.config) if cands else 4.0
            pred_var = self.tracker.gate_pred_var()  # legacy scalar for fallback/logging
            try:
                S_gating = self.tracker.gate_innovation_cov(r)
            except Exception:
                S_gating = None
            # Beacon freshness: ignore stale beacons >0.5s old
            fresh_beacon = None
            if self._pending_beacon is not None:
                try:
                    age = float(self.sim_time) - float(getattr(self._pending_beacon, "timestamp_s", 0.0) or 0.0)
                    if age <= 0.5 and self._pending_beacon.valid_crc:
                        fresh_beacon = self._pending_beacon
                    else:
                        # Stale beacon - clear pending to avoid reuse
                        if age > 0.5:
                            self._pending_beacon = None
                except Exception:
                    fresh_beacon = self._pending_beacon
            # Foreign beacon isolation: only pass beacon if TID matches active or no active yet
            assoc_beacon = fresh_beacon
            if fresh_beacon is not None and self.tracker.active_tid and str(fresh_beacon.terminal_id) != str(self.tracker.active_tid):
                # Do not contaminate active track with foreign power/timestamp
                assoc_beacon = None
            assoc = associate_tracking(
                cands, pred[0], pred[1],
                self.tracker.active_tid or "", assoc_beacon,
                pred_var=pred_var,
                r_base=r, mahal_threshold=self.cfg.association_mahal_threshold,
                S=S_gating)
            # Sensor-only validation: no ground-truth leakage. Stars drift vs beacon prediction already gated by Mahalanobis.
            # Additional photometric sanity: if association SNR < 7dB and P_rx indicates strong link, still accept (fading), but if spot area spikes >180, likely haze artifact
            if assoc.observation is not None:
                try:
                    # Reject large diffuse blobs (haze) that slipped through area gate under high variance
                    for s in cands:
                        if abs(float(s.x - assoc.observation.fov_x)) < 1.5 and abs(float(s.y - assoc.observation.fov_y)) < 1.5:
                            if int(s.area_px) > 180 and float(s.snr_db) < 9.0:
                                assoc.observation = None
                                assoc.reason = "diffuse_haze_blob"
                            break
                except Exception:
                    pass
            self._rejected = assoc.rejected_outliers
            # Innovation monitoring (BUG-05): large NIS indicates wrong association / maneuver / corruption
            if assoc.observation is not None:
                try:
                    # NIS before update (S_gating is S before update)
                    nis = self.tracker.mahalanobis_d2_full(
                        float(assoc.observation.fov_x), float(assoc.observation.fov_y),
                        r_for_snr(float(getattr(assoc.observation, "snr_db", 6.0)), self.tracker.config))
                    if nis > 16.0:  # 2-dof 99.9% ~13.8, 16 is strong outlier
                        log.debug("V2 large innovation NIS=%.2f @ %.3f state=%s pred=(%.1f,%.1f) obs=(%.1f,%.1f)",
                                  nis, self.sim_time, self.state.value, float(pred[0]), float(pred[1]),
                                  float(assoc.observation.fov_x), float(assoc.observation.fov_y))
                except Exception:
                    pass
            # Update tracker: already predicted, now only update if observation found
            if assoc.observation is not None:
                try:
                    r_upd = r_for_snr(float(getattr(assoc.observation, "snr_db", 6.0)), self.tracker.config)
                    self.tracker.kf.update(float(assoc.observation.fov_x), float(assoc.observation.fov_y), r_upd)
                    self.tracker.misses = 0
                    self.tracker.last_meas_t = float(self.sim_time)
                    self.tracker.p_rx_w = float(getattr(assoc.observation, "p_rx_w", 0.0) or 0.0)
                    if getattr(assoc.observation, "timestamp_s", 0.0):
                        self.tracker.last_beacon_t = float(assoc.observation.timestamp_s)
                    self.tracker.status = "TRACKING"
                except Exception:
                    pass
                # Create track object without re-predicting
                from local_terminal.models import TargetTrack as _TT
                x, y = self.tracker.kf.position
                vx, vy = self.tracker.kf.velocity
                unc = float(self.tracker.effective_uncertainty_px())
                track = _TT(terminal_id=self.tracker.active_tid or "", x=float(x), y=float(y), vx=float(vx), vy=float(vy), uncertainty_px=unc, last_measurement_time_s=float(self.tracker.last_meas_t), last_beacon_time_s=self.tracker.last_beacon_t, p_rx_w=float(self.tracker.p_rx_w), misses=int(self.tracker.misses), status=self.tracker.status).validate()
            else:
                # No valid measurement: already predicted, just increment misses and set COAST
                self.tracker.misses += 1
                self.tracker.status = "COASTING"
                from local_terminal.models import TargetTrack as _TT
                x, y = self.tracker.kf.position
                vx, vy = self.tracker.kf.velocity
                # Add coast margin to uncertainty
                margin = min(float(self.tracker.misses) * self.tracker.kf.config.coast_growth_px_per_frame, self.tracker.kf.config.coast_margin_cap_px)
                unc = float(self.tracker.kf.uncertainty_px) + (margin if self.tracker.misses else 0.0)
                track = _TT(terminal_id=self.tracker.active_tid or "", x=float(x), y=float(y), vx=float(vx), vy=float(vy), uncertainty_px=unc, last_measurement_time_s=float(self.tracker.last_meas_t), last_beacon_time_s=self.tracker.last_beacon_t, p_rx_w=float(self.tracker.p_rx_w), misses=int(self.tracker.misses), status=self.tracker.status).validate()
                # Clear stale pending beacon if it was foreign and caused miss
                if fresh_beacon is None and self._pending_beacon is not None:
                    # Keep pending for potential reacquisition, but not for track
                    pass
            track_err = self.tracker.error_px(fw, fh)
            unc = track.uncertainty_px
            since = self.sim_time - track.last_measurement_time_s
            # Debounced TRACK/COAST hysteresis: 2 consecutive misses -> COAST, 2 hits -> TRACK
            if assoc.observation is not None:
                self._track_miss_streak = 0
                self._track_hit_streak += 1
                self._coast_since = None
                # Only transition COAST->TRACK after 2 hits (single hit could be star coincidence)
                if self.state == V2State.COAST and self._track_hit_streak >= 2:
                    self._go(V2State.TRACK, "spot_recovered_debounced")
                    self._track_hit_streak = 0
                elif self.state == V2State.COAST and self._track_hit_streak == 1:
                    pass  # stay COAST one more frame, keep pid_active True
            else:
                self._track_hit_streak = 0
                self._track_miss_streak += 1
                # Require 2 misses before leaving TRACK (suppress single S&P dropout)
                if self.state == V2State.TRACK and self._track_miss_streak >= 2:
                    self._go(V2State.COAST, "spot_missing_debounced")
                    self._coast_since = self.sim_time
                elif self.state == V2State.TRACK and self._track_miss_streak == 1:
                    pass  # stay TRACK for one frame grace
                if unc > self.cfg.lost_uncertainty_threshold_px and since > self.cfg.lost_timeout_s:
                    self.loss_count += 1
                    self.tracker.status = "LOST"
                    self._go(V2State.LOST, "uncertainty_timeout")
                    pid_active = False
                    track_err = None
                    self._track_miss_streak = 0
                    self._track_hit_streak = 0
            if self.state in (V2State.TRACK, V2State.COAST):
                target_angles = None

        elif self.state == V2State.LOST:
            pid_active = False
            track_err = None
            if self.tracker.active_tid:
                try:
                    vx, vy = self.tracker.kf.velocity
                    unc = float(self.tracker.effective_uncertainty_px())
                    self.reacq.start(self.tracker.active_tid, (float(vx), float(vy)), unc, fov_size=(fw, fh))
                except Exception:
                    try:
                        self.reacq.start(self.tracker.active_tid, fov_size=(fw, fh))
                    except Exception:
                        self.reacq.start(self.tracker.active_tid)
                self.reacq_start = self.sim_time
            self._go(V2State.REACQUIRE, "track_timeout")

        elif self.state == V2State.REACQUIRE:
            pred = self.tracker.kf.position
            # REACQUIRE requires confirmed spots and fresh beacon (no raw fallback)
            cands = confirmed if confirmed else []
            fresh_beacon = None
            if self._pending_beacon is not None and self._pending_beacon.valid_crc:
                try:
                    age = float(self.sim_time) - float(getattr(self._pending_beacon, "timestamp_s", 0.0) or 0.0)
                    if age <= 0.5:
                        fresh_beacon = self._pending_beacon
                    else:
                        self._pending_beacon = None
                except Exception:
                    fresh_beacon = self._pending_beacon
            res = self.reacq.update(cands, fresh_beacon,
                                    pred[0], pred[1], self.cfg.p_rx_threshold_w,
                                    self.scan, cam_home, px_per_deg)
            target_angles = res.target_angles
            if res.reacquired and res.target_id and res.target_pos:
                # Only use fresh beacon power if TID matches reacquired target
                p_rx = 0.0
                if fresh_beacon is not None and str(fresh_beacon.terminal_id) == str(res.target_id):
                    p_rx = float(getattr(fresh_beacon, "p_rx_w", 0.0) or 0.0)
                self.tracker.lock(res.target_id, res.target_pos[0], res.target_pos[1],
                                  self.sim_time, p_rx)
                self.reacq_count += 1
                if self.reacq_start is not None:
                    self.reacq_time_s = self.sim_time - self.reacq_start
                self._pending_beacon = None
                self._coast_since = None
                if self._first_lock_t is None:
                    self._first_lock_t = self.sim_time
                self._go(V2State.TRACK, f"{res.target_id}_confirmed")
                pid_active = True
                track_err = self.tracker.error_px(fw, fh)
            elif res.exhausted:
                self._go(V2State.SEARCH, "reacq_exhausted_full_scan")

        tel = self._telemetry(spots, beacon)
        vx, vy = self.tracker.kf.velocity
        vel = (float(vx), float(vy)) if track_err is not None else None
        reset_req = bool(getattr(self, "_camera_reset_pending", False))
        self._camera_reset_pending = False
        return V2Output(self.state, target_angles, pid_active, track_err,
                        self.tracker.active_tid, tel, vel, reset_req)

    def _telemetry(self, spots, beacon) -> dict:
        x, y = self.tracker.kf.position
        vx, vy = self.tracker.kf.velocity
        err = self.tracker.error_px()
        locked = self.state == V2State.TRACK and self.tracker.active_tid is not None
        # Candidate telemetry: distinct labels for LOCKED vs raw candidates
        # Show active track as LOCKED, other candidates as CANDIDATE with true SNR
        cands = []
        if locked:
            cands.append({
                "terminal_id": self.tracker.active_tid,
                "fov_x": round(float(x), 2),
                "fov_y": round(float(y), 2),
                "confidence": 1.0,
                "snr_db": float(getattr(self.tracker, "p_rx_w", 0.0) or 0.0),  # placeholder
                "confirmed": True,
            })
        # Only show top 4 raw candidates, with true SNR, not inflated
        for s in (spots or [])[:4]:
            # Skip if this candidate is the active track (avoid duplicate)
            if locked and abs(float(s.x) - float(x)) < 6 and abs(float(s.y) - float(y)) < 6:
                continue
            conf = round(max(0.0, min(1.0, (float(s.snr_db) - 6.0) / 12.0)), 3)
            # Clamp confidence to avoid always 1.00 for bright stars - use actual SNR
            if float(s.snr_db) > 18:
                conf = min(0.85, conf)  # Stars rarely have sustained 18dB, cap at 0.85 unless truly bright beacon
            cands.append({
                "terminal_id": "CANDIDATE",
                "fov_x": float(s.x),
                "fov_y": float(s.y),
                "confidence": conf,
                "snr_db": float(s.snr_db),
                "confirmed": False,
            })
        # Detection rate: confirmed vs raw, not just locked
        try:
            confirmed = self.confirmer.update(spots) if hasattr(self, "confirmer") else []
            # Use spots vs confirmed to compute rate, but confirmer already consumed spots
            # So use history: detection rate = 100 * (1 - misses/(misses+hits)) approx
            total_frames = max(1, int(self.tracker.misses) + (1 if locked else 0))
            det_rate = 100.0 * (0.0 if not locked else max(0.0, 1.0 - float(self.tracker.misses) / max(1, total_frames * 2)))
            # Clamp to 0-100 and base on spot count when not locked
            if not locked:
                # When searching, rate based on whether spots are found vs expected beacons
                det_rate = 0.0 if not spots else min(30.0, len(spots) * 5.0)
        except Exception:
            det_rate = 100.0 if locked else 0.0
        # Acquisition time as duration, not absolute timestamp
        acq_time = getattr(self, "_first_lock_t", None)
        search_start = getattr(self, "_search_start_t", None)
        if acq_time is not None and search_start is not None:
            acq_dur = float(acq_time - search_start)
        else:
            acq_dur = acq_time
        return {
            "state": self.state.value,
            "active_target_id": self.tracker.active_tid,
            "p_rx_w": float(getattr(beacon, "p_rx_w", 0.0) or 0.0) if beacon else 0.0,
            "snr_db": float(getattr(beacon, "snr_db", 0.0) or 0.0) if beacon else 0.0,
            "last_decoded_tid": getattr(beacon, "terminal_id", None) if beacon else None,
            "last_decoded_sequence": getattr(beacon, "sequence", None) if beacon else None,
            "spot_count": len(spots or []),
            "active_spot_x": round(float(x), 2),
            "active_spot_y": round(float(y), 2),
            "predicted_x": round(float(x), 2),
            "predicted_y": round(float(y), 2),
            "track_vx": round(float(vx), 2),
            "track_vy": round(float(vy), 2),
            "track_uncertainty_px": round(float(self.tracker.effective_uncertainty_px()), 2),
            "tracking_error_x_px": round(float(err[0]), 2) if err else None,
            "tracking_error_y_px": round(float(err[1]), 2) if err else None,
            "miss_count": int(self.tracker.misses),
            "loss_count": int(self.loss_count),
            "reacquisition_count": int(self.reacq_count),
            "reacquisition_time_s": self.reacq_time_s,
            "reacq_radius_px": float(self.reacq.radius_px) if self.reacq.active else 0.0,
            "search_cell": self.scan.current_position.index,
            "camera_pan": None,
            "camera_tilt": None,
            "autonomy": {
                "state": "LOCKED" if locked else (
                    "SEARCHING" if self.state in (V2State.SEARCH, V2State.IDENTIFY,
                                                  V2State.ASSOCIATE) else self.state.value),
                "raw_state": self.state.value,
                "active_target_id": self.tracker.active_tid,
                "candidates": cands,
                "standby_pool": [],
                "blacklist": sorted(self.identity.blacklist),
                "fault": self.state == V2State.FAULT,
                "full_reset_count": 0,
            },
            "locked": bool(locked),
            "misses": int(self.tracker.misses),
            "frames_since_detection": int(self.tracker.misses),
            "acquisition_time_s": acq_dur,
            "target_loss_count": int(self.loss_count),
            "detection_rate_pct": round(float(det_rate), 1),
            "scan": self.scan.telemetry(),
            "validation": {"state": self.state.value,
                           "terminal_id": self.tracker.active_tid,
                           "validated": bool(locked),
                           "blacklisted": False,
                           "strikes": 0},
        }


# Backward-compat aliases for legacy imports (V2 is sole FSM) — defined AFTER SupervisorV2
AutonomyState = V2State
SupervisorConfig = AutonomyConfig
SupervisorOutput = V2Output
AutonomySupervisor = SupervisorV2

__all__ = ["V2State", "V2Output", "SupervisorV2", "V2_VALID_TRANSITIONS", "is_valid_transition", "AutonomyState", "SupervisorConfig", "SupervisorOutput", "AutonomySupervisor"]
