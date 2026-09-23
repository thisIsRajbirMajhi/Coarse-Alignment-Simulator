# local_terminal/ai/scorer.py - MLP 7→1 acquisition scorer (Plan Hybrid-AI §2).
# In: [SNR, area, peak, dist_pred, P_rx, age, confirm] → score 0..1.
# Replaces hand 200*fov*beacon*temporal scaling. ONNX or heuristic.

from __future__ import annotations

import os
import numpy as np

try:
    import cv2
except Exception:
    cv2 = None

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "scorer.onnx")

class MLPScorer:
    def __init__(self):
        self.net = None
        if cv2 is not None and os.path.exists(MODEL_PATH):
            try:
                self.net = cv2.dnn.readNetFromONNX(MODEL_PATH)
            except Exception:
                self.net = None

    def _heuristic(self, feats: np.ndarray) -> float:
        try:
            snr, area, peak, dist, prx, age, confirm = [float(x) for x in feats.flat[:7]]
            s = 0.0
            s += 0.30 * float(np.clip((snr - 6) / 10.0, 0, 1))
            s += 0.15 * float(np.clip((area - 8) / 30.0, 0, 1)) if area < 80 else 0.12
            s += 0.10 * float(np.clip((peak - 40) / 100.0, 0, 1))
            s += 0.20 * float(np.clip(1.0 - dist / 200.0, 0, 1))
            s += 0.10 * (1.0 if prx > 1e-6 else 0.0)
            s += 0.10 * float(confirm)
            s -= 0.15 * float(np.clip(age / 0.5, 0, 1))
            return float(np.clip(s, 0, 1))
        except Exception:
            return 0.5

    def score(self, snr_db: float, area_px: float, peak: float, dist_pred_px: float,
              p_rx_w: float, age_s: float, confirm: float) -> float:
        feats = np.array([[float(snr_db), float(area_px), float(peak),
                           float(dist_pred_px), float(p_rx_w), float(age_s), float(confirm)]], dtype=np.float32)
        # Normalize roughly to 0..1 for ONNX
        norm = feats.copy()
        norm[0, 0] = float(np.clip((feats[0, 0] - 6) / 14.0, 0, 1))
        norm[0, 1] = float(np.clip(feats[0, 1] / 100.0, 0, 1))
        norm[0, 2] = float(np.clip(feats[0, 2] / 255.0, 0, 1))
        norm[0, 3] = float(np.clip(feats[0, 3] / 250.0, 0, 1))
        norm[0, 4] = float(1.0 if feats[0, 4] > 1e-6 else 0.0)
        norm[0, 5] = float(np.clip(feats[0, 5] / 0.5, 0, 1))
        norm[0, 6] = float(np.clip(feats[0, 6], 0, 1))
        if self.net is not None:
            try:
                self.net.setInput(cv2.dnn.blobFromImage(norm))
                out = self.net.forward()
                p = float(np.squeeze(out).flat[0])
                if p < 0 or p > 1:
                    p = float(1.0 / (1.0 + np.exp(-p)))
                return float(np.clip(p, 0, 1))
            except Exception:
                pass
        return self._heuristic(feats[0])

    def score_candidate(self, candidate, dist_pred_px: float = 0.0, p_rx_w: float = 0.0,
                        age_s: float = 0.0, confirm: float = 1.0) -> float:
        try:
            return self.score(float(getattr(candidate, "snr_db", 6.0)),
                              float(getattr(candidate, "area_px", 20)),
                              float(getattr(candidate, "peak", 100)),
                              float(dist_pred_px), float(p_rx_w), float(age_s), float(confirm))
        except Exception:
            return 0.5
