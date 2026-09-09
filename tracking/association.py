# tracking/association — multi-beacon target association (temporal identity, not confidence-only)
#
# Why needed: simulator supports up to 5 beacons. Highest-confidence box may be
# a distractor. Association preserves "same beacon as ~33ms ago" using (§17):
#   1. Distance / Mahalanobis to predicted position (§17.1, primary anchor)
#   2. Bounding-box IoU vs predicted box (§17.2, spatial overlap)
#   3. Appearance / shape similarity (§17.3: area + circularity)
#   4. Detection confidence (§17.4, reject weak / break ties)
#   5. Motion consistency (§17.5, reject implausible jumps)
#   6. Size consistency (scale-change penalty, distractor-swap guard)

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.config_base import BaseValidatedConfig, clip_field
from tracking.detector import Detection, bbox_iou

ASSOC_LIMITS = {
    "w_pred": (0.0, 5.0),
    "w_conf": (0.0, 5.0),
    "w_hist": (0.0, 5.0),
    "w_motion": (0.0, 5.0),
    "w_size": (0.0, 5.0),
    "w_iou": (0.0, 5.0),
    "w_appear": (0.0, 5.0),
    "gate_px": (20.0, 1000.0),
    "max_jump_px": (20.0, 1000.0),
    "mahalanobis_gate": (2.0, 20.0),
}

ASSOC_DEFAULTS = {
    "w_pred": 2.0,
    "w_conf": 0.8,
    "w_hist": 0.6,
    "w_motion": 0.5,
    "w_size": 0.4,
    "w_iou": 0.6,
    "w_appear": 0.4,
    "gate_px": 300.0,
    "max_jump_px": 150.0,
    "mahalanobis_gate": 9.21,  # chi2 2-dof 99%: statistically principled gate
    "use_mahalanobis": True,
}


@dataclass
class AssociationConfig(BaseValidatedConfig):
    LIMITS = ASSOC_LIMITS
    DEFAULTS = {k: v for k, v in ASSOC_DEFAULTS.items() if k in ASSOC_LIMITS}

    w_pred: float = ASSOC_DEFAULTS["w_pred"]
    w_conf: float = ASSOC_DEFAULTS["w_conf"]
    w_hist: float = ASSOC_DEFAULTS["w_hist"]
    w_motion: float = ASSOC_DEFAULTS["w_motion"]
    w_size: float = ASSOC_DEFAULTS["w_size"]
    w_iou: float = ASSOC_DEFAULTS["w_iou"]
    w_appear: float = ASSOC_DEFAULTS["w_appear"]
    gate_px: float = ASSOC_DEFAULTS["gate_px"]
    max_jump_px: float = ASSOC_DEFAULTS["max_jump_px"]
    mahalanobis_gate: float = ASSOC_DEFAULTS["mahalanobis_gate"]
    use_mahalanobis: bool = ASSOC_DEFAULTS["use_mahalanobis"]

    def validate(self) -> "AssociationConfig":
        self.w_pred = float(clip_field(self.w_pred, *self.LIMITS["w_pred"]))
        self.w_conf = float(clip_field(self.w_conf, *self.LIMITS["w_conf"]))
        self.w_hist = float(clip_field(self.w_hist, *self.LIMITS["w_hist"]))
        self.w_motion = float(clip_field(self.w_motion, *self.LIMITS["w_motion"]))
        self.w_size = float(clip_field(self.w_size, *self.LIMITS["w_size"]))
        self.w_iou = float(clip_field(self.w_iou, *self.LIMITS["w_iou"]))
        self.w_appear = float(clip_field(self.w_appear, *self.LIMITS["w_appear"]))
        self.gate_px = float(clip_field(self.gate_px, *self.LIMITS["gate_px"]))
        self.max_jump_px = float(clip_field(self.max_jump_px, *self.LIMITS["max_jump_px"]))
        self.mahalanobis_gate = float(clip_field(self.mahalanobis_gate, *self.LIMITS["mahalanobis_gate"]))
        self.use_mahalanobis = bool(self.use_mahalanobis)
        return self


def mahalanobis2(residual: tuple[float, float], cov: np.ndarray | None, meas_var: float = 9.0) -> float:
    """Squared Mahalanobis distance r^T S^-1 r with S = cov_xy + meas_var*I.

    Falls back to squared Euclidean / meas_var when cov is unavailable.
    Never raises.
    """
    try:
        rx, ry = float(residual[0]), float(residual[1])
        r = float(meas_var) if np.isfinite(meas_var) else 9.0
        r = float(np.clip(r, 1.0, 100.0))
        if cov is not None:
            try:
                C = np.asarray(cov, dtype=float).reshape(2, 2)
                S = C + np.eye(2) * r
            except Exception:
                S = np.eye(2) * r
        else:
            S = np.eye(2) * r
        det = float(S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0])
        if not np.isfinite(det) or det < 1e-6:
            return float((rx * rx + ry * ry) / max(1.0, r))
        inv = np.array([[S[1, 1], -S[0, 1]], [-S[1, 0], S[0, 0]]]) / det
        v = np.array([rx, ry])
        d2 = float(v @ inv @ v)
        return float(d2) if np.isfinite(d2) else float((rx * rx + ry * ry) / max(1.0, r))
    except Exception:
        try:
            return float(residual[0] ** 2 + residual[1] ** 2) / 9.0
        except Exception:
            return 1e9


def _detection_size(d: Detection) -> float:
    try:
        return float(d.width + d.height) / 2.0
    except Exception:
        return 12.0


def _pred_bbox(anchor: tuple[float, float], last_size: float | None) -> tuple[float, float, float, float]:
    """Predicted box (§17.2): square of side last_size centred at anchor."""
    try:
        s = float(last_size) if last_size is not None and np.isfinite(last_size) else 12.0
        s = float(np.clip(s, 4.0, 120.0))
        ax, ay = float(anchor[0]), float(anchor[1])
        h = s / 2.0
        return (ax - h, ay - h, ax + h, ay + h)
    except Exception:
        return (anchor[0] - 6, anchor[1] - 6, anchor[0] + 6, anchor[1] + 6)


def _appearance_score(
    d: Detection,
    last_area: float | None,
    last_circ: float | None,
) -> float:
    """Appearance similarity (§17.3) in [0,1].

    When a previous appearance is known, penalise log-area change +
    circularity drift (same beacon keeps shape). Otherwise fall back to a
    beacon-likeness prior (compact + plausible size scores higher).
    Never raises.
    """
    try:
        circ = float(np.clip(getattr(d, "circularity", 1.0), 0.0, 1.0))
        area = float(getattr(d, "area", 0.0) or (d.width * d.height))
        if last_area is not None and np.isfinite(last_area) and last_area > 1e-6:
            la = float(max(last_area, 1e-6))
            a = float(max(area, 1e-6))
            log_ratio = abs(float(np.log(a / la)))
            area_sim = 1.0 / (1.0 + log_ratio * 2.0)
        else:
            # Plausible beacon size prior: peak ~25-400 px^2.
            if area < 6:
                area_sim = 0.3
            elif area <= 400:
                area_sim = 0.7 + 0.3 * (1.0 - abs(area - 100.0) / 400.0)
            else:
                area_sim = float(np.clip(400.0 / max(area, 1.0), 0.1, 0.7))
        if last_circ is not None and np.isfinite(last_circ):
            circ_sim = 1.0 / (1.0 + abs(circ - float(last_circ)) * 2.0)
        else:
            circ_sim = 0.5 + 0.5 * circ
        return float(np.clip(0.5 * area_sim + 0.5 * circ_sim, 0.0, 1.0))
    except Exception:
        return 0.5


def _score_candidate(
    d: Detection,
    anchor: tuple[float, float],
    last_position: tuple[float, float] | None,
    last_velocity: tuple[float, float] | None,
    last_size: float | None,
    dt: float,
    pred_cov: np.ndarray | None,
    cfg: AssociationConfig,
    last_area: float | None = None,
    last_circ: float | None = None,
) -> tuple[float, bool, float]:
    """Return (score, gated_out, mahalanobis_d2). Never raises."""
    try:
        cx, cy = float(d.center[0]), float(d.center[1])
        dist_pred = float(np.hypot(cx - anchor[0], cy - anchor[1]))
        meas_var = float(getattr(d, "pos_var", 9.0))
        m_dist2 = mahalanobis2((cx - anchor[0], cy - anchor[1]), pred_cov, meas_var)
        # Dual gate: statistical (Mahalanobis) AND hard pixel cap (safety)
        if bool(cfg.use_mahalanobis) and pred_cov is not None:
            if m_dist2 > float(cfg.mahalanobis_gate) and dist_pred > float(cfg.gate_px):
                return (-1e18, True, m_dist2)
        else:
            if dist_pred > float(cfg.gate_px):
                return (-1e18, True, m_dist2)
        # Prediction term: Mahalanobis-aware when cov available, else Euclidean
        if bool(cfg.use_mahalanobis) and pred_cov is not None:
            s_pred = 1.0 / (1.0 + m_dist2 / 2.0)
        else:
            s_pred = 1.0 / (1.0 + dist_pred / 50.0)

        s_conf = float(np.clip(d.confidence, 0.0, 1.0))

        if last_position is not None:
            dist_hist = float(np.hypot(cx - last_position[0], cy - last_position[1]))
            s_hist = 1.0 / (1.0 + dist_hist / 50.0)
        else:
            dist_hist = dist_pred
            s_hist = s_pred

        if last_position is not None and last_velocity is not None:
            ex = last_position[0] + last_velocity[0] * dt
            ey = last_position[1] + last_velocity[1] * dt
            dist_motion = float(np.hypot(cx - ex, cy - ey))
            s_motion = 1.0 / (1.0 + dist_motion / 50.0)
            if dist_hist > float(cfg.max_jump_px) and dist_motion > float(cfg.max_jump_px):
                s_motion *= 0.2
        else:
            s_motion = 1.0

        # Size consistency: penalize abrupt scale changes (distractor swap)
        if last_size is not None and last_size > 1e-6:
            sz = _detection_size(d)
            ratio = max(sz, 1e-6) / max(last_size, 1e-6)
            ratio = max(ratio, 1.0 / max(ratio, 1e-6))
            s_size = 1.0 / (1.0 + max(0.0, ratio - 1.0) * 2.0)
        else:
            s_size = 1.0

        # Bounding-box IoU vs predicted box (§17.2, soft spatial overlap).
        # Small beacons can have IoU=0 even a few px off, so this is a bonus
        # term, never a gate (gating stays Mahalanobis + pixel cap above).
        try:
            s_iou = float(bbox_iou(_pred_bbox(anchor, last_size), d.bbox))
            s_iou = float(np.clip(s_iou, 0.0, 1.0))
        except Exception:
            s_iou = 0.0

        # Appearance / shape similarity (§17.3).
        s_appear = _appearance_score(d, last_area, last_circ)

        score = (
            float(cfg.w_pred) * s_pred
            + float(cfg.w_conf) * s_conf
            + float(cfg.w_hist) * s_hist
            + float(cfg.w_motion) * s_motion
            + float(cfg.w_size) * s_size
            + float(getattr(cfg, "w_iou", 0.0)) * s_iou
            + float(getattr(cfg, "w_appear", 0.0)) * s_appear
        )
        # Down-weight very uncertain measurements slightly
        try:
            score *= 1.0 / (1.0 + max(0.0, meas_var - 9.0) / 60.0)
        except Exception:
            pass
        return (score, False, m_dist2)
    except Exception:
        return (-1e18, True, 1e9)


def associate(
    detections: list[Detection],
    predicted: tuple[float, float] | None = None,
    last_position: tuple[float, float] | None = None,
    last_velocity: tuple[float, float] | None = None,
    dt: float = 1 / 30,
    config: AssociationConfig | None = None,
    pred_cov: np.ndarray | None = None,
    last_size: float | None = None,
    last_area: float | None = None,
    last_circ: float | None = None,
) -> Detection | None:
    """Select designated target. Returns None if no valid candidate.

    Never uses ground truth — only prediction, confidence, history, motion,
    IoU (§17.2) and appearance (§17.3).
    New optional args (backward compatible): pred_cov (2x2 tracker covariance
    for Mahalanobis gating), last_size (mean target size), last_area /
    last_circ (previous appearance for similarity).
    """
    cfg = (config or AssociationConfig()).validate()
    if not detections:
        return None
    cands: list[Detection] = []
    for d in detections:
        try:
            cx, cy = float(d.center[0]), float(d.center[1])
            if not (np.isfinite(cx) and np.isfinite(cy) and np.isfinite(d.confidence)):
                continue
            cands.append(d)
        except Exception:
            continue
    if not cands:
        return None

    if predicted is None and last_position is None:
        return max(cands, key=lambda d: (d.confidence, -(d.center[0] ** 2 + d.center[1] ** 2)))

    # Single candidate: still gate it (fixes old bypass that accepted any
    # distractor). Return None if hard-gated so state machine can coast.
    if len(cands) == 1:
        d = cands[0]
        anchor1 = predicted if predicted is not None else last_position
        assert anchor1 is not None
        score, gated, _ = _score_candidate(d, anchor1, last_position, last_velocity, last_size, dt, pred_cov, cfg, last_area, last_circ)
        if gated:
            # Robust reacq: accept only if within hard pixel gate
            try:
                dist = float(np.hypot(d.center[0] - anchor1[0], d.center[1] - anchor1[1]))
            except Exception:
                return None
            if dist > float(cfg.gate_px) * 1.5:
                return None
        return d

    anchor = predicted if predicted is not None else last_position
    assert anchor is not None

    best: Detection | None = None
    best_score = -1e18
    for d in cands:
        score, gated, _ = _score_candidate(d, anchor, last_position, last_velocity, last_size, dt, pred_cov, cfg, last_area, last_circ)
        if gated:
            continue
        if score > best_score:
            best_score = score
            best = d
    if best is None:
        # All gated: no trustworthy match -> return None (coast) instead of
        # forcing closest-distractor lock.
        return None
    return best


def associate_multi(
    detections: list[Detection],
    tracks: list[dict],
    dt: float = 1 / 30,
    config: AssociationConfig | None = None,
) -> dict[int, Detection | None]:
    """Joint multi-target assignment (greedy Hungarian, no scipy needed).

    Args:
      detections: candidate boxes this frame.
      tracks: list of dicts with keys: predicted (x,y), pred_cov (2x2|None),
        last_position, last_velocity, last_size, last_area, last_circ.
    Returns:
      {track_idx: Detection|None}. Each detection used at most once.
      Prevents two tracks stealing the same box (identity switch).
    """
    cfg = (config or AssociationConfig()).validate()
    out: dict[int, Detection | None] = {i: None for i in range(len(tracks))}
    if not tracks or not detections:
        return out
    # Build cost = -score; gated pairs get +inf
    pairs: list[tuple[float, int, int]] = []
    for ti, tr in enumerate(tracks):
        anchor = tr.get("predicted", tr.get("last_position"))
        if anchor is None:
            continue
        for di, d in enumerate(detections):
            try:
                score, gated, _ = _score_candidate(
                    d, (float(anchor[0]), float(anchor[1])),
                    tr.get("last_position"), tr.get("last_velocity"),
                    tr.get("last_size"), dt, tr.get("pred_cov"), cfg,
                    tr.get("last_area"), tr.get("last_circ"),
                )
            except Exception:
                continue
            if gated:
                continue
            pairs.append((-score, ti, di))
    pairs.sort(key=lambda t: t[0])
    used_d, used_t = set(), set()
    det_list = list(detections)
    for neg_score, ti, di in pairs:
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        out[ti] = det_list[di]
    return out
