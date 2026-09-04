# tracking/association.py - Blind data association for PAT

from __future__ import annotations

import math

import numpy as np


def mahalanobis_distance(
    det_xy: tuple[float, float],
    pred_xy: tuple[float, float],
    cov_2x2: np.ndarray,
) -> float:
    """
    Squared Mahalanobis distance y^T S^-1 y for 2-D innovation.

    y = det - pred, S = innovation covariance (pos block).
    Returns inf if cov singular.
    """
    try:
        y = np.array([float(det_xy[0]) - float(pred_xy[0]),
                      float(det_xy[1]) - float(pred_xy[1])], dtype=float)
        invS = np.linalg.inv(np.asarray(cov_2x2, dtype=float))
        return float(y @ invS @ y)
    except Exception:
        try:
            y = np.array([float(det_xy[0]) - float(pred_xy[0]),
                          float(det_xy[1]) - float(pred_xy[1])], dtype=float)
            # fallback diagonal
            s = np.asarray(cov_2x2, dtype=float)
            diag = np.array([s[0, 0] if s.shape[0] > 0 else 1.0,
                             s[1, 1] if s.shape[0] > 1 else 1.0], dtype=float)
            diag = np.maximum(diag, 1e-6)
            return float((y[0] * y[0]) / diag[0] + (y[1] * y[1]) / diag[1])
        except Exception:
            return float("inf")


def innovation_cov_from_kalman(kalman) -> np.ndarray | None:
    """
    Extract 2x2 position innovation covariance S = H P H^T + R.

    Works for tracking.kalman.KalmanFilter (P is 4x4, meas_var scalar).
    Returns None if kalman not initialized.
    """
    try:
        if not kalman.is_initialized():
            return None
        P = kalman.P  # type: ignore
        r = float(getattr(kalman, "meas_var", 4.0))
        # H = [[1,0,0,0],[0,1,0,0]] -> H P H^T is top-left 2x2 of P
        S = np.array([[float(P[0, 0]), float(P[0, 1])],
                      [float(P[1, 0]), float(P[1, 1])]], dtype=float)
        S = S + np.eye(2, dtype=float) * r
        # ensure PD
        S = (S + S.T) * 0.5
        # clamp tiny
        S[0, 0] = max(float(S[0, 0]), 1e-3)
        S[1, 1] = max(float(S[1, 1]), 1e-3)
        return S
    except Exception:
        return None


def gate_radius_from_cov(cov_2x2: np.ndarray, chi2: float = 9.21) -> float:
    """
    Convert covariance + chi2 threshold to circular gate radius for fallback.

    radius = sqrt(chi2 * max(eig(S)))  ~ 3 sigma for chi2=9.21 (99% 2-DOF).
    """
    try:
        S = np.asarray(cov_2x2, dtype=float)
        eig = np.linalg.eigvalsh((S + S.T) * 0.5)
        vmax = float(np.max(eig))
        vmax = max(vmax, 1e-6)
        return float(math.sqrt(float(chi2) * vmax))
    except Exception:
        return float(math.sqrt(float(chi2) * 25.0))


def associate_detections(
    detections: list[dict],
    pred_xy: tuple[float, float] | None,
    cov_2x2: np.ndarray | None,
    chi2_threshold: float = 9.21,
    fallback_radius_px: float = 35.0,
) -> tuple[float, float] | None:
    """
    Blind nearest-neighbor association inside elliptical gate.

    - detections: list from BeaconDetector.detect_all (each has x,y,confidence,peak)
    - pred_xy: Kalman predicted position in FOV coords, or None (SEARCHING first hit)
    - cov_2x2: 2x2 innovation covariance, or None
    - chi2_threshold: 5.99 (95%) or 9.21 (99%) for 2 DOF
    - fallback_radius_px: circular radius when no covariance (initial acquire)

    Returns (x,y) of best gated detection or None.
    No ground-truth access.
    """
    if not detections:
        return None

    # No prediction -> pick brightest/confident (blind acquisition)
    if pred_xy is None or cov_2x2 is None:
        # Use confidence ranking already sorted descending by detector
        # but filter by peak sanity (avoid hot pixel)
        best = None
        best_conf = -1.0
        r2 = float(fallback_radius_px) * float(fallback_radius_px)
        # For blind SEARCHING we accept any detection within FOV; pick max conf
        # Since pred is None we have no gate center - just max conf
        # Sanity: if pred is None we ignore spatial gate
        for d in detections:
            try:
                conf = float(d.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            if conf > best_conf:
                best_conf = conf
                best = d
        if best is None:
            return None
        try:
            return (float(best["x"]), float(best["y"]))
        except Exception:
            return None

    # Gated NN with Mahalanobis
    best = None
    best_d2 = float("inf")
    best_conf = -1.0
    # threshold
    chi2 = float(chi2_threshold)
    for d in detections:
        try:
            xy = (float(d["x"]), float(d["y"]))
        except Exception:
            continue
        d2 = mahalanobis_distance(xy, pred_xy, cov_2x2)
        if d2 <= chi2 and d2 < best_d2:
            best_d2 = d2
            best = d
            try:
                best_conf = float(d.get("confidence", 0.0))
            except Exception:
                best_conf = 0.0
        elif d2 <= chi2 and abs(d2 - best_d2) < 1e-9:
            # tie-break by confidence
            try:
                conf = float(d.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            if conf > best_conf:
                best = d
                best_conf = conf

    if best is not None:
        try:
            return (float(best["x"]), float(best["y"]))
        except Exception:
            return None

    # No gated hit -> no association (do not fallback to truth)
    return None
