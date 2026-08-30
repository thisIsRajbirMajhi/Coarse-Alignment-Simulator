"""
Module: environment.vignetting
Purpose: Radial edge-darkening (vignetting) for optical realism.
Physics: Falloff  vig(r) = 1 - strength * (r/R)^1.8  clamped to [0.35, 1.0].
Public API: apply_vignetting
Notes: In-place scaling of float32 base buffer; no blur for sharpness.
"""

import math

import numpy as np

# ============================================================
# SECTION: Vignetting
# ============================================================

def apply_vignetting(base: np.ndarray, strength: float) -> np.ndarray:
    """
    Apply radial vignetting to the base buffer.

    ------------------------------------------------------------
    Inputs:
      base     : (H, W, 3) float32 sky buffer (modified in-place for efficiency)
      strength : 0.0..0.92 vignetting strength (0 = off)
    Returns:
      base : same array, clipped to [0,255]
    Notes:
      - strength ~0.0 bypasses computation entirely (fast path).
      - max_r is corner distance; exponent 1.8 gives smooth perceptual falloff.
    ------------------------------------------------------------
    """
    if strength <= 1e-3:
        return base
    h, w = base.shape[0], base.shape[1]
    ys, xs = np.ogrid[:h, :w]
    cx, cy = w * 0.5, h * 0.5
    r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    max_r = math.sqrt(cx * cx + cy * cy)
    vig = 1.0 - float(strength) * (r / max_r) ** 1.8
    vig = np.clip(vig, 0.35, 1.0).astype(np.float32)
    base *= vig[:, :, None]
    return np.clip(base, 0, 255)
