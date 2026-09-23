# local_terminal/ai/predictor.py - Temporal-MLP predictor (Plan Hybrid-AI §2).
# Default: 32→64→2 FC ~4k params pure cv2.dnn (replaces LSTM-64 35k needing onnxruntime).
# In: 8×[x y vx vy]=32 → Δpred (dx, dy) residual for KF + reacq seed.
# KF stays master: x = KF + 0.3*Δ, NIS>16 ignore.

from __future__ import annotations

import os
import numpy as np

try:
    import cv2
except Exception:
    cv2 = None

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "predictor.onnx")
LSTM_PATH = os.path.join(os.path.dirname(__file__), "models", "predictor_lstm.onnx")

class TemporalMLPPredictor:
    def __init__(self):
        self.net = None
        self.use_lstm = False
        self.device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
        except Exception:
            pass
        # Prefer LSTM if onnxruntime available and model exists, else Temporal-MLP
        if os.path.exists(LSTM_PATH):
            try:
                import onnxruntime  # type: ignore
                providers = ["CPUExecutionProvider"]
                try:
                    if self.device == "cuda" and "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    elif self.device == "cuda":
                        # Try CUDA anyway if torch says cuda available but ORT not built with it
                        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                except Exception:
                    pass
                self._ort_session = onnxruntime.InferenceSession(LSTM_PATH, providers=providers)
                self.use_lstm = True
                self._ort = onnxruntime
            except Exception:
                self.use_lstm = False
        if not self.use_lstm and cv2 is not None and os.path.exists(MODEL_PATH):
            try:
                self.net = cv2.dnn.readNetFromONNX(MODEL_PATH)
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
        self._history: list[tuple[float, float, float, float]] = []

    def push(self, x: float, y: float, vx: float, vy: float) -> None:
        self._history.append((float(x), float(y), float(vx), float(vy)))
        if len(self._history) > 8:
            self._history.pop(0)

    def reset(self) -> None:
        self._history.clear()

    def _heuristic_delta(self) -> tuple[float, float]:
        if len(self._history) < 3:
            return (0.0, 0.0)
        # Simple linear extrapolation from last 3 velocities
        vxs = [h[2] for h in self._history[-3:]]
        vys = [h[3] for h in self._history[-3:]]
        ax = (vxs[-1] - vxs[0]) / 2.0
        ay = (vys[-1] - vys[0]) / 2.0
        # Predict residual beyond CV (acceleration * dt * 0.3)
        dt = 1.0 / 30.0
        return (float(ax * dt * 0.5), float(ay * dt * 0.5))

    def predict_delta(self) -> tuple[float, float]:
        if len(self._history) < 2:
            return (0.0, 0.0)
        # Build 32-dim vector (pad with zeros if <8)
        vec = []
        for h in self._history:
            vec.extend([h[0] / 640.0, h[1] / 480.0, h[2] / 100.0, h[3] / 100.0])
        while len(vec) < 32:
            vec.extend([0.0, 0.0, 0.0, 0.0])
        vec = np.array([vec[:32]], dtype=np.float32)
        if self.use_lstm:
            try:
                inp_name = self._ort_session.get_inputs()[0].name
                out = self._ort_session.run(None, {inp_name: vec})[0]
                dx, dy = float(np.squeeze(out).flat[0]), float(np.squeeze(out).flat[1]) if out.size >= 2 else (0.0, 0.0)
                return (float(np.clip(dx * 10.0, -20, 20)), float(np.clip(dy * 10.0, -20, 20)))
            except Exception:
                pass
        if self.net is not None and cv2 is not None:
            try:
                self.net.setInput(cv2.dnn.blobFromImage(vec))
                out = self.net.forward()
                arr = np.squeeze(out)
                dx = float(arr.flat[0]) if arr.size >= 1 else 0.0
                dy = float(arr.flat[1]) if arr.size >= 2 else 0.0
                return (float(np.clip(dx * 10.0, -20, 20)), float(np.clip(dy * 10.0, -20, 20)))
            except Exception:
                pass
        return self._heuristic_delta()

    def predict_with_ai(self, kf_pos: tuple[float, float], kf_vel: tuple[float, float]) -> tuple[float, float]:
        """Return AI-corrected position: KF + 0.3*Δ (caller must still check NIS)."""
        dx, dy = self.predict_delta()
        return (float(kf_pos[0] + 0.3 * dx), float(kf_pos[1] + 0.3 * dy))
