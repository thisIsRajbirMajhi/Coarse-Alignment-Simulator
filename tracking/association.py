# tracking/association — multi-beacon target association (temporal identity, not confidence-only)
#
# Why needed: simulator supports up to 5 beacons. Highest-confidence box may be
# a distractor. Association preserves "same beacon as ~33ms ago" using:
#   1. Kalman predicted position (primary anchor)
#   2. Detection confidence (reject weak / break ties)
#   3. Distance from previous target (short-term continuity)
#   4. Motion consistency (reject implausible jumps)
#   5. Optional signature (reserved)

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.config_base import BaseValidatedConfig, clip_field
from tracking.detector import Detection

ASSOC_LIMITS = {
    "w_pred": (0.0, 5.0),
    "w_conf": (0.0, 5.0),
    "w_hist": (0.0, 5.0),
    "w_motion": (0.0, 5.0),
    "gate_px": (20.0, 1000.0),
    "max_jump_px": (20.0, 1000.0),
}

ASSOC_DEFAULTS = {
    "w_pred": 2.0,
    "w_conf": 0.8,
    "w_hist": 0.6,
    "w_motion": 0.5,
    "gate_px": 300.0,
    "max_jump_px": 150.0,
}


@dataclass
class AssociationConfig(BaseValidatedConfig):
    LIMITS = ASSOC_LIMITS
    DEFAULTS = ASSOC_DEFAULTS

    w_pred: float = ASSOC_DEFAULTS["w_pred"]
    w_conf: float = ASSOC_DEFAULTS["w_conf"]
    w_hist: float = ASSOC_DEFAULTS["w_hist"]
    w_motion: float = ASSOC_DEFAULTS["w_motion"]
    gate_px: float = ASSOC_DEFAULTS["gate_px"]
    max_jump_px: float = ASSOC_DEFAULTS["max_jump_px"]

    def validate(self) -> "AssociationConfig":
        self.w_pred = float(clip_field(self.w_pred, *self.LIMITS["w_pred"]))
        self.w_conf = float(clip_field(self.w_conf, *self.LIMITS["w_conf"]))
        self.w_hist = float(clip_field(self.w_hist, *self.LIMITS["w_hist"]))
        self.w_motion = float(clip_field(self.w_motion, *self.LIMITS["w_motion"]))
        self.gate_px = float(clip_field(self.gate_px, *self.LIMITS["gate_px"]))
        self.max_jump_px = float(clip_field(self.max_jump_px, *self.LIMITS["max_jump_px"]))
        return self


def associate(
    detections: list[Detection],
    predicted: tuple[float, float] | None = None,
    last_position: tuple[float, float] | None = None,
    last_velocity: tuple[float, float] | None = None,
    dt: float = 1 / 30,
    config: AssociationConfig | None = None,
) -> Detection | None:
    """Select designated target. Returns None if no valid candidate.

    Never uses ground truth — only prediction, confidence, history, motion.
    """
    cfg = (config or AssociationConfig()).validate()
    if not detections:
        return None
    # Drop invalid (NaN/inf) candidates — prevents one corrupt box breaking lock
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

    # No prediction yet (first frame): pick highest confidence
    if predicted is None and last_position is None:
        return max(cands, key=lambda d: (d.confidence, -(d.center[0] ** 2 + d.center[1] ** 2)))

    # Single candidate: accept directly if inside gate, else still return it
    # for reacq path (caller state machine decides). Avoids scoring jitter.
    if len(cands) == 1:
        return cands[0]

    anchor = predicted if predicted is not None else last_position
    assert anchor is not None

    best: Detection | None = None
    best_score = -1e18
    for d in cands:
        cx, cy = d.center
        dist_pred = float(np.hypot(cx - anchor[0], cy - anchor[1]))
        if dist_pred > float(cfg.gate_px):
            continue  # outside gate — likely distractor
        s_pred = 1.0 / (1.0 + dist_pred / 50.0)

        s_conf = float(np.clip(d.confidence, 0.0, 1.0))

        if last_position is not None:
            dist_hist = float(np.hypot(cx - last_position[0], cy - last_position[1]))
            s_hist = 1.0 / (1.0 + dist_hist / 50.0)
        else:
            dist_hist = dist_pred
            s_hist = s_pred

        # Motion consistency: expected position = last + velocity*dt
        if last_position is not None and last_velocity is not None:
            ex = last_position[0] + last_velocity[0] * dt
            ey = last_position[1] + last_velocity[1] * dt
            dist_motion = float(np.hypot(cx - ex, cy - ey))
            s_motion = 1.0 / (1.0 + dist_motion / 50.0)
            if dist_hist > float(cfg.max_jump_px) and dist_motion > float(cfg.max_jump_px):
                s_motion *= 0.2  # penalize implausible jump
        else:
            s_motion = 1.0

        score = (
            float(cfg.w_pred) * s_pred
            + float(cfg.w_conf) * s_conf
            + float(cfg.w_hist) * s_hist
            + float(cfg.w_motion) * s_motion
        )
        if score > best_score:
            best_score = score
            best = d
    # Fallback: if all gated out, return closest to anchor (robust reacq)
    if best is None:
        best = min(cands, key=lambda d: float(np.hypot(d.center[0] - anchor[0], d.center[1] - anchor[1])))
    return best
