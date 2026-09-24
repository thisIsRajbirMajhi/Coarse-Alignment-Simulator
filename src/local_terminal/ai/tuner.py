# local_terminal/ai/tuner.py - Scan Ranker + Bayesian PID tuner (Plan Hybrid-AI §2).
# Ranker: 6→32→32→20 MLP ~2k params → cell scores for 20-cell scan.
# PID tuner: bg_std/haze → kp/kd lookup (no NN).

from __future__ import annotations

import os
import math
import numpy as np

try:
    import cv2
except Exception:
    cv2 = None

RANKER_PATH = os.path.join(os.path.dirname(__file__), "models", "ranker.onnx")

class ScanRanker:
    """6→20 ranker: [last_known_x, y, vx, vy, unc, misses] → 20 cell scores."""

    def __init__(self):
        self.net = None
        self.device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
        except Exception:
            pass
        if cv2 is not None and os.path.exists(RANKER_PATH):
            try:
                self.net = cv2.dnn.readNetFromONNX(RANKER_PATH)
                try:
                    if self.device == "cuda" and hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                    else:
                        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                except Exception:
                    pass
            except Exception:
                self.net = None

    def _heuristic_scores(self, last_known, velocity, unc: float, misses: int, bg_std: float = 5.0) -> list[float]:
        # Score cells by proximity to predicted position (last_known + velocity*dt*10) and uncertainty
        try:
            from src.local_terminal.scan import build_grid
            grid = build_grid()
            if last_known is None:
                return [1.0 / 20.0] * 20
            lx, ly = float(last_known[0]), float(last_known[1])
            vx, vy = (float(velocity[0]), float(velocity[1])) if velocity else (0.0, 0.0)
            # Predict 0.5s ahead
            px, py = lx + vx * 0.5, ly + vy * 0.5
            # Uncertainty widens distribution
            sigma = max(80.0, float(unc) * 8.0)
            scores = []
            for p in grid:
                d2 = (p.center_x - px) ** 2 + (p.center_y - py) ** 2
                s = math.exp(-d2 / (2 * sigma * sigma))
                scores.append(float(s))
            tot = sum(scores) or 1.0
            return [s / tot for s in scores]
        except Exception:
            return [1.0 / 20.0] * 20

    def rank(self, last_known=None, velocity=None, unc: float = 20.0, misses: int = 0,
             bg_std: float = 5.0) -> list[float]:
        feats = np.array([[float(last_known[0] / 2000.0) if last_known else 0.5,
                           float(last_known[1] / 2000.0) if last_known else 0.5,
                           float(velocity[0] / 100.0) if velocity else 0.0,
                           float(velocity[1] / 100.0) if velocity else 0.0,
                           float(np.clip(unc / 50.0, 0, 1)),
                           float(np.clip(misses / 10.0, 0, 1))]], dtype=np.float32)
        if self.net is not None and cv2 is not None:
            try:
                self.net.setInput(cv2.dnn.blobFromImage(feats))
                out = self.net.forward()
                scores = [float(x) for x in np.squeeze(out).flat[:20]]
                if len(scores) == 20:
                    # Softmax
                    m = max(scores)
                    exps = [math.exp(s - m) for s in scores]
                    tot = sum(exps) or 1.0
                    return [e / tot for e in exps]
            except Exception:
                pass
        return self._heuristic_scores(last_known, velocity, unc, misses, bg_std)

    def ranked_schedule(self, last_known=None, velocity=None, unc: float = 20.0,
                        misses: int = 0, bg_std: float = 5.0, threshold: float = 0.7) -> list[int] | None:
        """Return ranked cell indices if max score >= threshold, else None (fallback systematic)."""
        scores = self.rank(last_known, velocity, unc, misses, bg_std)
        if max(scores, default=0) < threshold:
            return None
        order = sorted(range(20), key=lambda i: scores[i], reverse=True)
        return order

# Bayesian PID lookup (no NN) — bg_std/haze → kp/kd
_PID_TABLE = [
    # (bg_std_max, haze_max, kp, kd)
    (5.0,  0.2, 1.5, 0.25),
    (12.0, 0.4, 1.3, 0.22),
    (20.0, 0.6, 1.0, 0.18),
    (999,  999, 0.8, 0.15),
]

def pid_gains_for(bg_std: float, haze: float = 0.0) -> tuple[float, float]:
    for bg_max, haze_max, kp, kd in _PID_TABLE:
        if bg_std <= bg_max and haze <= haze_max:
            return (kp, kd)
    return (1.0, 0.20)
