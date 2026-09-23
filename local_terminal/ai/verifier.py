# local_terminal/ai/verifier.py - Tiny-CNN 32x32 verifier (Plan Hybrid-AI §2).
# 3xConv 16/32/64 + GAP + FC → p(beacon). ~80k params. ONNX via cv2.dnn.
# Falls back to classical SNR boost if no model file.

from __future__ import annotations

import os
import numpy as np

try:
    import cv2
except Exception:
    cv2 = None  # type: ignore

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "verifier.onnx")

# Lightweight pure-numpy / cv2.dnn inference. If ONNX missing, use heuristic.
class TinyCNNVerifier:
    """32x32 gray patch → p(beacon) 0..1. Heuristic fallback if no ONNX."""

    def __init__(self, threshold: float = 0.6):
        self.threshold = float(threshold)
        self.net = None
        self.device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
        except Exception:
            pass
        if cv2 is not None and os.path.exists(MODEL_PATH):
            try:
                self.net = cv2.dnn.readNetFromONNX(MODEL_PATH)
                # Try CUDA backend for cv2.dnn if available
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

    def _heuristic(self, patch: np.ndarray) -> float:
        """Fallback: shape + peak heuristic ≈ Tiny-CNN behavior."""
        try:
            if patch is None or patch.size == 0:
                return 0.0
            p = patch.astype(float)
            peak = float(p.max())
            mean = float(p.mean())
            std = float(p.std())
            # Beacon-like: moderate peak 80-220, std 15-40, centered mass
            if peak < 30:
                return 0.05
            # Normalized peak prominence
            prom = (peak - mean) / max(std, 1.0)
            # Size check via threshold mass
            _, bw = cv2.threshold(p.astype(np.uint8), int(mean + std), 255, cv2.THRESH_BINARY) if cv2 else (None, p > mean + std)
            area = float(np.count_nonzero(bw))
            # Beacon: prom 2.5-6, area 12-80
            score = 0.0
            if 2.0 <= prom <= 7.0:
                score += 0.4
            if 10 <= area <= 90:
                score += 0.3
            if 60 <= peak <= 240:
                score += 0.2
            # Center concentration (beacon centered)
            h, w = p.shape[:2]
            cy, cx = h // 2, w // 2
            center_mass = float(p[cy-4:cy+5, cx-4:cx+5].mean()) if h > 8 else mean
            if center_mass > mean + 8:
                score += 0.1
            return float(np.clip(score, 0, 1))
        except Exception:
            return 0.0

    def score_patch(self, patch: np.ndarray) -> float:
        if patch is None or patch.size == 0:
            return 0.0
        # Ensure 32x32 gray
        try:
            if patch.ndim == 3:
                g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if cv2 is not None else patch[:, :, 0]
            else:
                g = patch
            if g.shape != (32, 32):
                g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA) if cv2 is not None else np.resize(g, (32, 32))
            g = g.astype(np.float32) / 255.0
        except Exception:
            return self._heuristic(patch)
        if self.net is not None:
            try:
                blob = cv2.dnn.blobFromImage(g, scalefactor=1.0, size=(32, 32))
                self.net.setInput(blob)
                out = self.net.forward()
                p = float(np.squeeze(out).flat[0]) if out.size else 0.0
                # Sigmoid if raw logit
                if p < 0 or p > 1:
                    p = float(1.0 / (1.0 + np.exp(-p)))
                return float(np.clip(p, 0, 1))
            except Exception:
                pass
        return self._heuristic((g * 255).astype(np.uint8))

    def verify(self, frame: np.ndarray, candidate) -> float:
        """Score a SpotCandidate by cropping 32x32 around it."""
        try:
            x, y = int(round(float(candidate.x))), int(round(float(candidate.y)))
            x0, y0 = max(0, x - 16), max(0, y - 16)
            x1, y1 = min(frame.shape[1], x0 + 32), min(frame.shape[0], y0 + 32)
            patch = frame[y0:y1, x0:x1]
            if patch.shape[0] < 32 or patch.shape[1] < 32:
                # Pad
                import numpy as _np
                padded = _np.zeros((32, 32), dtype=frame.dtype)
                padded[: patch.shape[0], : patch.shape[1]] = patch if patch.ndim == 2 else patch[:, :, 0]
                patch = padded
            return self.score_patch(patch)
        except Exception:
            return 0.0
