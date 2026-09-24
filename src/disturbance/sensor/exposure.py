from __future__ import annotations

import numpy as np


def apply_exposure(frame: np.ndarray, exposure: float = 1.0) -> np.ndarray:
    if frame.size == 0 or abs(float(exposure) - 1.0) < 1e-9:
        return frame
    out = np.multiply(np.asarray(frame, dtype=np.float32), max(0.0, float(exposure)), out=None)
    return np.clip(out, 0, 255, out=out).astype(frame.dtype, copy=False)


__all__ = ["apply_exposure"]