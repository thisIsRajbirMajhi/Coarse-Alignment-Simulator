# tracking/pipeline — closed-loop perception-estimation-control with GT isolation
#
# Signal path (no privileged state anywhere in here):
#   frame -> detector -> association -> tracker -> state machine -> PID -> d_pan,d_tilt
#
# GT isolation: this module never imports simulator target state, never accepts
# gt_x/gt_y. Metric error (estimate vs GT) is computed OUTSIDE, in logger only.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from control.config import ControllerConfig
from control.controller import PIDController
from tracking.association import AssociationConfig, associate
from tracking.detector import Detection, DetectorConfig, UnifiedDetector, pixel_error
from tracking.kalman import KalmanConfig, KalmanTracker
from tracking.state_machine import (
    LOST,
    REACQUIRING,
    SEARCHING,
    TRACKING,
    AcquisitionStateMachine,
    StateMachineConfig,
)


@dataclass
class PipelineResult:
    all_detections: list[Detection]
    selected: Detection | None
    estimate: tuple[float, float] | None  # tracker (x, y) in FOV px
    velocity: tuple[float, float]  # tracker (vx, vy) px/s
    error_x: float | None  # control error vs boresight
    error_y: float | None
    error_px: float | None
    state: str
    d_pan: float
    d_tilt: float
    latency_ms: float


class TrackingPipeline:
    """Owns detector + association + tracker + state + PID. Frame in, motion out."""

    def __init__(
        self,
        detector_config: DetectorConfig | None = None,
        assoc_config: AssociationConfig | None = None,
        kalman_config: KalmanConfig | None = None,
        state_config: StateMachineConfig | None = None,
        controller_config: ControllerConfig | None = None,
        fov_size: tuple[int, int] = (640, 480),
        model_path: str | None = None,
        use_yolo: bool = True,
    ):
        self.detector_config = (detector_config or DetectorConfig()).validate()
        self.assoc_config = (assoc_config or AssociationConfig()).validate()
        self.kalman_config = (kalman_config or KalmanConfig()).validate()
        self.state_config = (state_config or StateMachineConfig()).validate()
        self.controller_config = (controller_config or ControllerConfig()).validate()
        # Enforce AI-ready: never allow privileged velocity through this path
        self.controller_config.use_privileged_velocity = False
        self.use_yolo = bool(use_yolo)

        if self.use_yolo:
            self.detector = UnifiedDetector(self.detector_config, model_path=model_path)
        else:
            # Real-time GUI path: classical only (fast, no backend clash, 30Hz safe)
            from tracking.detector import BrightSpotDetector

            self.detector = BrightSpotDetector(self.detector_config)
        self.tracker = KalmanTracker(self.kalman_config)
        self.states = AcquisitionStateMachine(self.state_config)
        self.controller = PIDController(config=self.controller_config)
        self.fov_w, self.fov_h = int(fov_size[0]), int(fov_size[1])

    def reset(self) -> None:
        self.tracker = KalmanTracker(self.kalman_config)
        self.states.reset()
        self.controller = PIDController(config=self.controller_config)

    def update(self, frame: np.ndarray, dt: float | None = None) -> PipelineResult:
        dt = float(dt if dt is not None else 1 / 30)
        # 1. Detect (image only)
        all_dets = self.detector.detect(frame)
        latency = float(getattr(self.detector, "last_latency_ms", 0.0))

        # 2. Associate against tracker prediction (temporal, not confidence-only)
        if self.tracker.initialized:
            pred = self.tracker.position
            last_pos = self.tracker.position
            last_vel = self.tracker.velocity
        else:
            pred = None
            last_pos = None
            last_vel = None
        selected = associate(
            all_dets, predicted=pred, last_position=last_pos,
            last_velocity=last_vel, dt=dt, config=self.assoc_config,
        )

        # 3. Fuse into tracker
        meas = selected.center if selected is not None else None
        t_state = self.tracker.step(meas, dt)
        est = (float(t_state[0]), float(t_state[1]))
        vel = (float(t_state[2]), float(t_state[3]))

        # If nothing ever seen, estimate stays None (searching, no control)
        estimate: tuple[float, float] | None = est if (selected is not None or self.tracker.initialized) else None
        if not self.tracker.initialized:
            estimate = None

        # 4. Supervise state (detection-gated, stale-aware)
        state = self.states.step(
            detected=selected is not None,
            tracker_stale=bool(self.tracker.stale),
            dt=dt,
        )

        # 5. Control ONLY in TRACKING, from estimate vs boresight, velocity from tracker
        d_pan, d_tilt = 0.0, 0.0
        ex, ey, epx = None, None, None
        if estimate is not None:
            ex, ey, epx = pixel_error(estimate[0], estimate[1], self.fov_w, self.fov_h)
        if state == TRACKING and estimate is not None:
            try:
                # Slew limit from camera is passed by caller via controller clamp;
                # here we use output_clamp only (camera clamp applied at move).
                d_pan, d_tilt = self.controller.compute_correction(
                    float(ex), float(ey), dt=dt, target_velocity=vel,
                )
            except Exception:
                d_pan, d_tilt = 0.0, 0.0
        else:
            d_pan, d_tilt = 0.0, 0.0

        return PipelineResult(
            all_detections=all_dets,
            selected=selected,
            estimate=estimate,
            velocity=vel,
            error_x=ex,
            error_y=ey,
            error_px=epx,
            state=state,
            d_pan=float(d_pan),
            d_tilt=float(d_tilt),
            latency_ms=latency,
        )
