from __future__ import annotations

import cv2
import numpy as np


def apply_blur(frame: np.ndarray, sigma: float = 0.0) -> np.ndarray:
    sigma = max(0.0, float(sigma))
    if sigma <= 0.0:
        return frame
    return cv2.GaussianBlur(frame, (0, 0), sigmaX=sigma, sigmaY=sigma)


__all__ = ["apply_blur"]