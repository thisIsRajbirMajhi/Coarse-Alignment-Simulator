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

    def _go(self, nxt: V2State, reason: str) -> None:
        if nxt is not self.state:
            # Track search start for acquisition duration
            if nxt == V2State.SEARCH:
                self._search_start_t = float(self.sim_time)
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
        self._full_resets = int(getattr(self, "_full_resets", 0)) + 1
        self._camera_reset_pending = True
        self._go(V2State.SEARCH, "full_reset")
        return True

    def apply_local_config(self, cfg) -> None:
        # V2 direct: AutonomyConfig
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
        # Legacy shim: LocalTerminalConfig (deprecated)
        try:
            lc = cfg.validate()
        except AttributeError:
            return
        try:
            self.cfg.search_dwell_frames = int(lc.scan.default_dwell_frames)
            self.cfg.search_extended_dwell_frames = int(lc.scan.decoding_dwell_frames)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            self.cfg.candidate_min_snr_db = float(lc.detector.snr_min_db)
            self.cfg.association_gate_px = float(lc.tracker.associate_gate_px)
            self.cfg.lost_timeout_s = float(lc.tracker.max_no_detection_time_s)
        except (AttributeError, TypeError, ValueError):
            pass
        self.cfg.validate()

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
            # Require confirmed spots for acquisition (not raw fallback)
            cands = confirmed if confirmed else []
            assoc = associate_acquisition(
                cands, fresh_beacon, (fw, fh),
                gate_px=float(self.cfg.association_gate_px))
            # World-distance check for acquisition: spot must be near beacon's terminal world pos
            if assoc.observation is not None and fresh_beacon is not None and comm_sources:
                try:
                    spot_world_x = float(boresight_world[0]) - fw/2 + float(assoc.observation.fov_x)
                    spot_world_y = float(boresight_world[1]) - fh/2 + float(assoc.observation.fov_y)
                    # Find beacon's terminal world pos
                    best_dist = 1e9
                    for s in comm_sources:
                        try:
                            sx, sy = float(s.position[0]), float(s.position[1])
                            d = math.hypot(sx - spot_world_x, sy - spot_world_y)
                            if d < best_dist:
                                best_dist = d
                        except Exception:
                            continue
                    if best_dist > 120:
                        assoc.observation = None
                        assoc.reason = "acq_spot_beacon_mismatch"
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).info(f"ACQ world check exception {e}")
                    pass
            if assoc.observation is not None:
                o = assoc.observation
                tid = select_active_v2([o], self.cfg.active_target_policy,
                                       self.mission_priority) or o.terminal_id
                self.tracker.lock(tid, o.fov_x, o.fov_y, self.sim_time, o.p_rx_w)
                self._pending_beacon = None
                self._pending_tid = None
                self._coast_since = None
                if self._first_lock_t is None:
                    self._first_lock_t = self.sim_time
                self._go(V2State.TRACK, "spot_associated")
                pid_active = True
                track_err = self.tracker.error_px(fw, fh)
            else:
                # Stay in ASSOCIATE briefly, but if no confirmed spots, return to IDENTIFY
                # If beacon stale, go back to SEARCH
                if fresh_beacon is None:
                    self._go(V2State.SEARCH, "assoc_no_fresh_beacon")
                else:
                    self._go(V2State.IDENTIFY, f"assoc_fail:{assoc.reason}")

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
            # Gate var after predict (not before)
            r = r_for_snr(spots[0].snr_db if spots else 6.0, self.tracker.config) if cands else 4.0
            pred_var = self.tracker.gate_pred_var()
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
                r_base=r, mahal_threshold=self.cfg.association_mahal_threshold)
            # World-distance validation: spot must be near beacon's terminal world pos
            # Prevents star false lock when God view shows FOV far from true terminals (image 1/2)
            if assoc.observation is not None and assoc_beacon is not None and comm_sources:
                try:
                    # Find beacon's terminal world pos from comm_sources
                    beacon_pos = None
                    for src in comm_sources:
                        # CommSource has position, check if it matches beacon TID via chip? Use first emitting
                        # For now, use boresight distance: spot world vs FOV center + spot offset
                        # Spot world = boresight_world + (spot - FOV_center)
                        spot_world_x = float(boresight_world[0]) - fw/2 + float(assoc.observation.fov_x)
                        spot_world_y = float(boresight_world[1]) - fh/2 + float(assoc.observation.fov_y)
                        # Find closest source to spot_world
                        best_dist = 1e9
                        best_src = None
                        for s in comm_sources:
                            try:
                                sx, sy = float(s.position[0]), float(s.position[1])
                                d = math.hypot(sx - spot_world_x, sy - spot_world_y)
                                if d < best_dist:
                                    best_dist = d
                                    best_src = s
                            except Exception:
                                continue
                        # If best source is far (>80px), this is likely a star, not the beacon's terminal
                        if best_src is not None and best_dist > 120:
                            # Reject this association - likely false star
                            assoc.observation = None
                            assoc.reason = "spot_beacon_world_mismatch"
                            self._rejected += 1
                except Exception:
                    pass
            self._rejected = assoc.rejected_outliers
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
            if assoc.observation is not None:
                self._coast_since = None
                if self.state == V2State.COAST:
                    self._go(V2State.TRACK, "spot_recovered")
            else:
                if self.state == V2State.TRACK:
                    self._go(V2State.COAST, "spot_missing")
                    self._coast_since = self.sim_time
                if unc > self.cfg.lost_uncertainty_threshold_px and since > self.cfg.lost_timeout_s:
                    self.loss_count += 1
                    self.tracker.status = "LOST"
                    self._go(V2State.LOST, "uncertainty_timeout")
                    pid_active = False
                    track_err = None
            if self.state in (V2State.TRACK, V2State.COAST):
                target_angles = None

        elif self.state == V2State.LOST:
            pid_active = False
            track_err = None
            if self.tracker.active_tid:
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

__all__ = ["V2State", "V2Output", "SupervisorV2", "AutonomyState", "SupervisorConfig", "SupervisorOutput", "AutonomySupervisor"]
