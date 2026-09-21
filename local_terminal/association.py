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
    """Initial acquisition: nearest spot to boresight + valid TID (§11.1)."""
    if beacon is None or not beacon.valid_crc or not beacon.terminal_id:
        return AssociationResult(None, 0, "no_valid_tid")
    if not spots:
        return AssociationResult(None, 0, "no_spots")
    cx, cy = fov_size[0] / 2.0, fov_size[1] / 2.0
    best = min(spots, key=lambda s: (s.x - cx) ** 2 + (s.y - cy) ** 2)
    dist = math.hypot(best.x - cx, best.y - cy)
    if dist > float(gate_px):
        return AssociationResult(None, 0, "outside_boresight_gate")
    obs = TargetObservation(
        terminal_id=str(beacon.terminal_id),
        fov_x=float(best.x), fov_y=float(best.y),
        p_rx_w=float(beacon.p_rx_w), snr_db=float(best.snr_db),
        timestamp_s=float(beacon.timestamp_s),
    ).validate()
    return AssociationResult(obs, 0, "acquired")


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
    """
    var = max(float(pred_var) + float(r_base), 1e-6)
    if not spots:
        return AssociationResult(None, 0, "no_spots_coast")
    gated = [s for s in spots
             if mahalanobis_d2(s.x, s.y, pred_x, pred_y, var) < float(mahal_threshold)]
    rejected = len(spots) - len(gated)
    if not gated:
        return AssociationResult(None, rejected, "all_outside_gate")
    # Identity precedence: if beacon confirms a *different* TID, do not
    # reassign — hold spatial pick for active target, record rejection.
    if beacon is not None and beacon.valid_crc and beacon.terminal_id \
            and str(beacon.terminal_id) != str(active_tid):
        rejected += 1  # foreign TID noted, not accepted
    best = min(gated, key=lambda s: mahalanobis_d2(s.x, s.y, pred_x, pred_y, var))
    p_rx = float(beacon.p_rx_w) if beacon is not None else 0.0
    ts = float(beacon.timestamp_s) if beacon is not None else 0.0
    obs = TargetObservation(
        terminal_id=str(active_tid),
        fov_x=float(best.x), fov_y=float(best.y),
        p_rx_w=p_rx, snr_db=float(best.snr_db),
        timestamp_s=ts,
    ).validate()
    return AssociationResult(obs, rejected, "tracked")


__all__ = ["AssociationResult", "associate_acquisition", "associate_tracking", "mahalanobis_d2"]
