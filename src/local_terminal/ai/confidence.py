# local_terminal/ai/confidence.py - Confidence fusion per spec.
# C_total = 0.35*AI + 0.10*shape + 0.15*brightness + 0.20*motion + 0.20*prediction
# Thresholds: c_detect / c_identify / c_track / c_lost
# Classical fallback when AI=0.
from __future__ import annotations

import math

DEFAULT_WEIGHTS = {
    "ai": 0.35,
    "shape": 0.10,
    "brightness": 0.15,
    "motion": 0.20,
    "prediction": 0.20,
}

# Validate weights sum to 1.0 within tolerance
_WEIGHT_SUM_TOL = 1e-6


def confidence_fusion(
    p_ai: float = 0.0,
    shape_score: float = 0.0,
    brightness_score: float = 0.0,
    motion_score: float = 0.0,
    prediction_score: float = 0.0,
    weights: dict | None = None,
) -> float:
    """Weighted C_total per spec. All inputs 0..1. Classical fallback when p_ai=0."""
    w = weights or DEFAULT_WEIGHTS
    # allow caller dict missing keys -> fallback to default
    w_ai = float(w.get("ai", DEFAULT_WEIGHTS["ai"]))
    w_shape = float(w.get("shape", DEFAULT_WEIGHTS["shape"]))
    w_brightness = float(w.get("brightness", DEFAULT_WEIGHTS["brightness"]))
    w_motion = float(w.get("motion", DEFAULT_WEIGHTS["motion"]))
    w_prediction = float(w.get("prediction", DEFAULT_WEIGHTS["prediction"]))
    # clamp inputs
    p_ai = float(max(0.0, min(1.0, p_ai)))
    shape_score = float(max(0.0, min(1.0, shape_score)))
    brightness_score = float(max(0.0, min(1.0, brightness_score)))
    motion_score = float(max(0.0, min(1.0, motion_score)))
    prediction_score = float(max(0.0, min(1.0, prediction_score)))
    c = w_ai * p_ai + w_shape * shape_score + w_brightness * brightness_score + w_motion * motion_score + w_prediction * prediction_score
    return float(max(0.0, min(1.0, c)))


class ConfidenceFusion:
    """Stateful wrapper with configured weights + thresholds."""

    def __init__(
        self,
        weights: dict | None = None,
        c_detect: float = 0.55,
        c_identify: float = 0.75,
        c_track: float = 0.60,
        c_lost: float = 0.40,
    ):
        self.weights = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
        # normalise if sum != 1 (keep ratios)
        s = sum(float(v) for v in self.weights.values())
        if abs(s - 1.0) > _WEIGHT_SUM_TOL and s > 1e-9:
            for k in self.weights:
                self.weights[k] = float(self.weights[k]) / s
        self.c_detect = float(c_detect)
        self.c_identify = float(c_identify)
        self.c_track = float(c_track)
        self.c_lost = float(c_lost)

    def fuse(
        self,
        p_ai: float = 0.0,
        shape_score: float = 0.0,
        brightness_score: float = 0.0,
        motion_score: float = 0.0,
        prediction_score: float = 0.0,
    ) -> float:
        return confidence_fusion(p_ai, shape_score, brightness_score, motion_score, prediction_score, self.weights)

    def is_detected(self, c_total: float) -> bool:
        return float(c_total) >= self.c_detect

    def is_identified(self, c_total: float) -> bool:
        return float(c_total) >= self.c_identify

    def is_tracking(self, c_total: float) -> bool:
        return float(c_total) >= self.c_track

    def is_lost(self, c_total: float) -> bool:
        return float(c_total) < self.c_lost

    def decide(self, c_total: float) -> str:
        """Return highest achieved level: 'identify'|'track'|'detect'|'lost'."""
        c = float(c_total)
        if c >= self.c_identify:
            return "identify"
        if c >= self.c_track:
            return "track"
        if c >= self.c_detect:
            return "detect"
        return "lost"


__all__ = ["DEFAULT_WEIGHTS", "confidence_fusion", "ConfidenceFusion"]
