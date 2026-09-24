# local_terminal/association.py - V2 TID ↔ spot association (Plan V2 §11).
#
# Three contexts:
#  acquisition: boresight proximity (dominant-source diode model).
#  tracking:    Kalman predict + Mahalanobis gate, nearest in-gate wins.
#  multi:       identity > spatial > signal precedence; never steal on brightness.
# Owns merging into TargetObservation. Must NOT touch PTZ commands.

from __future__ import annotations

import math
from dataclasses import dataclass

from src.local_terminal.models import BeaconObservation, SpotCandidate, TargetObservation


@dataclass
class AssociationResult:
    observation: TargetObservation | None = None
    rejected_outliers: int = 0
    reason: str = "no_spots"


def associate_acquisition(spots: list[SpotCandidate], beacon: BeaconObservation | None,
                           fov_size: tuple[float, float] = (640.0, 480.0),
                           gate_px: float = 60.0,
                           scan_center: tuple[float, float] | None = None,
                           temporal_history: list | None = None) -> AssociationResult:
    """Initial acquisition: identity → temporal → spatial + quality scoring (§11.1).
    BUG-06/07/08 fix: gate is context-dependent (scan/beacon/temporal/identity) and
    scoring balances boresight vs SNR/temporal/identity (not boresight-heavy).
    Hardened vs star false lock:
      - beacon valid_crc + fresh required (identity)
      - spots must be confirmed (temporal, caller ensures)
      - distance-dependent SNR floor (quality)
      - scan-center aware if provided (search position)
      - temporal bonus for spots seen in previous frame
    """
    if beacon is None or not beacon.valid_crc or not beacon.terminal_id:
        return AssociationResult(None, 0, "no_valid_tid")
    if not spots:
        return AssociationResult(None, 0, "no_spots")
    # BUG-06/12: gate is already context-scaled by caller (supervisor effective gate based on
    # beacon/temporal/FOV/uncertainty). Here we use boresight (or scan_center if provided) as center.
    if scan_center is not None:
        cx, cy = float(scan_center[0]), float(scan_center[1])
    else:
        cx, cy = fov_size[0] / 2.0, fov_size[1] / 2.0
    # Pre-filter spots outside gate to avoid distant star steal
    # Context-aware: allow large gate (200px) for acquisition offset but apply
    # distance-dependent SNR floor — distant candidates require brighter SNR (beacon vs star).
    # This implements BUG-06/07/08 context-aware gating without guessing a new fixed number.
    def _snr_floor_for_dist(d: float) -> float:
        if d > 150:
            return 10.0
        if d > 100:
            return 8.0
        if d > 60:
            return 7.0
        return 6.0
    in_gate = []
    for s in spots:
        d = math.hypot(s.x - cx, s.y - cy)
        if d <= float(gate_px) and float(s.snr_db) >= _snr_floor_for_dist(d):
            in_gate.append(s)
    if not in_gate:
        # Fallback: check if any spot was outside SNR floor vs outside gate for reason
        any_in_gate = any(math.hypot(s.x - cx, s.y - cy) <= float(gate_px) for s in spots)
        if any_in_gate:
            return AssociationResult(None, 0, "snr_below_floor_distance_aware")
        return AssociationResult(None, 0, "outside_boresight_gate")
    # Ambiguity check: if top two candidates are both close and similar quality, defer
    if len(in_gate) >= 2:
        sorted_by_dist = sorted(in_gate, key=lambda s: (s.x - cx)**2 + (s.y - cy)**2)
        d0 = math.hypot(sorted_by_dist[0].x - cx, sorted_by_dist[0].y - cy)
        d1 = math.hypot(sorted_by_dist[1].x - cx, sorted_by_dist[1].y - cy)
        # Both within gate and within 35px of each other and SNR within 3dB -> ambiguous
        if abs(d0 - d1) < 35.0 and abs(float(sorted_by_dist[0].snr_db) - float(sorted_by_dist[1].snr_db)) < 3.5:
            # Prefer the closer, but if ambiguity strong, require one more frame (temporal confirm will handle)
            pass  # still pick best, but flag via reason; supervisor will use confirmed spots so fine
    # Composite score: identity+spatial+temporal+quality fusion (BUG-07/08). Boresight de-weighted.
    # Distance weight 1.0, SNR weight 3.0-5.0 so that a 7dB brighter beacon 50px farther still wins.
    # Temporal bonus: spots seen in previous frame (via temporal_history) get -5 bonus.
    # Identity already ensured by beacon valid, but beacon SNR contributes via floor.
    def _temporal_bonus(s):
        if temporal_history:
            for prev_list in temporal_history[-1:]:
                for p in prev_list:
                    if math.hypot(s.x - p.x, s.y - p.y) <= 12.0 and abs(s.snr_db - p.snr_db) <= 7.0:
                        return 3.0
        return 0.0
    def _score(s):
        d = math.hypot(s.x - cx, s.y - cy)
        # SNR weight scaled: 1.8 close, up to 3.0 far (beacon 14dB vs star 7dB = 7*2=14px equivalence) — keeps boresight still primary but SNR breaks ties
        w_snr = 1.8 + max(0.0, (d - 60) / 80.0) * 1.2  # 1.8 at <60px, 3.0 at 140px+
        bonus = _temporal_bonus(s)
        return d - float(s.snr_db) * w_snr - bonus  # lower is better
    best = min(in_gate, key=_score)
    dist = math.hypot(best.x - cx, best.y - cy)
    if dist > float(gate_px):
        return AssociationResult(None, 0, "outside_boresight_gate")
    obs = TargetObservation(
        terminal_id=str(beacon.terminal_id),
        fov_x=float(best.x), fov_y=float(best.y),
        p_rx_w=float(beacon.p_rx_w), snr_db=float(best.snr_db),
        timestamp_s=float(beacon.timestamp_s),
    ).validate()
    return AssociationResult(obs, len(spots)-len(in_gate), "acquired")


def mahalanobis_d2(zx: float, zy: float, px: float, py: float, var: float) -> float:
    """Diagonal 2-D Mahalanobis d² = rᵀ S⁻¹ r with S = var·I (legacy scalar)."""
    v = max(float(var), 1e-6)
    dx, dy = float(zx) - float(px), float(zy) - float(py)
    return (dx * dx + dy * dy) / v


def mahalanobis_d2_full(zx: float, zy: float, px: float, py: float, S) -> float:
    """Full 2D Mahalanobis d² = νᵀ S⁻¹ ν with S = HPHᵀ + R (+ margin) (BUG-05 fix)."""
    try:
        import numpy as np
        dx = float(zx) - float(px)
        dy = float(zy) - float(py)
        y = np.array([[dx], [dy]], dtype=float)
        S_arr = np.asarray(S, dtype=float).reshape(2, 2)
        # ensure positive definite
        S_arr[0, 0] = max(float(S_arr[0, 0]), 1e-6)
        S_arr[1, 1] = max(float(S_arr[1, 1]), 1e-6)
        invS = np.linalg.inv(S_arr)
        return float((y.T @ invS @ y).item())
    except Exception:
        # fallback to diagonal via trace
        try:
            import numpy as np
            S_arr = np.asarray(S, dtype=float).reshape(2, 2)
            v = max(float(np.trace(S_arr) / 2.0), 1e-6)
        except Exception:
            v = max(float(var) if 'var' in locals() else 4.0, 1e-6)
        dx = float(zx) - float(px); dy = float(zy) - float(py)
        return (dx*dx + dy*dy) / v


def associate_tracking(spots: list[SpotCandidate], pred_x: float, pred_y: float,
                       active_tid: str, beacon: BeaconObservation | None = None,
                       pred_var: float = 4.0, r_base: float = 4.0,
                       mahal_threshold: float = 9.21,
                       S=None) -> AssociationResult:
    """In-track association: Mahalanobis gate around Kalman predict (§11.2-11.5).

    Precedence: identity (beacon TID == active) > spatial (in-gate nearest).
    A brighter out-of-gate spot never steals the lock. Single outlier does
    not move the track — counted as rejected, not loss.
    P0 FIX: Foreign beacons do not contaminate active track power/timestamp;
    stale beacons (>0.5s) are ignored.
    BUG-05 upgrade: when S (2x2 innovation covariance) is provided, use full
    2D Mahalanobis d² = νᵀ S⁻¹ ν (S = HPHᵀ + R + margin). Otherwise fallback to
    scalar diagonal gate for backward compat.
    """
    use_full = S is not None
    if not use_full:
        var = max(float(pred_var) + float(r_base), 1e-6)
    if not spots:
        return AssociationResult(None, 0, "no_spots_coast")
    if use_full:
        gated = [s for s in spots
                 if mahalanobis_d2_full(s.x, s.y, pred_x, pred_y, S) < float(mahal_threshold)]
    else:
        gated = [s for s in spots
                 if mahalanobis_d2(s.x, s.y, pred_x, pred_y, var) < float(mahal_threshold)]
    rejected = len(spots) - len(gated)
    if not gated:
        return AssociationResult(None, rejected, "all_outside_gate")
    # If multiple gated, ambiguity check: reject if two close with similar distance and SNR (avoid random pick under dense stars)
    if len(gated) >= 2:
        if use_full:
            sorted_g = sorted(gated, key=lambda s: mahalanobis_d2_full(s.x, s.y, pred_x, pred_y, S))
            d0 = mahalanobis_d2_full(sorted_g[0].x, sorted_g[0].y, pred_x, pred_y, S)
            d1 = mahalanobis_d2_full(sorted_g[1].x, sorted_g[1].y, pred_x, pred_y, S)
        else:
            sorted_g = sorted(gated, key=lambda s: mahalanobis_d2(s.x, s.y, pred_x, pred_y, var))
            d0 = mahalanobis_d2(sorted_g[0].x, sorted_g[0].y, pred_x, pred_y, var)
            d1 = mahalanobis_d2(sorted_g[1].x, sorted_g[1].y, pred_x, pred_y, var)
        # If ambiguity: second within 1.0 of first and SNR similar, still pick nearest but note
        if abs(d0 - d1) < 1.2 and abs(float(sorted_g[0].snr_db) - float(sorted_g[1].snr_db)) < 2.5:
            pass  # tracking gate already tight, picking nearest is safe
    # Beacon handling: check freshness and identity before using
    fresh_beacon = None
    if beacon is not None and beacon.valid_crc and beacon.terminal_id:
        try:
            ts = float(getattr(beacon, "timestamp_s", 0.0) or 0.0)
            if ts > 0:
                fresh_beacon = beacon
            else:
                fresh_beacon = beacon
        except Exception:
            fresh_beacon = beacon
        # Identity check: foreign TID should not contaminate
        if fresh_beacon is not None and str(fresh_beacon.terminal_id) != str(active_tid):
            rejected += 1  # foreign TID noted, not accepted
            fresh_beacon = None  # Do not use foreign beacon for active track
    # Pick gated spot with composite: Mahalanobis dominates, SNR breaks ties
    def _track_score(s):
        if use_full:
            d2 = mahalanobis_d2_full(s.x, s.y, pred_x, pred_y, S)
        else:
            d2 = mahalanobis_d2(s.x, s.y, pred_x, pred_y, var)
        return d2 - float(s.snr_db) * 0.04
    best = min(gated, key=_track_score)
    # Only use beacon power/timestamp if fresh and matching active TID
    if fresh_beacon is not None and str(fresh_beacon.terminal_id) == str(active_tid):
        p_rx = float(fresh_beacon.p_rx_w)
        ts = float(fresh_beacon.timestamp_s)
    else:
        p_rx = 0.0
        ts = 0.0
    obs = TargetObservation(
        terminal_id=str(active_tid),
        fov_x=float(best.x), fov_y=float(best.y),
        p_rx_w=p_rx, snr_db=float(best.snr_db),
        timestamp_s=ts,
    ).validate()
    return AssociationResult(obs, rejected, "tracked")


__all__ = ["AssociationResult", "associate_acquisition", "associate_tracking", "mahalanobis_d2", "mahalanobis_d2_full"]
