# local_terminal/ai/__init__.py - Hybrid-AI lazy loaders (Plan Hybrid-AI §2).
# No torch at import; ONNX via cv2.dnn or onnxruntime. Falls back to classical if missing.

from __future__ import annotations

import os

_ONNX_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

def get_device() -> str:
    """Auto-detect GPU via torch.cuda, fallback to cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"

def _load_onnx_c2dnn(path: str):
    try:
        import cv2
        if os.path.exists(path):
            net = cv2.dnn.readNetFromONNX(path)
            if not net.empty():
                # Prefer CUDA backend if GPU available
                try:
                    if get_device() == "cuda" and hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                    else:
                        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                except Exception:
                    pass
                return net
    except Exception:
        pass
    return None

def _ort_providers():
    """ORT providers with CUDA first if available."""
    try:
        import onnxruntime
        avail = onnxruntime.get_available_providers()
        if get_device() == "cuda" and "CUDAExecutionProvider" in avail:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:
        pass
    return ["CPUExecutionProvider"]

def load_verifier():
    """Lazy load Tiny-CNN verifier net or None (fallback classical)."""
    try:
        from src.local_terminal.ai.verifier import TinyCNNVerifier
        return TinyCNNVerifier()
    except Exception:
        return None

def load_scorer():
    try:
        from src.local_terminal.ai.scorer import MLPScorer
        return MLPScorer()
    except Exception:
        return None

def load_predictor():
    try:
        from src.local_terminal.ai.predictor import TemporalMLPPredictor
        return TemporalMLPPredictor()
    except Exception:
        return None

def load_ranker():
    try:
        from src.local_terminal.ai.tuner import ScanRanker
        return ScanRanker()
    except Exception:
        return None

__all__ = ["load_verifier", "load_scorer", "load_predictor", "load_ranker"]
