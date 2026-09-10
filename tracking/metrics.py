# tracking/metrics — frame log + aggregate benchmark report (evaluation only)
#
# GT flows ONLY here, never into detector / tracker / controller.
# Two errors are tracked:
#   perception = estimate vs GT (how good is vision)
#   pointing   = GT vs boresight (how well is camera centered — the <=10px spec)

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass
class FrameRecord:
    timestamp: float
    frame_id: int
    gt_x: float | None  # GT in FOV px (None if outside FOV)
    gt_y: float | None
    gt_visible: bool
    detected_x: float | None
    detected_y: float | None
    detection_confidence: float | None
    estimated_x: float | None
    estimated_y: float | None
    estimated_vx: float | None
    estimated_vy: float | None
    # Control error: estimate vs boresight
    error_x: float | None
    error_y: float | None
    error_px: float | None
    # Pointing error: GT vs boresight (the acceptance metric)
    pointing_x: float | None
    pointing_y: float | None
    pointing_px: float | None
    # Perception error: estimate vs GT
    perception_px: float | None
    state: str
    latency_ms: float
    lock_quality: float | None = None
    detection_pos_var: float | None = None
    # Association supervision (§39.3): was this frame's detection->track
    # decision correct? None when no decision could be judged
    # (GT invisible or no candidates).
    assoc_correct: bool | None = None
    assoc_candidates: int = 0
    # Multi-beacon identity: internal track id holding the lock this frame.
    track_id: int | None = None
    designated_target_id: int | None = None


class MetricsLogger:
    """Collects per-frame records, aggregates to acceptance indicators."""

    # Plausibility radius for association judging: a candidate within this
    # distance of GT counts as the true beacon (§39.3).
    ASSOC_GT_RADIUS_PX = 50.0

    def __init__(self, fov_size: tuple[int, int] = (640, 480)):
        self.fov_w, self.fov_h = int(fov_size[0]), int(fov_size[1])
        self.bx, self.by = self.fov_w / 2.0, self.fov_h / 2.0
        self.records: list[FrameRecord] = []
        self._t0: float | None = None

    def reset(self) -> None:
        self.records.clear()
        self._t0 = None

    @staticmethod
    def _extract_centers(all_detections) -> list[tuple[float, float]]:
        """Normalise Detection | dict | tuple list to [(x,y)]. Never raises."""
        out: list[tuple[float, float]] = []
        try:
            if not all_detections:
                return out
            for d in all_detections:
                try:
                    if hasattr(d, "center"):
                        out.append((float(d.center[0]), float(d.center[1])))
                    elif isinstance(d, dict):
                        c = d.get("center", None)
                        if c is not None:
                            out.append((float(c[0]), float(c[1])))
                    elif isinstance(d, (list, tuple)) and len(d) >= 2:
                        out.append((float(d[0]), float(d[1])))
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def log(
        self,
        frame_id: int,
        gt_fov: tuple[float, float] | None,
        gt_visible: bool,
        detected_center: tuple[float, float] | None,
        detection_conf: float | None,
        estimate: tuple[float, float] | None,
        velocity: tuple[float, float] | None,
        state: str,
        latency_ms: float = 0.0,
        timestamp: float | None = None,
        lock_quality: float | None = None,
        detection_pos_var: float | None = None,
        all_detections=None,
        track_id: int | None = None,
        designated_target_id: int | None = None,
    ) -> FrameRecord:
        ts = float(timestamp if timestamp is not None else time.perf_counter())
        if self._t0 is None:
            self._t0 = ts
        gx, gy = (None, None)
        if gt_fov is not None:
            gx, gy = float(gt_fov[0]), float(gt_fov[1])
        dx, dy = (None, None)
        if detected_center is not None:
            dx, dy = float(detected_center[0]), float(detected_center[1])
        ex, ey = (None, None)
        vx, vy = (None, None)
        if estimate is not None:
            ex, ey = float(estimate[0]), float(estimate[1])
        if velocity is not None:
            vx, vy = float(velocity[0]), float(velocity[1])

        err_x = err_y = err_px = None
        if ex is not None:
            err_x, err_y = ex - self.bx, ey - self.by
            err_px = float(np.hypot(err_x, err_y))
        pt_x = pt_y = pt_px = None
        if gx is not None and gt_visible:
            pt_x, pt_y = gx - self.bx, gy - self.by
            pt_px = float(np.hypot(pt_x, pt_y))
        perc = None
        if ex is not None and gx is not None and gt_visible:
            perc = float(np.hypot(ex - gx, ey - gy))

        try:
            lq = float(lock_quality) if lock_quality is not None else None
        except Exception:
            lq = None
        try:
            pv = float(detection_pos_var) if detection_pos_var is not None else None
        except Exception:
            pv = None
        # Association accuracy judging (§39.3): Correct / Total, GT-only here.
        # Total = GT visible AND ≥1 candidate (association had a decision).
        # Correct = selected is the candidate nearest GT (no ID switch), or
        # correctly rejected (None) when every candidate is far from GT.
        assoc_correct: bool | None = None
        n_cands = 0
        try:
            centers = self._extract_centers(all_detections)
            # Fall back: if caller did not pass the full list but a selected
            # detection exists, count a single-candidate decision.
            if not centers and dx is not None:
                centers = [(dx, dy)] if dy is not None else []
            n_cands = len(centers)
            if bool(gt_visible) and gx is not None and gy is not None and n_cands > 0:
                dists = [float(np.hypot(cx - gx, cy - gy)) for cx, cy in centers]
                best = min(dists)
                rad = float(self.ASSOC_GT_RADIUS_PX)
                if dx is None or dy is None:
                    assoc_correct = bool(best > rad)  # correctly rejected all-false
                else:
                    d_sel = float(np.hypot(dx - gx, dy - gy))
                    if best > rad:
                        assoc_correct = False  # GT visible but we locked a false blob
                        # (selected exists yet nothing near GT -> wrong target)
                        # Note: if all far AND selected is None handled above.
                    else:
                        assoc_correct = bool(d_sel <= best + 1e-6)
            else:
                assoc_correct = None
        except Exception:
            assoc_correct = None
        try:
            tid = int(track_id) if track_id is not None else None
        except Exception:
            tid = None
        try:
            did = int(designated_target_id) if designated_target_id is not None else None
        except Exception:
            did = None
        rec = FrameRecord(
            timestamp=ts, frame_id=int(frame_id),
            gt_x=gx, gt_y=gy, gt_visible=bool(gt_visible),
            detected_x=dx, detected_y=dy, detection_confidence=detection_conf,
            estimated_x=ex, estimated_y=ey, estimated_vx=vx, estimated_vy=vy,
            error_x=err_x, error_y=err_y, error_px=err_px,
            pointing_x=pt_x, pointing_y=pt_y, pointing_px=pt_px,
            perception_px=perc, state=str(state), latency_ms=float(latency_ms),
            lock_quality=lq, detection_pos_var=pv,
            assoc_correct=assoc_correct, assoc_candidates=int(n_cands),
            track_id=tid, designated_target_id=did,
        )
        self.records.append(rec)
        return rec

    def id_switches(self) -> int:
        """Count designated-track identity changes (multi-beacon stability)."""
        try:
            n = 0
            prev = None
            for r in self.records:
                if r.track_id is None:
                    continue
                if prev is not None and int(r.track_id) != int(prev):
                    n += 1
                prev = int(r.track_id)
            return int(n)
        except Exception:
            return 0

    # -- aggregates ---------------------------------------------------------
    def reacquisition_times(self) -> list[float]:
        """All LOST(/REACQUIRING)->TRACKING durations (s). Empty if none."""
        times: list[float] = []
        try:
            lost_t: float | None = None
            for r in self.records:
                if r.state in ("lost", "reacquiring"):
                    if lost_t is None:
                        lost_t = float(r.timestamp)
                elif r.state == "tracking":
                    if lost_t is not None:
                        times.append(float(r.timestamp) - lost_t)
                        lost_t = None
        except Exception:
            pass
        return times

    def detection_stats(self, hitbox_radius: float = 14.0, center_radius: float = 2.0) -> dict:
        """Hitbox/center-hit aggregates from GT + selected detection.

        detection hit = GT visible, detection present, dist <= hitbox_radius.
        center hit    = same with dist <= center_radius (<=2px precise).
        Rates are over total logged frames (dashboard definition).
        Times use mean frame dt from record timestamps.
        """
        try:
            n = len(self.records)
            if n == 0:
                return {"detection_count": 0, "detection_rate_pct": None,
                        "detection_time_s": None, "center_hit_count": 0,
                        "center_hit_rate_pct": None, "center_hit_time_s": None,
                        "searching_count": 0, "searching_rate_pct": None,
                        "searching_time_s": None}
            hb = max(1.0, float(hitbox_radius))
            cr = max(0.5, float(center_radius))
            det = 0
            cen = 0
            sea = 0
            for r in self.records:
                try:
                    if str(r.state) == "searching":
                        sea += 1
                    if (r.gt_visible and r.gt_x is not None and r.gt_y is not None
                            and r.detected_x is not None and r.detected_y is not None):
                        d = float(np.hypot(float(r.detected_x) - float(r.gt_x),
                                           float(r.detected_y) - float(r.gt_y)))
                        if d <= hb:
                            det += 1
                        if d <= cr:
                            cen += 1
                except Exception:
                    continue
            try:
                elapsed = float(self.records[-1].timestamp - self.records[0].timestamp) if n > 1 else 0.0
                dt_mean = (elapsed / max(n - 1, 1)) if elapsed > 1e-9 else 1.0 / 30.0
            except Exception:
                dt_mean = 1.0 / 30.0
            return {
                "detection_count": int(det),
                "detection_rate_pct": round(100.0 * det / max(n, 1), 2),
                "detection_time_s": round(float(det * dt_mean), 3),
                "center_hit_count": int(cen),
                "center_hit_rate_pct": round(100.0 * cen / max(n, 1), 2),
                "center_hit_time_s": round(float(cen * dt_mean), 3),
                "searching_count": int(sea),
                "searching_rate_pct": round(100.0 * sea / max(n, 1), 2),
                "searching_time_s": round(float(sea * dt_mean), 3),
            }
        except Exception:
            return {"detection_count": 0, "detection_rate_pct": 0.0,
                    "detection_time_s": 0.0, "center_hit_count": 0,
                    "center_hit_rate_pct": 0.0, "center_hit_time_s": 0.0,
                    "searching_count": 0, "searching_rate_pct": 0.0,
                    "searching_time_s": 0.0}

    def summary(self, hitbox_radius: float = 14.0, center_radius: float = 2.0) -> dict:
        n = len(self.records)
        if n == 0:
            return {"frames": 0}
        states = [r.state for r in self.records]
        n_track = sum(1 for s in states if s == "tracking")
        n_lost = sum(1 for s in states if s in ("lost", "reacquiring"))
        # Timing from state transitions
        acq = self._first_transition_time("searching", "tracking")
        reacq = self._first_transition_time("lost", "tracking") if n_lost > 0 else None
        pt = np.array([r.pointing_px for r in self.records if r.pointing_px is not None], dtype=float)
        perc = np.array([r.perception_px for r in self.records if r.perception_px is not None], dtype=float)
        lat = np.array([r.latency_ms for r in self.records], dtype=float)
        elapsed = (self.records[-1].timestamp - self.records[0].timestamp) if n > 1 else 0.0
        fps = (n - 1) / elapsed if elapsed > 1e-6 else 0.0

        def _stats(a: np.ndarray) -> dict:
            if a.size == 0:
                return {"mean": None, "max": None, "p95": None, "rmse": None, "count": 0}
            return {
                "mean": float(np.mean(a)),
                "max": float(np.max(a)),
                "p95": float(np.percentile(a, 95)),
                "rmse": float(np.sqrt(np.mean(a**2))),
                "count": int(a.size),
            }

        # Robustness extensions (all GT-isolated aggregates, backward compatible):
        n_vis = sum(1 for r in self.records if r.gt_visible)
        n_det = sum(1 for r in self.records if r.detected_x is not None)
        n_det_vis = sum(1 for r in self.records if r.gt_visible and r.detected_x is not None)
        detection_recall = (n_det_vis / n_vis) if n_vis else None
        # Reacq stats: count lost->tracking transitions + successes
        n_reacq_events = 0
        prev = None
        longest_track = 0
        cur_track = 0
        for r in self.records:
            if r.state == "tracking":
                cur_track += 1
                longest_track = max(longest_track, cur_track)
                if prev in ("lost", "reacquiring"):
                    n_reacq_events += 1
            else:
                cur_track = 0
            prev = r.state
        # Count TRACK->LOST transitions (not LOST-entry repeats) so
        # reacq_success_rate denominator matches actual losses.
        n_losses = sum(1 for i, r in enumerate(self.records)
                       if r.state == "lost" and i > 0 and self.records[i - 1].state == "tracking")
        if n_losses == 0:
            n_losses = sum(1 for i, r in enumerate(self.records)
                           if r.state == "lost" and (i == 0 or self.records[i - 1].state != "lost"))
        reacq_rate = (n_reacq_events / n_losses) if n_losses else None
        lq_arr = np.array([r.lock_quality for r in self.records if r.lock_quality is not None], dtype=float)
        # Normalized perception (NEES-like): err^2 / pos_var when available
        normed = []
        for r in self.records:
            if r.perception_px is not None and r.detection_pos_var:
                try:
                    normed.append((r.perception_px ** 2) / max(1.0, float(r.detection_pos_var)))
                except Exception:
                    pass
        normed = np.array(normed, dtype=float)
        # Association accuracy (§39.3): Correct / Total over judged decisions.
        assoc_judged = [r for r in self.records if r.assoc_correct is not None]
        n_assoc_total = len(assoc_judged)
        n_assoc_correct = sum(1 for r in assoc_judged if r.assoc_correct)
        assoc_acc = (n_assoc_correct / n_assoc_total) if n_assoc_total else None
        # Re-acquisition distribution (all events, not just first).
        reacq_times = self.reacquisition_times()
        if reacq_times:
            reacq_avg = float(sum(reacq_times) / len(reacq_times))
            reacq_min = float(min(reacq_times))
            reacq_max = float(max(reacq_times))
        else:
            reacq_avg = reacq_min = reacq_max = None
        # Detection / center-hit / searching aggregates (dashboard section E).
        try:
            det_stats = self.detection_stats(hitbox_radius=hitbox_radius, center_radius=center_radius)
        except Exception:
            det_stats = {}
        return {
            "frames": n,
            "elapsed_s": round(float(elapsed), 3),
            "fps": round(float(fps), 2),
            "lock_retention_pct": round(100.0 * n_track / n, 2),
            "target_loss_pct": round(100.0 * n_lost / n, 2),
            "tracking_frames": n_track,
            "acquisition_time_s": None if acq is None else round(float(acq), 3),
            "reacquisition_time_s": None if reacq is None else round(float(reacq), 3),
            "pointing_px": _stats(pt),  # GT vs boresight — acceptance metric
            "perception_px": _stats(perc),  # estimate vs GT — vision accuracy
            "latency_ms": {
                "mean": round(float(np.mean(lat)), 2) if lat.size else None,
                "p95": round(float(np.percentile(lat, 95)), 2) if lat.size else None,
            },
            "accept_pointing_le_10px": bool(pt.size and float(np.mean(pt[-20:])) <= 10.0) if pt.size >= 20 else None,
            "accept_pointing_p95_le_15px": bool(pt.size and float(np.percentile(pt[-100:] if pt.size >= 100 else pt, 95)) <= 15.0) if pt.size >= 20 else None,
            "accept_pointing_max_le_25px": bool(pt.size and float(np.max(pt[-100:] if pt.size >= 100 else pt)) <= 25.0) if pt.size >= 20 else None,
            "detection_recall_vis": round(float(detection_recall), 4) if detection_recall is not None else None,
            "association_accuracy": round(float(assoc_acc), 4) if assoc_acc is not None else None,
            "association_decisions": int(n_assoc_total),
            "association_correct": int(n_assoc_correct),
            "reacq_events": int(n_reacq_events),
            "loss_events": int(n_losses),
            "reacq_success_rate": round(float(reacq_rate), 4) if reacq_rate is not None else None,
            "id_switches": int(self.id_switches()),
            "reacq_times_s": [round(float(t), 3) for t in reacq_times],
            "avg_reacquisition_time_s": None if reacq_avg is None else round(reacq_avg, 3),
            "min_reacquisition_time_s": None if reacq_min is None else round(reacq_min, 3),
            "max_reacquisition_time_s": None if reacq_max is None else round(reacq_max, 3),
            "detection_count": int(det_stats.get("detection_count", 0)),
            "detection_rate_pct": det_stats.get("detection_rate_pct"),
            "detection_time_s": det_stats.get("detection_time_s"),
            "center_hit_count": int(det_stats.get("center_hit_count", 0)),
            "center_hit_rate_pct": det_stats.get("center_hit_rate_pct"),
            "center_hit_time_s": det_stats.get("center_hit_time_s"),
            "searching_count": int(det_stats.get("searching_count", 0)),
            "searching_rate_pct": det_stats.get("searching_rate_pct"),
            "searching_time_s": det_stats.get("searching_time_s"),
            "longest_track_streak": int(longest_track),
            "lock_quality_mean": round(float(np.mean(lq_arr)), 4) if lq_arr.size else None,
            "perception_nees_mean": round(float(np.mean(normed)), 4) if normed.size else None,
        }

    def _first_transition_time(self, frm: str, to: str) -> float | None:
        # Time from first entry of `frm` (or start if already past it) to next `to`.
        # Handles runs that start already in DETECTED (visible first frame).
        t_frm: float | None = None
        for r in self.records:
            if t_frm is None and r.state == frm:
                t_frm = r.timestamp
            if t_frm is not None and r.state == to and r.timestamp >= t_frm:
                return r.timestamp - t_frm
        # If never saw `frm` but saw `to`, measure from run start (acquired almost instantly)
        states = [r.state for r in self.records]
        if t_frm is None and to in states:
            return self.records[states.index(to)].timestamp - self.records[0].timestamp
        # Fallback for reacq: lost -> tracking
        if frm == "lost":
            t_lost: float | None = None
            for r in self.records:
                if r.state == "lost" and t_lost is None:
                    t_lost = r.timestamp
                if t_lost is not None and r.state == "tracking":
                    return r.timestamp - t_lost
        return None

    # -- persistence ---------------------------------------------------------
    def save_csv(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(self.records[0]).keys()) if self.records else [])
            if self.records:
                w.writeheader()
                for r in self.records:
                    w.writerow(asdict(r))
        return str(path)

    def save_summary(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.summary(), f, indent=2)
        return str(path)
