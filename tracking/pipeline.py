# tracking/pipeline — closed-loop perception-estimation-control with GT isolation
#
# Signal path (no privileged state anywhere in here):
#   frame -> detector -> association -> tracker (KF/IMM) -> state machine -> PID/search -> d_pan,d_tilt
#
# GT isolation: this module never imports simulator target state, never accepts
# gt_x/gt_y. Metric error (estimate vs GT) is computed OUTSIDE, in logger only.

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from control.config import ControllerConfig
from control.controller import PIDController
from tracking.association import AssociationConfig, associate
from tracking.detector import Detection, DetectorConfig, UnifiedDetector, expected_color_for_target, pixel_error
from tracking.imm import IMMConfig, IMMTracker
from tracking.kalman import KalmanConfig, KalmanTracker
from tracking.multitrack import MultiBeaconTracker
from tracking.search import SearchPattern
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
    # Phase-4 additions (defaults keep old unpacking working):
    lock_quality: float = 0.0
    model_probs: tuple[float, ...] = field(default_factory=tuple)
    search_active: bool = False
    predicted_next: tuple[float, float] | None = None
    # Multi-beacon identity (B+C):
    designated_target_id: int | None = None
    locked_track_id: int | None = None
    id_switches: int = 0
    n_tracks: int = 0


class TrackingPipeline:
    """Owns detector + association + tracker + state + PID + search. Frame in, motion out."""

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
        use_imm: bool = False,
        imm_config: IMMConfig | None = None,
        search_enabled: bool = True,
        search_mode: str = "adaptive",
        designated_target_id: int | None = None,
        max_tracks: int = 5,
    ):
        self.detector_config = (detector_config or DetectorConfig()).validate()
        self.assoc_config = (assoc_config or AssociationConfig()).validate()
        self.kalman_config = (kalman_config or KalmanConfig()).validate()
        self.state_config = (state_config or StateMachineConfig()).validate()
        self.controller_config = (controller_config or ControllerConfig()).validate()
        # Enforce AI-ready: never allow privileged velocity through this path
        self.controller_config.use_privileged_velocity = False
        self.use_yolo = bool(use_yolo)
        self.use_imm = bool(use_imm)
        self.imm_config = (imm_config or IMMConfig()).validate()

        if self.use_yolo:
            self.detector = UnifiedDetector(self.detector_config, model_path=model_path)
        else:
            # Real-time GUI path: classical only (fast, no backend clash, 30Hz safe)
            from tracking.detector import BrightSpotDetector

            self.detector = BrightSpotDetector(self.detector_config)
        if self.use_imm:
            self.tracker = IMMTracker(self.imm_config)
        else:
            self.tracker = KalmanTracker(self.kalman_config)
        self.states = AcquisitionStateMachine(self.state_config)
        self.controller = PIDController(config=self.controller_config)
        self.fov_w, self.fov_h = int(fov_size[0]), int(fov_size[1])
        self.search_enabled = bool(search_enabled)
        self.search = SearchPattern(
            pan_speed=240.0,
            row_step=SearchPattern.coverage_row_step(float(self.fov_h), 0.25),
            mode=search_mode,
        )
        self._last_size: float | None = None
        self._last_area: float | None = None
        self._last_circ: float | None = None
        # B: designated mission target (mission intent, not per-frame GT).
        self.designated_target_id: int | None = int(designated_target_id) if designated_target_id is not None else None
        self.expected_color = expected_color_for_target(self.designated_target_id)
        self._latched_color: tuple[float, float, float] | None = None
        self._prev_center: tuple[float, float] | None = None
        # C: persistent hypothesis tracks (distractors keep their own tracks).
        self.multi = MultiBeaconTracker(
            max_tracks=int(max_tracks), use_imm=bool(use_imm),
            imm_config=self.imm_config, kalman_config=self.kalman_config,
            assoc_config=self.assoc_config,
        )
        self.multi.set_expected_color(self.expected_color)

    def set_designated_target(self, idx: int | None) -> None:
        """Mission retarget (operator/GUI): latch new expected tint, keep filters.

        Does NOT use GT position — only the pre-known per-ID color signature.
        Identity re-resolves over the next frames via color + continuity.
        """
        try:
            self.designated_target_id = int(idx) if idx is not None else None
        except Exception:
            self.designated_target_id = None
        try:
            self.expected_color = expected_color_for_target(self.designated_target_id)
            self.multi.set_expected_color(self.expected_color)
            # Re-anchor latch to expected (observed latch re-tunes after lock).
            self._latched_color = self.expected_color
        except Exception:
            pass

    def reset(self) -> None:
        if self.use_imm:
            self.tracker = IMMTracker(self.imm_config)
        else:
            self.tracker = KalmanTracker(self.kalman_config)
        self.states.reset()
        self.controller = PIDController(config=self.controller_config)
        self.search.reset()
        self._last_size = None
        self._last_area = None
        self._last_circ = None
        self._latched_color = self.expected_color
        self._prev_center = None
        try:
            self.multi.reset()
            self.multi.set_expected_color(self.expected_color)
        except Exception:
            pass

    def _tracker_cov(self):
        try:
            return self.tracker.cov_xy
        except Exception:
            return None

    def update(
        self,
        frame: np.ndarray,
        dt: float | None = None,
        current_pan_tilt: tuple[float, float] | None = None,
        pan_range: tuple[float, float] | None = None,
        tilt_range: tuple[float, float] | None = None,
    ) -> PipelineResult:
        dt = float(dt if dt is not None else 1 / 30)
        # 1. Detect (image only, fused YOLO+classical with uncertainty)
        all_dets = self.detector.detect(frame)
        latency = float(getattr(self.detector, "last_latency_ms", 0.0))

        # 2. Multi-hypothesis identity (C) + designated associate (B).
        # multi keeps one filter per visible beacon; designated track wins
        # ties via expected/latched color + continuity. The single control
        # filter below is then stepped with the designated detection only,
        # so distractors can no longer drag the servo state.
        designated_det: Detection | None = None
        try:
            _des_track, _assign = self.multi.step(all_dets, dt)
            if _des_track is not None:
                # Find the box assigned to the designated internal track.
                try:
                    idx = next(i for i, t in enumerate(self.multi.tracks) if t.internal_id == _des_track.internal_id)
                    designated_det = _assign.get(idx)
                except Exception:
                    designated_det = None
        except Exception:
            designated_det = None
        # Template: latched observation anchored to expected mission tint.
        template = self._latched_color if self._latched_color is not None else self.expected_color
        # 2b. Associate against tracker *predicted* position (§18 Expected
        # Target Position): non-mutating peek forward by dt so the anchor
        # leads the target instead of lagging one frame behind.
        if self.tracker.initialized:
            last_pos = self.tracker.position
            last_vel = self.tracker.velocity
            try:
                peek_xy, peek_cov = self.tracker.peek_predict(dt)
                pred = (float(peek_xy[0]), float(peek_xy[1]))
                pred_cov = peek_cov
            except Exception:
                pred = self.tracker.position
                pred_cov = self._tracker_cov()
        else:
            pred = None
            last_pos = None
            last_vel = None
            pred_cov = None
        single = associate(
            all_dets, predicted=pred, last_position=last_pos,
            last_velocity=last_vel, dt=dt, config=self.assoc_config,
            pred_cov=pred_cov, last_size=self._last_size,
            last_area=self._last_area, last_circ=self._last_circ,
            boresight=(self.fov_w / 2.0, self.fov_h / 2.0),
            template_color=template, prev_center=self._prev_center,
        )
        # Prefer multi-track designated identity when available; fall back to
        # single-frame associate (first frames / single beacon).
        selected = designated_det if designated_det is not None else single

        # 3. Fuse into tracker with per-detection measurement noise
        meas = selected.center if selected is not None else None
        meas_var = float(getattr(selected, "pos_var", 9.0)) if selected is not None else None
        try:
            t_state = self.tracker.step(meas, dt, meas_var=meas_var)
        except TypeError:
            t_state = self.tracker.step(meas, dt)
        est = (float(t_state[0]), float(t_state[1]))
        vel = (float(t_state[2]), float(t_state[3]))
        if selected is not None:
            try:
                sz = (float(selected.width) + float(selected.height)) / 2.0
                self._last_size = sz if self._last_size is None else 0.9 * self._last_size + 0.1 * sz
            except Exception:
                pass
            try:
                ar = float(getattr(selected, "area", 0.0) or (selected.width * selected.height))
                self._last_area = ar if self._last_area is None else 0.9 * self._last_area + 0.1 * ar
            except Exception:
                pass
            try:
                ci = float(getattr(selected, "circularity", 1.0))
                self._last_circ = ci if self._last_circ is None else 0.9 * self._last_circ + 0.1 * ci
            except Exception:
                pass
            try:
                dc = getattr(selected, "color_bgr", None)
                if dc is not None:
                    dc = (float(dc[0]), float(dc[1]), float(dc[2]))
                    base = self._latched_color if self._latched_color is not None else self.expected_color
                    if base is None:
                        self._latched_color = dc
                    else:
                        # Latch follows observations slowly, anchored to expected.
                        obs = (0.85 * base[0] + 0.15 * dc[0], 0.85 * base[1] + 0.15 * dc[1], 0.85 * base[2] + 0.15 * dc[2])
                        exp = self.expected_color
                        if exp is not None:
                            self._latched_color = (0.7 * obs[0] + 0.3 * exp[0], 0.7 * obs[1] + 0.3 * exp[1], 0.7 * obs[2] + 0.3 * exp[2])
                        else:
                            self._latched_color = obs
                self._prev_center = (float(selected.center[0]), float(selected.center[1]))
            except Exception:
                pass

        # If nothing ever seen, estimate stays None (searching, no control)
        estimate: tuple[float, float] | None = est if (selected is not None or self.tracker.initialized) else None
        if not self.tracker.initialized:
            estimate = None

        # Lock quality (covariance + coast + residual + IMM regime confidence)
        try:
            lq = self.tracker.lock_quality()
            quality = float(lq.get("quality", 0.0))
        except Exception:
            quality = 1.0 if selected is not None else 0.0

        # 4. Supervise state (detection-gated, stale-aware, quality-aware M/N)
        try:
            state = self.states.step(
                detected=selected is not None,
                tracker_stale=bool(self.tracker.stale),
                dt=dt,
                quality=quality,
            )
        except TypeError:
            state = self.states.step(
                detected=selected is not None,
                tracker_stale=bool(self.tracker.stale),
                dt=dt,
            )

        # Predicted next (for reacq focus + controller look-ahead)
        predicted_next = None
        try:
            pn, _ = self.tracker.peek_predict(dt)
            predicted_next = (float(pn[0]), float(pn[1]))
        except Exception:
            predicted_next = estimate

        try:
            model_probs = tuple(self.tracker.model_probs)  # IMM only
        except Exception:
            model_probs = tuple()

        # 5. Control ONLY in TRACKING, from estimate vs boresight, velocity from tracker
        d_pan, d_tilt = 0.0, 0.0
        ex, ey, epx = None, None, None
        if estimate is not None:
            ex, ey, epx = pixel_error(estimate[0], estimate[1], self.fov_w, self.fov_h)
        search_active = False
        if state == TRACKING and estimate is not None:
            try:
                try:
                    spd = float(np.hypot(vel[0], vel[1]))
                except Exception:
                    spd = None
                try:
                    self.controller.schedule_by_lock(quality, spd)
                except Exception:
                    pass
                try:
                    d_pan, d_tilt = self.controller.compute_correction(
                        float(ex), float(ey), dt=dt, target_velocity=vel,
                        lock_quality=quality,
                    )
                except TypeError:
                    d_pan, d_tilt = self.controller.compute_correction(
                        float(ex), float(ey), dt=dt, target_velocity=vel,
                    )
            except Exception:
                d_pan, d_tilt = 0.0, 0.0
        elif self.search_enabled and current_pan_tilt is not None and pan_range is not None and tilt_range is not None:
            # Active search / reacq steering (§27-§29): spiral around the
            # *predicted* target location sized by tracker uncertainty
            # (3-sigma + margin), else blind raster sweep. 1 FOV px == 1
            # pan/tilt unit, so focus = current + (predicted - boresight).
            try:
                if state in (LOST, REACQUIRING) and self.tracker.initialized:
                    try:
                        rad = float(self.tracker.uncertainty_radius) * 3.0 + 40.0
                    except Exception:
                        rad = 120.0
                    try:
                        px, py = predicted_next if predicted_next is not None else estimate
                        ox = float(np.clip(float(px) - self.fov_w / 2.0, -self.fov_w, self.fov_w))
                        oy = float(np.clip(float(py) - self.fov_h / 2.0, -self.fov_h, self.fov_h))
                    except Exception:
                        ox, oy = 0.0, 0.0
                    self.search.set_focus(float(current_pan_tilt[0]) + ox, float(current_pan_tilt[1]) + oy, rad)
                elif state == SEARCHING:
                    self.search.clear_focus()
                nx, ny = self.search.step(
                    float(current_pan_tilt[0]), float(current_pan_tilt[1]),
                    (float(pan_range[0]), float(pan_range[1])),
                    (float(tilt_range[0]), float(tilt_range[1])), dt,
                )
                d_pan = float(nx - float(current_pan_tilt[0]))
                d_tilt = float(ny - float(current_pan_tilt[1]))
                search_active = True
            except Exception:
                d_pan, d_tilt = 0.0, 0.0
        else:
            d_pan, d_tilt = 0.0, 0.0

        try:
            locked_id = self.multi.designated_internal_id
        except Exception:
            locked_id = None
        try:
            ntr = len(self.multi.tracks)
        except Exception:
            ntr = 0
        try:
            nsw = int(self.multi.id_switches)
        except Exception:
            nsw = 0
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
            lock_quality=float(quality),
            model_probs=model_probs,
            search_active=bool(search_active),
            predicted_next=predicted_next,
            designated_target_id=self.designated_target_id,
            locked_track_id=locked_id,
            id_switches=nsw,
            n_tracks=int(ntr),
        )
