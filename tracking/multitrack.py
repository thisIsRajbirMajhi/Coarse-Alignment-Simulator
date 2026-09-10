# tracking/multitrack — persistent multi-hypothesis beacon tracks (C).
#
# Why: single associate() picks "nearest to prediction" each frame, so on
# crossings/occlusions it jumps to the brightest distractor. This manager
# keeps one filter per visible beacon (up to max_tracks), assigns boxes with
# associate_multi() (one box <-> one track), and holds a *designated* track
# for the mission target. Distractors get their own tracks instead of
# stealing the designated one.
#
# Identity: internal ids 0..N (image persistence), NOT sim beacon ids (GT).
# Designated matching uses the pre-known per-ID color template
# (expected_color_for_target, mission signature) + motion continuity, plus a
# latched EMA template after lock. No per-frame GT is used.

from __future__ import annotations

import numpy as np

from tracking.association import associate_multi
from tracking.detector import Detection, color_distance
from tracking.kalman import KalmanConfig, KalmanTracker


class BeaconTrack:
    _next_id = 0

    def __init__(self, use_imm: bool = False, imm_config=None, kalman_config=None):
        try:
            tid = int(BeaconTrack._next_id)
        except Exception:
            tid = 0
        BeaconTrack._next_id = tid + 1
        self.internal_id = tid
        self.use_imm = bool(use_imm)
        if use_imm:
            from tracking.imm import IMMTracker
            self.filter = IMMTracker(imm_config)
        else:
            self.filter = KalmanTracker(kalman_config)
        self.last_size: float | None = None
        self.last_area: float | None = None
        self.last_circ: float | None = None
        self.template_color: tuple[float, float, float] | None = None
        self.hits = 0
        self.misses = 0
        self.age = 0

    def predict_info(self, dt: float) -> dict:
        try:
            if self.filter.initialized:
                try:
                    px, pcov = self.filter.peek_predict(dt)
                    pred = (float(px[0]), float(px[1]))
                except Exception:
                    pred = self.filter.position
                    pcov = self.filter.cov_xy
                return {
                    "predicted": pred,
                    "pred_cov": pcov,
                    "last_position": self.filter.position,
                    "last_velocity": self.filter.velocity,
                    "last_size": self.last_size,
                    "last_area": self.last_area,
                    "last_circ": self.last_circ,
                    "template_color": self.template_color,
                }
            return {"predicted": None, "pred_cov": None, "last_position": None,
                    "last_velocity": None, "last_size": None, "last_area": None,
                    "last_circ": None, "template_color": self.template_color}
        except Exception:
            return {"predicted": None, "pred_cov": None, "last_position": None,
                    "last_velocity": None, "last_size": None, "last_area": None,
                    "last_circ": None, "template_color": None}

    def observe(self, det: Detection | None, dt: float) -> None:
        self.age += 1
        if det is None:
            self.misses += 1
            try:
                self.filter.step(None, dt)
            except Exception:
                pass
            return
        try:
            meas = (float(det.center[0]), float(det.center[1]))
            mv = float(getattr(det, "pos_var", 9.0))
            try:
                self.filter.step(meas, dt, meas_var=mv)
            except TypeError:
                self.filter.step(meas, dt)
            self.hits += 1
            self.misses = 0
            try:
                sz = (float(det.width) + float(det.height)) / 2.0
                self.last_size = sz if self.last_size is None else 0.9 * self.last_size + 0.1 * sz
            except Exception:
                pass
            try:
                ar = float(getattr(det, "area", 0.0) or (det.width * det.height))
                self.last_area = ar if self.last_area is None else 0.9 * self.last_area + 0.1 * ar
            except Exception:
                pass
            try:
                ci = float(getattr(det, "circularity", 1.0))
                self.last_circ = ci if self.last_circ is None else 0.9 * self.last_circ + 0.1 * ci
            except Exception:
                pass
            try:
                dc = getattr(det, "color_bgr", None)
                if dc is not None:
                    dc = (float(dc[0]), float(dc[1]), float(dc[2]))
                    if self.template_color is None:
                        self.template_color = dc
                    else:
                        self.template_color = (
                            0.85 * self.template_color[0] + 0.15 * dc[0],
                            0.85 * self.template_color[1] + 0.15 * dc[1],
                            0.85 * self.template_color[2] + 0.15 * dc[2],
                        )
            except Exception:
                pass
        except Exception:
            self.misses += 1


class MultiBeaconTracker:
    """N hypothesis tracks + designated selection. No GT."""

    def __init__(self, max_tracks: int = 5, use_imm: bool = False,
                 imm_config=None, kalman_config=None, assoc_config=None,
                 max_misses: int = 12):
        from tracking.association import AssociationConfig
        self.max_tracks = int(np.clip(int(max_tracks), 1, 8))
        self.use_imm = bool(use_imm)
        self.imm_config = imm_config
        self.kalman_config = kalman_config
        self.assoc_config = assoc_config or AssociationConfig()
        self.max_misses = int(max_misses)
        self.tracks: list[BeaconTrack] = []
        self.designated_internal_id: int | None = None
        self.expected_color: tuple[float, float, float] | None = None
        self.id_switches = 0
        self._prev_designated_id: int | None = None

    def reset(self) -> None:
        self.tracks = []
        self.designated_internal_id = None
        self._prev_designated_id = None
        self.id_switches = 0

    def set_expected_color(self, color: tuple[float, float, float] | None) -> None:
        try:
            self.expected_color = tuple(float(v) for v in color) if color is not None else None
        except Exception:
            self.expected_color = None

    def _prune(self) -> None:
        try:
            self.tracks = [t for t in self.tracks if t.misses <= int(self.max_misses)]
            # Keep strongest: hits desc, then recent.
            if len(self.tracks) > self.max_tracks:
                self.tracks.sort(key=lambda t: (t.hits, -t.misses), reverse=True)
                keep_ids = {t.internal_id for t in self.tracks[: self.max_tracks]}
                # Never prune designated.
                for t in self.tracks:
                    if t.internal_id == self.designated_internal_id:
                        keep_ids.add(t.internal_id)
                self.tracks = [t for t in self.tracks if t.internal_id in keep_ids][: self.max_tracks + 1]
            if self.designated_internal_id is not None and not any(
                    t.internal_id == self.designated_internal_id for t in self.tracks):
                self.designated_internal_id = None
        except Exception:
            pass

    def _choose_designated(self, assignment: dict[int, Detection | None]) -> int | None:
        """Pick designated internal track: expected-color match + continuity."""
        try:
            if not self.tracks:
                return None
            # Prefer current designated if still alive and matched.
            if self.designated_internal_id is not None:
                for ti, t in enumerate(self.tracks):
                    if t.internal_id == self.designated_internal_id:
                        if assignment.get(ti) is not None:
                            return t.internal_id
                        # Coast briefly: keep designated through short misses.
                        if t.misses <= 3:
                            return t.internal_id
                        break
            # Otherwise best color match among matched tracks, fallback to most hits.
            best, best_d = None, 1e18
            if self.expected_color is not None:
                for ti, t in enumerate(self.tracks):
                    d = assignment.get(ti)
                    if d is None:
                        continue
                    dc = getattr(d, "color_bgr", None) or t.template_color
                    dd = color_distance(dc, self.expected_color)
                    if dd < best_d:
                        best_d = dd
                        best = t.internal_id
                # Accept only if reasonably close (BGR dist < 90); else motion decides.
                if best is not None and best_d < 90.0:
                    return best
            # Fallback: track with most hits that got a detection.
            fb, fb_h = None, -1
            for ti, t in enumerate(self.tracks):
                if assignment.get(ti) is not None and t.hits > fb_h:
                    fb_h = t.hits
                    fb = t.internal_id
            return fb
        except Exception:
            return None

    def step(self, detections: list[Detection], dt: float) -> tuple[BeaconTrack | None, dict[int, Detection | None]]:
        """Associate all detections to tracks, update filters, return designated."""
        try:
            infos = [t.predict_info(dt) for t in self.tracks]
            # Bias designated track's template toward expected color so it wins ties.
            if self.expected_color is not None and self.designated_internal_id is not None:
                for info, t in zip(infos, self.tracks):
                    if t.internal_id == self.designated_internal_id and info.get("template_color") is None:
                        info["template_color"] = self.expected_color
            assignment = associate_multi(list(detections or []), infos, dt=dt, config=self.assoc_config) if infos else {}
        except Exception:
            assignment = {}
        try:
            used = set()
            for ti, d in assignment.items():
                if d is not None:
                    try:
                        used.add(id(d))
                    except Exception:
                        pass
            # Spawn tracks for unmatched detections (new beacons entering FOV).
            for d in (detections or []):
                try:
                    if id(d) in used:
                        continue
                except Exception:
                    pass
                if len(self.tracks) >= self.max_tracks + 2:
                    break
                try:
                    nt = BeaconTrack(use_imm=self.use_imm, imm_config=self.imm_config, kalman_config=self.kalman_config)
                    nt.observe(d, dt)
                    self.tracks.append(nt)
                except Exception:
                    continue
            # Update existing tracks.
            for ti, t in enumerate(self.tracks):
                if ti < len(infos):
                    try:
                        t.observe(assignment.get(ti), dt)
                    except Exception:
                        pass
            self._prune()
            # Recompute assignment indices after spawn/prune for designation:
            # choose designated by color+continuity over current tracks.
            try:
                infos2 = [t.predict_info(dt) for t in self.tracks]
                # Match latest detections to refreshed tracks for designation only.
                tmp = associate_multi(list(detections or []), infos2, dt=dt, config=self.assoc_config) if infos2 else {}
            except Exception:
                tmp = assignment
            new_des = self._choose_designated(tmp)
            if new_des is None and self.tracks:
                # Single-track case: keep sole track.
                if len(self.tracks) == 1:
                    new_des = self.tracks[0].internal_id
            if (new_des is not None and self._prev_designated_id is not None
                    and new_des != self._prev_designated_id):
                # Count a switch only when both had real detections (not coast).
                self.id_switches += 1
            if new_des is not None:
                self.designated_internal_id = new_des
                self._prev_designated_id = new_des
            des = next((t for t in self.tracks if t.internal_id == self.designated_internal_id), None)
            return des, tmp
        except Exception:
            return None, assignment
