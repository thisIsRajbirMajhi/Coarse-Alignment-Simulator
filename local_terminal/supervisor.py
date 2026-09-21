# local_terminal/supervisor.py - V2 compact FSM (Plan V2 §5, §18).
# States: SEARCH IDENTIFY ASSOCIATE TRACK COAST LOST REACQUIRE FAULT.

from __future__ import annotations

import enum
import logging
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
        self._full_resets: int = 0
        self._camera_reset_pending: bool = False

    def _go(self, nxt: V2State, reason: str) -> None:
        if nxt is not self.state:
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
            if beacon is not None:
                try:
                    prx = float(getattr(beacon, "p_rx_w", 0.0) or 0.0)
                    snr = float(getattr(beacon, "snr_db", -99) or -99)
                    has_p_rx = prx >= float(self.cfg.p_rx_threshold_w) and snr >= float(self.cfg.candidate_min_snr_db)
                except Exception:
                    has_p_rx = False
            if spots and has_p_rx:
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
            assoc = associate_acquisition(
                confirmed or spots, self._pending_beacon, (fw, fh),
                gate_px=max(fw, fh))
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
                self._go(V2State.IDENTIFY, f"assoc_fail:{assoc.reason}")

        elif self.state in (V2State.TRACK, V2State.COAST):
            pid_active = True
            pred = self.tracker.kf.position
            r = r_for_snr(spots[0].snr_db if spots else 6.0, self.tracker.config)
            assoc = associate_tracking(
                confirmed or spots, pred[0], pred[1],
                self.tracker.active_tid or "", self._pending_beacon,
                pred_var=self.tracker.gate_pred_var(),
                r_base=r, mahal_threshold=self.cfg.association_mahal_threshold)
            self._rejected = assoc.rejected_outliers
            track = self.tracker.step(assoc.observation, dt_eff, self.sim_time, origin_shift)
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
            res = self.reacq.update(confirmed or spots, self._pending_beacon,
                                    pred[0], pred[1], self.cfg.p_rx_threshold_w,
                                    self.scan, cam_home, px_per_deg)
            target_angles = res.target_angles
            if res.reacquired and res.target_id and res.target_pos:
                self.tracker.lock(res.target_id, res.target_pos[0], res.target_pos[1],
                                  self.sim_time,
                                  float(getattr(self._pending_beacon, "p_rx_w", 0.0) or 0.0))
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
        cands = []
        if locked:
            cands.append({
                "terminal_id": self.tracker.active_tid,
                "fov_x": round(float(x), 2),
                "fov_y": round(float(y), 2),
                "confidence": 1.0,
                "confirmed": True,
            })
        for s in (spots or [])[:8]:
            cands.append({
                "terminal_id": self.tracker.active_tid if locked else "CANDIDATE",
                "fov_x": float(s.x),
                "fov_y": float(s.y),
                "confidence": round(max(0.0, min(1.0, (float(s.snr_db) - 6.0) / 12.0)), 3),
                "confirmed": bool(locked),
            })
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
            "acquisition_time_s": getattr(self, "_first_lock_t", None),
            "target_loss_count": int(self.loss_count),
            "detection_rate_pct": 100.0 if locked else 0.0,
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
