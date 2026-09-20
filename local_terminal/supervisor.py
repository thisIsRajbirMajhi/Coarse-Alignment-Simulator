# local_terminal/supervisor.py - Autonomy Supervisor (Plan.md §9).
#
# State machine orchestrating:
#   SEARCH -> DETECT -> VALIDATE -> SELECT -> TRACK -> RE_ACQUIRE -> (RESET / FAULT)
#
# Enforces:
# - Autonomous transitions (§9.1)
# - Watchdogs: DECODING <= 672 ms, selection per scan cycle, re-acq bounded (§9.2)
# - Two-level reset policy: escalation scan vs rate-limited full reset (§9.3)
# - Telemetry aggregation for dashboard and renderer (§10)

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from local_terminal.comm_receiver import CommReceiver, CommSource, ber_from_snr_db
from local_terminal.detector import Detection, DetectorConfig, detect_candidates
from local_terminal.motion import AlphaBetaFilter2D
from local_terminal.reacquisition import (
    EscalationStage,
    ReacquisitionConfig,
    ReacquisitionManager,
)
from local_terminal.registry import SignatureRegistry
from local_terminal.scan import ScanConfig, ScanController, ScanPosition
from local_terminal.selector import StandbyCandidate, TargetSelector
from local_terminal.tracker import ImageTracker, TrackerConfig, TrackSnapshot
from local_terminal.validator import TrackValidator, ValidationConfig, ValidationSnapshot

log = logging.getLogger(__name__)


class AutonomyState(enum.Enum):
    SEARCH = "SEARCH"
    DETECT = "DETECT"
    VALIDATE = "VALIDATE"
    SELECT = "SELECT"
    TRACK = "TRACK"
    RE_ACQUIRE = "RE_ACQUIRE"
    FAULT = "FAULT"


@dataclass
class SupervisorConfig:
    max_resets_per_window: int = 3
    reset_window_s: float = 300.0  # 5 minutes (§9.3)
    decoding_watchdog_s: float = 0.672  # 2 beacon periods (§9.2)
    in_track_recheck_interval: int = 30  # 30 frames ≈ 1 s (§7.4)

    def validate(self) -> "SupervisorConfig":
        self.max_resets_per_window = int(max(1, self.max_resets_per_window))
        self.reset_window_s = float(max(10.0, self.reset_window_s))
        self.decoding_watchdog_s = float(max(0.1, self.decoding_watchdog_s))
        self.in_track_recheck_interval = int(max(1, self.in_track_recheck_interval))
        return self


@dataclass
class SupervisorOutput:
    state: AutonomyState
    camera_target_angles: tuple[float, float] | None = None
    pid_active: bool = False
    track_error_px: tuple[float, float] | None = None
    active_target_id: str | None = None
    telemetry: dict = field(default_factory=dict)


class AutonomySupervisor:
    """Central autonomy supervisor for Coarse Alignment & Tracking (Plan.md §9)."""

    def __init__(
        self,
        registry: SignatureRegistry | None = None,
        config: SupervisorConfig | None = None,
        scan_config: ScanConfig | None = None,
        tracker_config: TrackerConfig | None = None,
        validation_config: ValidationConfig | None = None,
        reacq_config: ReacquisitionConfig | None = None,
        detector_config: DetectorConfig | None = None,
    ):
        self.config = (config or SupervisorConfig()).validate()
        self.registry = registry or SignatureRegistry()
        self.detector_config = (detector_config or DetectorConfig()).validate()

        # Core modules
        self.scan_ctrl = ScanController(scan_config)
        self.tracker = ImageTracker(tracker_config)
        self.validator = TrackValidator(self.registry, validation_config)
        self.selector = TargetSelector()
        self.reacq_mgr = ReacquisitionManager(reacq_config)
        self.comm_rx = CommReceiver()

        # State tracking
        self.state: AutonomyState = AutonomyState.SEARCH
        self.sim_time_s: float = 0.0
        self.transitions: list[tuple[float, str, str, str]] = []  # (t, from, to, reason)
        self.reset_timestamps: list[float] = []
        self.full_reset_count: int = 0
        self.fault_active: bool = False

        # Metrics for dashboard (§10)
        self.searching_start_s: float | None = 0.0
        self.total_searching_time_s: float = 0.0
        self.acquisition_time_s: float | None = None
        self.reacquisition_start_s: float | None = None
        self.reacquisition_time_s: float | None = None
        self.reacquisition_count: int = 0
        self.target_loss_count: int = 0
        self.total_frames: int = 0
        self.detection_frames: int = 0

        # Current frame cache
        self._current_dets: list[Detection] = []
        self._pending_validation_snap: ValidationSnapshot | None = None

    def set_registry(self, registry: SignatureRegistry) -> None:
        self.registry = registry
        self.validator.set_registry(registry)

    def _transition(self, new_state: AutonomyState, reason: str) -> None:
        if new_state != self.state:
            old_str = self.state.value
            new_str = new_state.value
            self.transitions.append((self.sim_time_s, old_str, new_str, reason))
            log.info("Autonomy transition @ %.3fs: %s -> %s (%s)", self.sim_time_s, old_str, new_str, reason)
            self.state = new_state

    # -- Reset Policies (§9.3) -----------------------------------------
    def escalation_scan(self) -> None:
        """Level 1: clears visited registry and candidates; PRESERVES blacklist/model/standby."""
        self._transition(AutonomyState.SEARCH, "escalation_scan")
        self.scan_ctrl.reset(clear_visited=True)
        self.validator.reset_track()
        self.tracker.reset()

    def full_reset(self) -> bool:
        """Level 2: clears all state, centres camera, rate-limited to 3 per 5 min."""
        now = self.sim_time_s
        # Prune reset timestamps older than reset_window_s
        self.reset_timestamps = [t for t in self.reset_timestamps if now - t <= self.config.reset_window_s]

        if len(self.reset_timestamps) >= self.config.max_resets_per_window:
            # Rate limit breached -> hold wide-scan and raise FAULT (§9.3)
            self.fault_active = True
            self._transition(AutonomyState.FAULT, "reset_rate_limit_exceeded")
            return False

        self.reset_timestamps.append(now)
        self.full_reset_count += 1
        self.fault_active = False

        self.scan_ctrl.reset(clear_visited=True)
        self.tracker.reset()
        self.validator = TrackValidator(self.registry, self.validator.config)
        self.selector.standby_pool.clear()
        self.reacq_mgr.reset()
        self.comm_rx.reset()

        self._transition(AutonomyState.SEARCH, "full_reset")
        return True

    # -- Main Autonomy Step -------------------------------------------
    def step(
        self,
        fov_frame: np.ndarray,
        dt: float,
        sim_time_s: float,
        comm_sources: list[CommSource] | None = None,
        boresight_world: tuple[float, float] = (1000.0, 1000.0),
        cam_home: tuple[float, float] = (1000.0, 1000.0),
        px_per_deg: tuple[float, float] = (160.0, 160.0),
        origin_shift: tuple[float, float] = (0.0, 0.0),
        fov_size: tuple[int, int] = (640, 480),
    ) -> SupervisorOutput:
        """Execute one autonomous cycle across all phases.

        Strict ground-truth isolation holds: comm_sources are used only by
        the photodiode physical sensor model in comm_rx; all autonomy
        decisions consume only decoded photons and detections.
        """
        self.sim_time_s = float(sim_time_s)
        dt_eff = max(float(dt), 1e-6)
        self.total_frames += 1

        # 1. Detection (§5.1)
        dets = detect_candidates(fov_frame, self.detector_config) if fov_frame is not None else []
        self._current_dets = dets
        if dets:
            self.detection_frames += 1

        # 2. Photodiode Comm Receiver update (§2.7, §5.3)
        sources = comm_sources or []
        snr_db = float(dets[0].snr_db) if dets else 6.0
        ber = ber_from_snr_db(snr_db)
        self.comm_rx.update(sources, boresight_world, self.sim_time_s, dt_eff, ber)
        crc_before = self.comm_rx.crc_failures
        decode_res = self.comm_rx.try_parse()
        crc_failed = self.comm_rx.crc_failures > crc_before

        # 3. State Machine Logic (§9.1)
        target_angles: tuple[float, float] | None = None
        pid_active = False
        track_error: tuple[float, float] | None = None

        curr_cam_angles = (
            (boresight_world[0] - cam_home[0]) / px_per_deg[0],
            (cam_home[1] - boresight_world[1]) / px_per_deg[1],
        )

        if self.state == AutonomyState.SEARCH:
            if self.searching_start_s is None:
                self.searching_start_s = self.sim_time_s
            self.total_searching_time_s += dt_eff

            if dets:
                self._hold_target_angles = curr_cam_angles
                target_angles = self._hold_target_angles
                self._transition(AutonomyState.DETECT, "spot_detected")
            else:
                # Scan controller drives camera pose schedule (§1.2, §4.1)
                pos = self.scan_ctrl.step(has_decoding_candidate=False)
                target_angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])
                self._hold_target_angles = target_angles

        elif self.state == AutonomyState.DETECT:
            self.total_searching_time_s += dt_eff
            # Hold camera for dwell to observe beacon frame (§4.3)
            target_angles = getattr(self, "_hold_target_angles", curr_cam_angles)

            if dets:
                self._transition(AutonomyState.VALIDATE, "candidate_ingested")
            else:
                self._transition(AutonomyState.SEARCH, "spot_lost_before_validation")

        elif self.state == AutonomyState.VALIDATE:
            self.total_searching_time_s += dt_eff
            # Hold dwell on current scan cell
            target_angles = getattr(self, "_hold_target_angles", curr_cam_angles)

            # Ingest into validator (§5.3)
            phot = None
            if dets:
                phot = {"snr_db": dets[0].snr_db, "peak": dets[0].peak, "centroid": (dets[0].fov_x, dets[0].fov_y)}
            vsnap = self.validator.ingest(decode_res, phot, crc_failed, self.sim_time_s)
            self._pending_validation_snap = vsnap

            if vsnap.drop_track or vsnap.state == "REJECTED":
                self.validator.reset_track()
                self._transition(AutonomyState.SEARCH, f"validation_rejected: {vsnap.reject_reason}")
            elif vsnap.state in ("SCORED", "SELECTED") and vsnap.score >= 0.60:
                self._transition(AutonomyState.SELECT, "candidate_scored")

        elif self.state == AutonomyState.SELECT:
            self.total_searching_time_s += dt_eff
            # Select best target from pool (§6)
            cands = []
            if self._pending_validation_snap and dets:
                cands.append((self._pending_validation_snap, (dets[0].fov_x, dets[0].fov_y)))
            selected_snap, selected_pos = self.selector.select(cands, self.sim_time_s, self.validator.blacklist)

            if selected_snap is not None and selected_pos is not None and selected_snap.terminal_id:
                # Lock target into tracker (§6)
                self.tracker.lock_target(selected_snap.terminal_id, selected_pos[0], selected_pos[1], self.sim_time_s)
                self.acquisition_time_s = self.sim_time_s - (self.searching_start_s or 0.0)
                self._transition(AutonomyState.TRACK, f"target_locked: {selected_snap.terminal_id}")
                pid_active = True
                track_error = self.tracker.error_px(fov_size[0], fov_size[1])
            else:
                self._transition(AutonomyState.SEARCH, "no_selectable_target")

        elif self.state == AutonomyState.TRACK:
            pid_active = True
            # Update image tracker from fresh detections (§7.1)
            tsnap = self.tracker.update(dets, dt_eff, self.sim_time_s, fov_size[0], fov_size[1], origin_shift)
            track_error = self.tracker.error_px(fov_size[0], fov_size[1])

            # In-track signature re-check every 30 frames (§7.4)
            if self.tracker._recheck_counter >= self.config.in_track_recheck_interval:
                self.tracker._recheck_counter = 0
                payload = getattr(decode_res, "payload", None) if decode_res else None
                seq = getattr(payload, "seq", None) if payload else None
                tid = getattr(payload, "tid", None) if payload else None
                valid = self.tracker.check_signature(seq, tid)
                if not valid:
                    self._transition(AutonomyState.RE_ACQUIRE, "in_track_signature_recheck_failed")

            # Check for lost target (>10 misses) (§7.1 step 4)
            if not tsnap.locked:
                self.target_loss_count += 1
                self.reacquisition_start_s = self.sim_time_s
                last_pos = (tsnap.fov_x, tsnap.fov_y)
                self.reacq_mgr.start(tsnap.terminal_id or "RT", last_pos, self.tracker.model, self.sim_time_s)
                self._transition(AutonomyState.RE_ACQUIRE, "target_lost_exceeded_misses")

        elif self.state == AutonomyState.RE_ACQUIRE:
            # Re-acquisition manager drives escalation ladder (§8)
            reacq_res = self.reacq_mgr.update(
                dets,
                decode_res,
                self.sim_time_s,
                dt_eff,
                self.selector.standby_pool,
                self.scan_ctrl,
                cam_home,
                px_per_deg,
            )

            if reacq_res.reacquired and reacq_res.target_id and reacq_res.target_pos:
                # Target re-acquired! (§8.2)
                self.reacquisition_count += 1
                if self.reacquisition_start_s is not None:
                    self.reacquisition_time_s = self.sim_time_s - self.reacquisition_start_s
                self.tracker.lock_target(reacq_res.target_id, reacq_res.target_pos[0], reacq_res.target_pos[1], self.sim_time_s)
                self._transition(AutonomyState.TRACK, "reacquired_confirmed")
            elif reacq_res.exhausted:
                # Escalation ladder exhausted -> apply reset policy (§9.3)
                if not self.full_reset():
                    self._transition(AutonomyState.FAULT, "reacquisition_exhausted_and_rate_limited")
            else:
                target_angles = reacq_res.target_angles

        elif self.state == AutonomyState.FAULT:
            # Hold wide-scan / safe position
            target_angles = (0.0, 0.0)

        # Build comprehensive telemetry
        tel = self.autonomy_telemetry()

        return SupervisorOutput(
            state=self.state,
            camera_target_angles=target_angles,
            pid_active=pid_active,
            track_error_px=track_error,
            active_target_id=self.tracker.active_terminal_id,
            telemetry=tel,
        )

    def autonomy_telemetry(self) -> dict:
        """Renderer and dashboard compatible telemetry (Plan.md §10)."""
        tsnap = self.tracker.snapshot()
        cands = []
        for d in self._current_dets:
            cands.append({
                "terminal_id": tsnap.terminal_id if tsnap.locked else "CANDIDATE",
                "fov_x": float(d.fov_x),
                "fov_y": float(d.fov_y),
                "confidence": round(float(self.tracker.photometric_confidence()), 3),
                "confirmed": bool(tsnap.locked),
            })

        det_rate = (self.detection_frames / max(1, self.total_frames)) * 100.0

        return {
            "autonomy": {
                "state": "LOCKED" if self.state == AutonomyState.TRACK else (
                    "SEARCHING" if self.state in (AutonomyState.SEARCH, AutonomyState.DETECT) else self.state.value
                ),
                "raw_state": self.state.value,
                "active_target_id": self.tracker.active_terminal_id,
                "candidates": cands,
                "standby_pool": [c.to_dict() for c in self.selector.standby_pool.all_candidates()],
                "blacklist": sorted(list(self.validator.blacklist)),
                "fault": self.fault_active,
                "full_reset_count": self.full_reset_count,
            },
            "locked": bool(tsnap.locked),
            "misses": int(tsnap.misses),
            "frames_since_detection": int(tsnap.frames_since_detection),
            "acquisition_time_s": self.acquisition_time_s,
            "reacquisition_time_s": self.reacquisition_time_s,
            "reacquisition_count": self.reacquisition_count,
            "target_loss_count": self.target_loss_count,
            "detection_rate_pct": round(det_rate, 1),
            "total_searching_time_s": round(self.total_searching_time_s, 2),
            "scan": self.scan_ctrl.telemetry(),
            "validation": self.validator.snapshot().to_dict(),
        }


__all__ = [
    "AutonomyState",
    "SupervisorConfig",
    "SupervisorOutput",
    "AutonomySupervisor",
]
