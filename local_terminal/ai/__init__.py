# local_terminal/ai/__init__.py - Hybrid-AI lazy loaders (Plan Hybrid-AI §2).
# No torch at import; ONNX via cv2.dnn or onnxruntime. Falls back to classical if missing.

from __future__ import annotations

import os

_ONNX_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

def _load_onnx_c2dnn(path: str):
    try:
        import cv2
        if os.path.exists(path):
            net = cv2.dnn.readNetFromONNX(path)
            if not net.empty():
                return net
    except Exception:
        pass
    return None

def load_verifier():
    """Lazy load Tiny-CNN verifier net or None (fallback classical)."""
    try:
        from local_terminal.ai.verifier import TinyCNNVerifier
        return TinyCNNVerifier()
    except Exception:
        return None

def load_scorer():
    try:
        from local_terminal.ai.scorer import MLPScorer
        return MLPScorer()
    except Exception:
        return None

def load_predictor():
    try:
        from local_terminal.ai.predictor import TemporalMLPPredictor
        return TemporalMLPPredictor()
    except Exception:
        return None

def load_ranker():
    try:
        from local_terminal.ai.tuner import ScanRanker
        return ScanRanker()
    except Exception:
        return None

__all__ = ["load_verifier", "load_scorer", "load_predictor", "load_ranker"]
