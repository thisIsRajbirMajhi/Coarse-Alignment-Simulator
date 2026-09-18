# local_terminal/association.py - Module 4: Candidate Association Manager (§10).
from __future__ import annotations

import math

from local_terminal.models import CandidateTrack, DetectionCandidate
from local_terminal.states import CandidateState

# Dead tracks never absorb detections (§27): a reappearing source gets a
# fresh BEACON-N id unless reacquisition validation explicitly merges it.
_DEAD = (CandidateState.LOST, CandidateState.EXPIRED, CandidateState.REJECTED)


class CandidateAssociationManager:
    """Associate DetectionCandidate[] to CandidateTrack[] with gating.

    Uses spatial distance + predicted position + velocity + size/signal +
    spectral consistency — never nearest-pixel alone. Maintains predicted
    state.

    Matching is TRACK-CENTRIC and confidence-ordered: live tracks claim
    their best detection in rank order (lifecycle, confidence, hits), so an
    orphan detection can never steal a high-confidence track from its true
    measurement under clutter. Leftover detections spawn fresh BEACON-N
    tracks. Deterministic (no dict-order dependence).
    """

    # Lifecycle rank shared with the overload cap (system.py): identified
    # tracks outrank tentative ones when competing for a measurement.
    _RANK = {
        "TRACKING": 9, "ACQUIRED": 8, "SELECTED": 7, "IDENTIFIED": 6,
        "REACQUIRING": 5, "DEGRADED": 4, "VALIDATING": 3, "TENTATIVE": 2,
        "SEEN": 1, "LOST": 0, "REJECTED": -1, "EXPIRED": -2,
    }

    def __init__(self, gate_px: float = 40.0, size_tol_px: float = 6.0,
                 snr_tol_db: float = 12.0):
        self.gate_px = float(gate_px)
        self.size_tol_px = float(size_tol_px)
        self.snr_tol_db = float(snr_tol_db)
        self._next_id = 1

    def reset_counter(self, start: int = 1) -> None:
        self._next_id = int(start)

    def _predict(self, track: CandidateTrack, dt: float) -> tuple[float, float]:
        dt = max(0.0, float(dt))
        return (track.est_x + track.est_vx * dt, track.est_y + track.est_vy * dt)

    def _track_spectral(self, track: CandidateTrack) -> float | None:
        """Voted spectral class from the track's own measured history."""
        try:
            feats = [float(f.get("spectral", 0.0)) for f in track.feature_history[-6:]
                     if isinstance(f, dict) and float(f.get("peak", 0.0)) > 0]
            if feats:
                s = sorted(feats)
                n = len(s)
                return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
        except Exception:
            pass
        return None

    def _cost(self, det: DetectionCandidate, track: CandidateTrack,
              pred: tuple[float, float]) -> float | None:
        """Association cost, or None when outside the spatial gate."""
        dist_pred = math.hypot(det.centroid_x - pred[0], det.centroid_y - pred[1])
        dist_meas = math.hypot(det.centroid_x - track.meas_x, det.centroid_y - track.meas_y)
        dist = min(dist_pred, dist_meas)
        gate = self.gate_px * 2.0 if track.lifecycle_state in (CandidateState.TRACKING, CandidateState.ACQUIRED) else self.gate_px
        if dist > gate:
            return None
        size_err = abs(det.apparent_diameter - track.meas_spot_px) / max(1.0, self.size_tol_px)
        snr_err = abs(det.local_snr - track.meas_snr) / max(1.0, self.snr_tol_db)
        cost = dist + 2.0 * min(size_err, 3.0) + 1.0 * min(snr_err, 3.0)
        # Spectral soft penalty (never a hard gate: dim frames can
        # mis-estimate hue, which must not split a true track — it only
        # breaks ties against a different-band impostor).
        try:
            det_wl = float(det.spectral_observation.estimated_center)
            ref_wl = self._track_spectral(track)
            if ref_wl is not None and abs(det_wl - ref_wl) > 300.0:
                cost += 10.0
        except Exception:
            pass
        return cost

    def _refresh(self, track: CandidateTrack, det: DetectionCandidate,
                 timestamp: float) -> None:
        track.meas_x, track.meas_y = det.centroid_x, det.centroid_y
        track.meas_intensity = det.peak_intensity
        track.meas_snr = det.local_snr
        track.meas_spot_px = det.apparent_diameter
        track.last_seen_timestamp = float(timestamp)
        track.hit_count += 1
        track.miss_count = 0
        track.touch(float(timestamp))
        track.temporal.timestamps.append(float(timestamp))
        track.temporal.intensity_history.append(float(det.peak_intensity))
        track.temporal.centroid_history.append((float(det.centroid_x), float(det.centroid_y)))
        # bounded buffers per Plans/New Upgrades.md §§10, 34 (> 2 full frame durations)
        del track.temporal.timestamps[:-1200]
        del track.temporal.intensity_history[:-1200]
        del track.temporal.centroid_history[:-1200]
        track.timestamps.append(float(timestamp))
        del track.timestamps[:-1200]
        track.feature_history.append({"snr": det.local_snr, "spot_px": det.apparent_diameter,
                                      "spectral": det.spectral_observation.estimated_center,
                                      "peak": det.peak_intensity})
        del track.feature_history[:-1200]

    def associate(self, detections: list[DetectionCandidate],
                  tracks: dict[str, CandidateTrack],
                  timestamp: float, dt: float) -> tuple[dict[str, CandidateTrack], list[CandidateTrack], list[CandidateTrack]]:
        """Returns (updated_tracks, new_tracks, unmatched_tracks)."""
        unmatched: list[CandidateTrack] = []
        new_tracks: list[CandidateTrack] = []
        # Predict live tracks forward (dead tracks are kept for telemetry
        # but never match).
        live = {tid: tr for tid, tr in tracks.items() if tr.lifecycle_state not in _DEAD}
        preds = {tid: self._predict(tr, dt) for tid, tr in live.items()}
        # Confidence-ordered track-centric claiming (deterministic).
        ordered = sorted(live.values(),
                         key=lambda t: (self._RANK.get(t.lifecycle_state.value, 0),
                                        float(t.confidence), int(t.hit_count),
                                        t.observation_id),
                         reverse=True)
        claimed_det: set[int] = set()
        matched_ids: set[str] = set()
        for tr in ordered:
            pred = preds.get(tr.observation_id, (tr.est_x, tr.est_y))
            best_di, best_cost = None, float("inf")
            for di, det in enumerate(detections):
                if di in claimed_det:
                    continue
                cost = self._cost(det, tr, pred)
                if cost is None:
                    continue
                if cost < best_cost:
                    best_di, best_cost = di, cost
            if best_di is not None:
                claimed_det.add(best_di)
                matched_ids.add(tr.observation_id)
                self._refresh(tr, detections[best_di], timestamp)
        # Leftover detections spawn fresh local observations with spectral
        # memory from birth (so the next frame can already penalize a
        # different-band impostor).
        for di, det in enumerate(detections):
            if di in claimed_det:
                continue
            tid = f"BEACON-{self._next_id}"
            self._next_id += 1
            tr = CandidateTrack(observation_id=tid)
            tr.meas_x, tr.meas_y = det.centroid_x, det.centroid_y
            tr.est_x, tr.est_y = det.centroid_x, det.centroid_y
            tr.meas_intensity = det.peak_intensity
            tr.meas_snr = det.local_snr
            tr.meas_spot_px = det.apparent_diameter
            tr.hit_count = 1
            tr.miss_count = 0
            tr.touch(float(timestamp))
            tr.temporal.timestamps = [float(timestamp)]
            tr.temporal.intensity_history = [float(det.peak_intensity)]
            tr.temporal.centroid_history = [(float(det.centroid_x), float(det.centroid_y))]
            tr.timestamps = [float(timestamp)]
            tr.feature_history = [{"snr": det.local_snr, "spot_px": det.apparent_diameter,
                                   "spectral": det.spectral_observation.estimated_center,
                                   "peak": det.peak_intensity}]
            new_tracks.append(tr)
            tracks[tid] = tr
        for tid, tr in tracks.items():
            if tid in matched_ids or any(t.observation_id == tid for t in new_tracks):
                continue
            # Not observed this frame
            unmatched.append(tr)
        return tracks, new_tracks, unmatched
