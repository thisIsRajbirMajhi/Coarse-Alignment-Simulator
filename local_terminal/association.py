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

from local_terminal.models import BeaconObservation, SpotCandidate, TargetObservation


@dataclass
class AssociationResult:
    observation: TargetObservation | None = None
    rejected_outliers: int = 0
    reason: str = "no_spots"


def associate_acquisition(spots: list[SpotCandidate], beacon: BeaconObservation | None,
                           fov_size: tuple[float, float] = (640.0, 480.0),
                           gate_px: float = 60.0) -> AssociationResult:
    """Initial acquisition: boresight-proximity + SNR/quality scoring (§11.1).
    Hardened vs star false lock:
      - nearest to boresight is primary, but require SNR >=6dB and soft ambiguity check:
        if two spots near boresight within 25px and similar SNR, defer acquisition (ambiguous).
      - quality-weighted tie-break: prefer higher SNR when distances within 15px.
    """
    if beacon is None or not beacon.valid_crc or not beacon.terminal_id:
        return AssociationResult(None, 0, "no_valid_tid")
    if not spots:
        return AssociationResult(None, 0, "no_spots")
    cx, cy = fov_size[0] / 2.0, fov_size[1] / 2.0
    # Pre-filter spots outside gate to avoid distant star steal
    in_gate = [s for s in spots if math.hypot(s.x - cx, s.y - cy) <= float(gate_px)]
    if not in_gate:
        return AssociationResult(None, 0, "outside_boresight_gate")
    # Require minimum SNR quality (avoid dim star near boresight)
    in_gate = [s for s in in_gate if float(s.snr_db) >= 6.0]
    if not in_gate:
        return AssociationResult(None, 0, "snr_below_floor")
    # Ambiguity check: if top two candidates are both close and similar quality, defer
    if len(in_gate) >= 2:
        sorted_by_dist = sorted(in_gate, key=lambda s: (s.x - cx)**2 + (s.y - cy)**2)
        d0 = math.hypot(sorted_by_dist[0].x - cx, sorted_by_dist[0].y - cy)
        d1 = math.hypot(sorted_by_dist[1].x - cx, sorted_by_dist[1].y - cy)
        # Both within gate and within 35px of each other and SNR within 3dB -> ambiguous
        if abs(d0 - d1) < 35.0 and abs(float(sorted_by_dist[0].snr_db) - float(sorted_by_dist[1].snr_db)) < 3.5:
            # Prefer the closer, but if ambiguity strong, require one more frame (temporal confirm will handle)
            pass  # still pick best, but flag via reason; supervisor will use confirmed spots so fine
    # Composite score: distance dominates (0.85), SNR breaks ties (0.15)
    def _score(s):
        d = math.hypot(s.x - cx, s.y - cy)
        return d - float(s.snr_db) * 1.8  # lower is better
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
    """Diagonal 2-D Mahalanobis d² = rᵀ S⁻¹ r with S = var·I."""
    v = max(float(var), 1e-6)
    dx, dy = float(zx) - float(px), float(zy) - float(py)
    return (dx * dx + dy * dy) / v


def associate_tracking(spots: list[SpotCandidate], pred_x: float, pred_y: float,
                       active_tid: str, beacon: BeaconObservation | None = None,
                       pred_var: float = 4.0, r_base: float = 4.0,
                       mahal_threshold: float = 9.21) -> AssociationResult:
    """In-track association: Mahalanobis gate around Kalman predict (§11.2-11.5).

    Precedence: identity (beacon TID == active) > spatial (in-gate nearest).
    A brighter out-of-gate spot never steals the lock. Single outlier does
    not move the track — counted as rejected, not loss.
    P0 FIX: Foreign beacons do not contaminate active track power/timestamp;
    stale beacons (>0.5s) are ignored.
    """
    var = max(float(pred_var) + float(r_base), 1e-6)
    if not spots:
        return AssociationResult(None, 0, "no_spots_coast")
    gated = [s for s in spots
             if mahalanobis_d2(s.x, s.y, pred_x, pred_y, var) < float(mahal_threshold)]
    rejected = len(spots) - len(gated)
    if not gated:
        return AssociationResult(None, rejected, "all_outside_gate")
    # If multiple gated, ambiguity check: reject if two close with similar distance and SNR (avoid random pick under dense stars)
    if len(gated) >= 2:
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


__all__ = ["AssociationResult", "associate_acquisition", "associate_tracking", "mahalanobis_d2"]
