# local_terminal/ai/verifier.py - Tiny-CNN 32x32/64x64 verifier (Plan Hybrid-AI §2 + simple reliable AI spec).
# Spec Stage B: single lightweight CNN 32x32 (or 64x64) -> p_beacon 0..1.
# p_noise / p_distractor optional (derived as 1-p). ONNX via cv2.dnn, heuristic fallback.
# Confidence fusion weights 0.35/0.10/0.15/0.20/0.20 consumed by detector/confidence.py.
# Classical fallback when ONNX missing.

from __future__ import annotations

import math
import os
import numpy as np

try:
    import cv2
except Exception:
    cv2 = None  # type: ignore

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "verifier.onnx")

# Lightweight pure-numpy / cv2.dnn inference. If ONNX missing, use heuristic.
class TinyCNNVerifier:
    """32x32 (or 64x64) gray patch → p_beacon 0..1. Heuristic fallback if no ONNX.

    Spec input: 32x32 or 64x64 gray uint8. Output: p_beacon in [0,1];
    p_noise/p_distractor optional as 1-p or from second ONNX output.
    """

    # spec allows both resolutions
    SUPPORTED_SIZES = ((32, 32), (64, 64))

    def __init__(self, threshold: float = 0.6, input_size: int = 32):
        self.threshold = float(threshold)
        self.input_size = int(input_size) if int(input_size) in (32, 64) else 32
        self.net = None
        self.device = "cpu"
        # Device detection via cv2.cuda only — avoids torch DLL crash on Python 3.14
        try:
            if cv2 is not None and hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
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
        sz = int(getattr(self, "input_size", 32))
        # Ensure sz x sz gray
        try:
            if patch.ndim == 3:
                g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if cv2 is not None else patch[:, :, 0]
            else:
                g = patch
            if g.shape[0] != sz or g.shape[1] != sz:
                g = cv2.resize(g, (sz, sz), interpolation=cv2.INTER_AREA) if cv2 is not None else np.resize(g, (sz, sz))
            g = g.astype(np.float32) / 255.0
        except Exception:
            return self._heuristic(patch)
        if self.net is not None:
            try:
                blob = cv2.dnn.blobFromImage(g, scalefactor=1.0, size=(sz, sz))
                self.net.setInput(blob)
                out = self.net.forward()
                # ONNX may output 1 logit (p_beacon) or 2/3 (beacon/noise/distractor)
                arr = np.squeeze(out)
                if arr.size == 0:
                    p = 0.0
                elif arr.size == 1:
                    p = float(arr.flat[0])
                    if p < 0 or p > 1:
                        p = float(1.0 / (1.0 + np.exp(-p)))
                else:
                    # softmax first two as beacon vs noise
                    vals = [float(x) for x in arr.flat[:3]]
                    m = max(vals)
                    exps = [math.exp(v - m) for v in vals] if any(v < 0 or v > 1 for v in vals) else vals
                    tot = sum(exps) or 1.0
                    p = float(exps[0] / tot)
                return float(np.clip(p, 0, 1))
            except Exception:
                pass
        # heuristic expects uint8; resize heuristic input to 32 for consistency
        try:
            hu8 = (g * 255).astype(np.uint8)
            if hu8.shape != (32, 32):
                hu8 = cv2.resize(hu8, (32, 32), interpolation=cv2.INTER_AREA) if cv2 is not None else hu8
            return self._heuristic(hu8)
        except Exception:
            return self._heuristic(patch)

    def score_patch_with_distractor(self, patch: np.ndarray) -> dict:
        """Return dict {p_beacon, p_noise, p_distractor} — auxiliary outputs optional."""
        p = float(self.score_patch(patch))
        return {"p_beacon": p, "p_noise": float(1.0 - p), "p_distractor": float(1.0 - p)}

    def verify(self, frame: np.ndarray, candidate) -> float:
        """Score a SpotCandidate by cropping input_size x input_size around it."""
        try:
            sz = int(getattr(self, "input_size", 32))
            half = sz // 2
            x, y = int(round(float(candidate.x))), int(round(float(candidate.y)))
            x0, y0 = max(0, x - half), max(0, y - half)
            x1, y1 = min(frame.shape[1], x0 + sz), min(frame.shape[0], y0 + sz)
            patch = frame[y0:y1, x0:x1]
            if patch.shape[0] < sz or patch.shape[1] < sz:
                import numpy as _np
                padded = _np.zeros((sz, sz), dtype=frame.dtype)
                padded[: patch.shape[0], : patch.shape[1]] = patch if patch.ndim == 2 else patch[:, :, 0]
                patch = padded
            return self.score_patch(patch)
        except Exception:
            return 0.0

    def verify_fused(self, frame: np.ndarray, candidate, shape_score: float = 0.5,
                     brightness_score: float = 0.5, motion_score: float = 0.5,
                     prediction_score: float = 0.5, weights: dict | None = None) -> float:
        """Convenience: p_beacon + confidence fusion -> C_total."""
        try:
            from src.local_terminal.ai.confidence import confidence_fusion as _cf
        except Exception:
            _cf = None
        p = float(self.verify(frame, candidate))
        if _cf is None:
            return p
        return float(_cf(p, shape_score, brightness_score, motion_score, prediction_score, weights))
