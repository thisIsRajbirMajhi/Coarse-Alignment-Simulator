from __future__ import annotations

import numpy as np


def apply_exposure(frame: np.ndarray, exposure: float = 1.0) -> np.ndarray:
    return np.clip(np.asarray(frame, dtype=np.float32) * max(0.0, float(exposure)), 0, 255).astype(frame.dtype)


__all__ = ["apply_exposure"]