# local_terminal/reacquisition.py - Re-acquisition Manager (Plan.md §8).
#
# Escalation ladder (blacklist and motion model preserved throughout):
# 1. Predicted-location window (<= half scene = 1000 px).
# 2. Standby-pool candidates in score order.
# 3. Last-known 3x3 priority scan.
# 4. Full systematic scan with motion-weighted order - NOT a reset.
# 5. Exhausted -> autonomy supervisor reset policy (§9.3).

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Sequence

from local_terminal.detector import Detection
from local_terminal.motion import AlphaBetaFilter2D
from local_terminal.scan import ScanController
from local_terminal.selector import StandbyCandidate, StandbyPool
from local_terminal.validator import ValidationSnapshot


class EscalationStage(enum.Enum):
    LOCAL_SEARCH = 1      # Predicted location with expanding search window
    STANDBY_POOL = 2      # Testing standby pool candidates
    PRIORITY_3X3 = 3      # 3×3 FOV patch around last-known position
    SYSTEMATIC_SCAN = 4   # Full scan with motion-weighted order
    EXHAUSTED = 5         # Exhausted all options -> supervisor reset policy


@dataclass
class ReacquisitionConfig:
    initial_radius_px: float = 50.0
    radius_step_px: float = 20.0
    max_radius_px: float = 1000.0  # half scene (Plan.md §8.3 step 1)
    confirm_timeout_s: float = 0.672  # 2 beacon periods watchdog (§9.2)
    max_standby_attempts: int = 3

    def validate(self) -> "ReacquisitionConfig":
        self.initial_radius_px = float(max(10.0, self.initial_radius_px))
        self.radius_step_px = float(max(1.0, self.radius_step_px))
        self.max_radius_px = float(max(self.initial_radius_px, self.max_radius_px))
        self.confirm_timeout_s = float(max(0.1, self.confirm_timeout_s))
        return self


@dataclass
class ReacquisitionResult:
    reacquired: bool = False
    provisional: bool = False
    target_id: str | None = None
    target_pos: tuple[float, float] | None = None
    stage: EscalationStage = EscalationStage.LOCAL_SEARCH
    target_angles: tuple[float, float] | None = None
    exhausted: bool = False


class ReacquisitionManager:
    """Manages localized re-acquisition and the 5-stage escalation ladder (Plan.md §8)."""

    def __init__(self, config: ReacquisitionConfig | None = None):
        self.config = (config or ReacquisitionConfig()).validate()
        self.stage: EscalationStage = EscalationStage.LOCAL_SEARCH
        self.target_id: str | None = None
        self.last_known_pos: tuple[float, float] = (1000.0, 1000.0)
        self.model: AlphaBetaFilter2D = AlphaBetaFilter2D()
        self.current_radius_px: float = self.config.initial_radius_px
        self.provisional_active: bool = False
        self.provisional_pos: tuple[float, float] | None = None
        self.confirm_deadline: float | None = None
        self.active: bool = False
        self._standby_tried: set[str] = set()

    def start(
        self,
        target_id: str,
        last_known_pos: tuple[float, float],
        model: AlphaBetaFilter2D,
        now_s: float,
    ) -> None:
        """Enter re-acquisition mode (Plan.md §8.1)."""
        self.active = True
        self.target_id = str(target_id)
        self.last_known_pos = (float(last_known_pos[0]), float(last_known_pos[1]))
        self.model = model
        self.stage = EscalationStage.LOCAL_SEARCH
        self.current_radius_px = self.config.initial_radius_px
        self.provisional_active = False
        self.provisional_pos = None
        self.confirm_deadline = None
        self._standby_tried.clear()

    def reset(self) -> None:
        self.active = False
        self.target_id = None
        self.stage = EscalationStage.LOCAL_SEARCH
        self.provisional_active = False
        self.provisional_pos = None
        self.confirm_deadline = None
        self._standby_tried.clear()

    def update(
        self,
        detections: list[Detection],
        decode_result,
        now_s: float,
        dt: float,
        standby_pool: StandbyPool,
        scan_ctrl: ScanController,
        cam_home: tuple[float, float] = (1000.0, 1000.0),
        px_per_deg: tuple[float, float] = (160.0, 160.0),
    ) -> ReacquisitionResult:
        """Advance re-acquisition by one frame.

        Args:
            detections: fresh detections in FOV.
            decode_result: BeaconDecodeResult from comm receiver if any.
            now_s: current sim time.
            dt: step dt.
            standby_pool: StandbyPool of alternative candidates.
            scan_ctrl: ScanController for priority / systematic scan.
            cam_home: world coords of gimbal (0°, 0°).
            px_per_deg: (px_per_deg_h, px_per_deg_v).
        """
        if not self.active or self.target_id is None:
            return ReacquisitionResult()

        now = float(now_s)

        # -- Check Provisional Confirmation Gate (§8.2 step 4) --
        if self.provisional_active:
            if decode_result is not None and getattr(decode_result, "valid_crc", False):
                payload = getattr(decode_result, "payload", None)
                tid = getattr(payload, "tid", "")
                if tid == self.target_id:
                    # Confirmed! Re-acquisition complete (§8.2 step 4)
                    res = ReacquisitionResult(
                        reacquired=True,
                        provisional=False,
                        target_id=self.target_id,
                        target_pos=self.provisional_pos,
                        stage=self.stage,
                    )
                    self.reset()
                    return res

            if self.confirm_deadline is not None and now > self.confirm_deadline:
                # Confirm timeout: drop back to expanding window (§8.2 step 4)
                self.provisional_active = False
                self.provisional_pos = None
                self.confirm_deadline = None
                self.current_radius_px += self.config.radius_step_px

        # -- Stage 1: Localized Search (§8.2 steps 1-3) --
        if self.stage == EscalationStage.LOCAL_SEARCH:
            pred_x, pred_y = self.model.predict(dt)
            # Slew camera toward predicted location
            pan = (pred_x - cam_home[0]) / px_per_deg[0]
            tilt = (cam_home[1] - pred_y) / px_per_deg[1]
            angles = (float(pan), float(tilt))

            # Check detections within current search radius (§8.2 step 2)
            matching_det = None
            if detections:
                for d in detections:
                    dist = math.hypot(d.fov_x - 320.0, d.fov_y - 240.0)
                    if dist <= self.current_radius_px:
                        matching_det = d
                        break

            if matching_det is not None and not self.provisional_active:
                # Provisional resume gate (§8.2 step 3): photometric detection
                self.provisional_active = True
                self.provisional_pos = (matching_det.fov_x, matching_det.fov_y)
                self.confirm_deadline = now + self.config.confirm_timeout_s
                return ReacquisitionResult(
                    reacquired=False,
                    provisional=True,
                    target_id=self.target_id,
                    target_pos=self.provisional_pos,
                    stage=self.stage,
                    target_angles=angles,
                )

            # Not found or awaiting confirm: expand radius incrementally
            if not self.provisional_active:
                self.current_radius_px += self.config.radius_step_px
                if self.current_radius_px > self.config.max_radius_px:
                    # Escalate to Standby Pool (§8.3 step 2)
                    self.stage = EscalationStage.STANDBY_POOL

            return ReacquisitionResult(
                reacquired=False,
                provisional=self.provisional_active,
                target_id=self.target_id,
                target_pos=self.provisional_pos,
                stage=self.stage,
                target_angles=angles,
            )

        # -- Stage 2: Standby Pool Candidates (§8.3 step 2) --
        elif self.stage == EscalationStage.STANDBY_POOL:
            best_cand = standby_pool.get_best()
            if best_cand and best_cand.snapshot.terminal_id not in self._standby_tried:
                self._standby_tried.add(str(best_cand.snapshot.terminal_id))
                pan = (best_cand.fov_x - cam_home[0]) / px_per_deg[0]
                tilt = (cam_home[1] - best_cand.fov_y) / px_per_deg[1]
                angles = (float(pan), float(tilt))
                # If target decodes cleanly from standby position
                if decode_result is not None and getattr(decode_result, "valid_crc", False):
                    payload = getattr(decode_result, "payload", None)
                    if payload and payload.tid == best_cand.snapshot.terminal_id:
                        self.target_id = payload.tid
                        res = ReacquisitionResult(
                            reacquired=True,
                            provisional=False,
                            target_id=self.target_id,
                            target_pos=(best_cand.fov_x, best_cand.fov_y),
                            stage=self.stage,
                        )
                        self.reset()
                        return res
                return ReacquisitionResult(
                    reacquired=False,
                    provisional=False,
                    target_id=self.target_id,
                    stage=self.stage,
                    target_angles=angles,
                )
            else:
                # Standby pool exhausted -> Escalate to 3×3 Priority Scan (§8.3 step 3)
                self.stage = EscalationStage.PRIORITY_3X3
                scan_ctrl.plan_schedule(
                    priority_mode="LAST_KNOWN",
                    last_known=self.last_known_pos,
                )

        # -- Stage 3: Last-Known 3×3 Priority Scan (§8.3 step 3) --
        if self.stage == EscalationStage.PRIORITY_3X3:
            pos = scan_ctrl.step(has_decoding_candidate=len(detections) > 0)
            angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])
            if decode_result is not None and getattr(decode_result, "valid_crc", False):
                payload = getattr(decode_result, "payload", None)
                if payload and payload.tid == self.target_id:
                    res = ReacquisitionResult(
                        reacquired=True,
                        provisional=False,
                        target_id=self.target_id,
                        target_pos=(pos.center_x, pos.center_y),
                        stage=self.stage,
                    )
                    self.reset()
                    return res
            if scan_ctrl.cycle_completed:
                # 3×3 scan completed without target -> Escalate to Full Scan (§8.3 step 4)
                self.stage = EscalationStage.SYSTEMATIC_SCAN
                scan_ctrl.plan_schedule(priority_mode="SYSTEMATIC")

            return ReacquisitionResult(
                reacquired=False,
                provisional=False,
                target_id=self.target_id,
                stage=self.stage,
                target_angles=angles,
            )

        # -- Stage 4: Full Systematic Scan (§8.3 step 4) --
        elif self.stage == EscalationStage.SYSTEMATIC_SCAN:
            pos = scan_ctrl.step(has_decoding_candidate=len(detections) > 0)
            angles = pos.target_angles(cam_home, px_per_deg[0], px_per_deg[1])
            if decode_result is not None and getattr(decode_result, "valid_crc", False):
                payload = getattr(decode_result, "payload", None)
                if payload and payload.tid == self.target_id:
                    res = ReacquisitionResult(
                        reacquired=True,
                        provisional=False,
                        target_id=self.target_id,
                        target_pos=(pos.center_x, pos.center_y),
                        stage=self.stage,
                    )
                    self.reset()
                    return res
            if scan_ctrl.cycle_completed:
                # Full scan completed without finding target -> Exhausted (§8.3 step 5)
                self.stage = EscalationStage.EXHAUSTED
                return ReacquisitionResult(
                    reacquired=False,
                    provisional=False,
                    target_id=self.target_id,
                    stage=self.stage,
                    exhausted=True,
                )

            return ReacquisitionResult(
                reacquired=False,
                provisional=False,
                target_id=self.target_id,
                stage=self.stage,
                target_angles=angles,
            )

        # -- Stage 5: Exhausted (§8.3 step 5) --
        return ReacquisitionResult(
            reacquired=False,
            provisional=False,
            target_id=self.target_id,
            stage=EscalationStage.EXHAUSTED,
            exhausted=True,
        )


__all__ = [
    "EscalationStage",
    "ReacquisitionConfig",
    "ReacquisitionResult",
    "ReacquisitionManager",
]
