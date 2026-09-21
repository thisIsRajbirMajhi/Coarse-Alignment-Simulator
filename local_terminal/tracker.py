# local_terminal/tracker.py - Image-plane track manager (Plan.md Stages 1-2).
#
# Associates per-frame detections into a track that sources the PID error —
# closing the control loop through the disturbed image instead of ground truth.
# Stage 2 adds the α-β motion model (§7.3): association gates on the prediction,
# coasting drives toward the predicted position, uncertainty grows to the
# ±30 px search cap. Validation (§5.3-5.5) arrives in Stage 3; until then the
# brightest candidate seeds the track. Deterministic: no RNG.

from __future__ import annotations

from dataclasses import dataclass

from local_terminal.detector import Detection
from local_terminal.motion import AlphaBetaFilter2D


@dataclass
class TrackerConfig:
    """Association and loss rules (Stage 1 subset of Plan.md §7).

    loss_after_misses spans a full beacon period (336 ms): OOK blink plus
    the header's long zero-runs (version/type/length bytes) hide the spot
    for several consecutive camera frames on real frames. Counting every
    dark frame as a tracking miss would flap lock on clean air. Chip-aware
    miss gating (decode knows the chip phase) tightens this in Stage 3.
    """

    associate_gate_px: float = 60.0  # max jump from last centroid to associate
    loss_after_misses: int = 10      # ≈333 ms ≈ one 336-chip beacon period
    max_no_detection_time_s: float = 0.333  # time-based loss threshold (Fixes.md §5.5)

    def validate(self) -> "TrackerConfig":
        self.associate_gate_px = float(max(1.0, self.associate_gate_px))
        self.loss_after_misses = int(max(1, self.loss_after_misses))
        self.max_no_detection_time_s = float(max(0.05, self.max_no_detection_time_s))
        return self


@dataclass
class TrackSnapshot:
    """Immutable per-frame track output for sim snapshots and GUI."""

    locked: bool = False
    fov_x: float = 0.0
    fov_y: float = 0.0
    misses: int = 0
    frames_since_detection: int = 0
    first_lock_time_s: float | None = None
    loss_count: int = 0
    detection: Detection | None = None
    terminal_id: str | None = None
    warning_state: bool = False
    recheck_failed: bool = False


class ImageTracker:
    """Nearest-neighbour image tracker sourcing PID error from detections."""

    def __init__(self, config: TrackerConfig | None = None):
        self.config = (config or TrackerConfig()).validate()
        self.model = AlphaBetaFilter2D()
        self._locked = False
        self._cx = 0.0
        self._cy = 0.0
        self._misses = 0
        self._since_det = 0
        self._first_lock: float | None = None
        self._losses = 0
        self._last_det: Detection | None = None
        self._prev_meas: tuple[float, float] | None = None
        self._seeded = False
        self._sim_time = 0.0
        self._last_dt = 1.0 / 30.0
        self._time_since_det: float = 0.0
        self.active_terminal_id: str | None = None
        self.warning_state: bool = False
        self.recheck_failed: bool = False
        self._recheck_counter: int = 0
        self._last_verified_seq: int | None = None

    def reset(self) -> None:
        self.model.reset()
        self._locked = False
        self._cx = self._cy = 0.0
        self._misses = 0
        self._since_det = 0
        self._time_since_det = 0.0
        self._first_lock = None
        self._losses = 0
        self._last_det = None
        self._prev_meas = None
        self._seeded = False
        self._sim_time = 0.0
        self.active_terminal_id = None
        self.warning_state = False
        self.recheck_failed = False
        self._recheck_counter = 0
        self._last_verified_seq = None

    def reset_measurement_lock(self) -> None:
        """Reset measurement lock while PRESERVING motion model velocity/uncertainty (Fixes.md §3.3)."""
        self._locked = False
        self._misses = 0
        self._since_det = 0
        self._time_since_det = 0.0
        self._last_det = None
        self._prev_meas = None
        self._seeded = False
        self.warning_state = False
        self.recheck_failed = False

    def lock_target(self, terminal_id: str, fov_x: float, fov_y: float, sim_time_s: float) -> None:
        """Lock target identity and initialize tracker (Plan.md §6)."""
        self.active_terminal_id = str(terminal_id)
        self._cx = float(fov_x)
        self._cy = float(fov_y)
        self.model.reset()
        self.model.update(self._cx, self._cy, self._last_dt)
        self._prev_meas = (self._cx, self._cy)
        self._locked = True
        self._misses = 0
        self._since_det = 0
        self._time_since_det = 0.0
        self._seeded = False
        self.recheck_failed = False
        self._recheck_counter = 0
        self._last_verified_seq = None
        if self._first_lock is None:
            self._first_lock = float(sim_time_s)

    def check_signature(self, seq: int | None, tid: str | None) -> bool:
        """In-track signature re-check every 30 frames (Plan.md §7.4)."""
        if not self._locked or self.active_terminal_id is None:
            return True
        from common.protocol.beacon.navigation import sequence_is_newer
        if tid is not None and str(tid) != self.active_terminal_id:
            self.recheck_failed = True
            self._locked = False
            self._losses += 1
            return False
        if seq is not None and self._last_verified_seq is not None:
            if not sequence_is_newer(int(seq), int(self._last_verified_seq)):
                self.recheck_failed = True
                self._locked = False
                self._losses += 1
                return False
        if seq is not None:
            self._last_verified_seq = int(seq)
        self.recheck_failed = False
        return True

    def update(self, detections: list[Detection], dt: float, sim_time_s: float,
               fov_w: int = 640, fov_h: int = 480,
               origin_shift: tuple[float, float] = (0.0, 0.0)) -> TrackSnapshot:
        """Associate one frame of detections; advance lock/miss counters."""
        self._sim_time = float(sim_time_s)
        self._last_dt = max(float(dt), 1e-6)
        if self._locked:
            self._recheck_counter += 1
        # Translate prior against camera motion, then predict to this frame.
        self.model.shift(-float(origin_shift[0]), -float(origin_shift[1]))
        pred_x, pred_y = self.model.predict(self._last_dt)
        gate = self.config.associate_gate_px + self.model.uncertainty_px
        pick: Detection | None = None
        if detections:
            if self._locked:
                gated = [d for d in detections
                         if ((d.fov_x - pred_x) ** 2 + (d.fov_y - pred_y) ** 2) ** 0.5 <= gate]
                if gated:
                    pick = max(gated, key=lambda d: d.peak)
            else:
                pick = max(detections, key=lambda d: d.peak)
        if pick is not None:
            self._cx, self._cy = float(pick.fov_x), float(pick.fov_y)
            # Centroid error check for warning state (§7.2)
            c_err = ((self._cx - pred_x) ** 2 + (self._cy - pred_y) ** 2) ** 0.5
            if c_err > 10.0:
                self.warning_state = True
                self.model.ax.config.alpha = 0.6
                self.model.ay.config.alpha = 0.6
            else:
                self.warning_state = False
                self.model.ax.config.alpha = 0.4
                self.model.ay.config.alpha = 0.4

            if not self._seeded and self._misses == 0 and self._prev_meas is not None:
                self.model.initialise(self._prev_meas[0], self._prev_meas[1],
                                      self._cx, self._cy, self._last_dt)
                self._seeded = True
            else:
                self.model.update(self._cx, self._cy, self._last_dt)
            self._prev_meas = (self._cx, self._cy)
            self._misses = 0
            self._since_det = 0
            self._time_since_det = 0.0
            self._last_det = pick
            if not self._locked:
                self._locked = True
                if self._first_lock is None:
                    self._first_lock = float(sim_time_s)
        else:
            self._prev_meas = None
            self.model.coast(self._last_dt)
            self._misses += 1
            self._since_det += 1
            self._time_since_det += self._last_dt
            if self._locked and (self._misses > self.config.loss_after_misses or self._time_since_det > self.config.max_no_detection_time_s):
                self._locked = False
                self._losses += 1
        return self.snapshot()

    def snapshot(self) -> TrackSnapshot:
        return TrackSnapshot(
            locked=self._locked,
            fov_x=self._cx,
            fov_y=self._cy,
            misses=self._misses,
            frames_since_detection=self._since_det,
            first_lock_time_s=self._first_lock,
            loss_count=self._losses,
            detection=self._last_det if self._misses == 0 else None,
            terminal_id=self.active_terminal_id,
            warning_state=self.warning_state,
            recheck_failed=self.recheck_failed,
        )

    def error_px(self, fov_w: int = 640, fov_h: int = 480) -> tuple[float, float] | None:
        """Pixel error (target − boresight) for the PID, or None when lost.

        Fresh detection → measured centroid error. Coasting (misses within
        the loss horizon) → predicted-position error, so the camera slews to
        the predicted location instead of holding blindly (Plan §7.1).
        """
        if not self._locked:
            return None
        if self._misses == 0:
            return (self._cx - fov_w / 2.0, self._cy - fov_h / 2.0)
        if self._misses <= self.config.loss_after_misses:
            # Coast state already holds this frame's prediction (update() ran
            # model.coast); steer toward it without double-propagating.
            ex, ey = self.model.estimate
            return (ex - fov_w / 2.0, ey - fov_h / 2.0)
        return None

    @property
    def predicted_fov(self) -> tuple[float, float]:
        return self.model.predict(self._last_dt)

    def photometric_confidence(self) -> float:
        """Pre-validation confidence from photometry only (Stage 3 replaces this)."""
        det = self._last_det
        if det is None or self._misses > 0:
            return 0.0
        snr_term = max(0.0, min(1.0, (det.snr_db - 6.0) / 12.0))
        return float(0.5 * snr_term + 0.5 * det.compactness_r2)

    def autonomy_telemetry(self) -> dict:
        """Renderer-compatible autonomy schema (gui/core/renderer.py §1)."""
        snap = self.snapshot()
        cands = []
        if snap.detection is not None:
            cands.append({
                "terminal_id": "TRACK",
                "fov_x": float(snap.fov_x),
                "fov_y": float(snap.fov_y),
                "confidence": round(self.photometric_confidence(), 3),
                "confirmed": bool(snap.locked),
            })
        vx, vy = self.model.velocity
        px, py = self.predicted_fov
        return {
            "autonomy": {
                "state": "LOCKED" if snap.locked else "SEARCHING",
                "active_target_id": "TRACK" if snap.locked else None,
                "candidates": cands,
            },
            "locked": bool(snap.locked),
            "misses": int(snap.misses),
            "frames_since_detection": int(snap.frames_since_detection),
            "acquisition_time_s": snap.first_lock_time_s,
            "target_loss_count": int(snap.loss_count),
            "detection_rate_pct": 100.0 if snap.locked else 0.0,
            "velocity_px_s": [round(float(vx), 3), round(float(vy), 3)],
            "uncertainty_px": round(float(self.model.uncertainty_px), 3),
            "predicted_fov": [round(float(px), 2), round(float(py), 2)],
        }


__all__ = ["ImageTracker", "TrackerConfig", "TrackSnapshot"]
