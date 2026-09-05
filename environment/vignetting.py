# environment/vignetting.py - Physical cos4 + off-axis lens vignetting
#
# PHYSICAL MODEL: Real lens vignetting follows cos^4(θ) + mechanical shading.
#   Previous 1.8 exponent approximated perception; new model uses exponent 2.1
#   (closer to cos4 at 4° FOV) with slight asymmetric tilt for realism.
#   Still sensor/image-space (FOV centre), follows camera.

import math

import numpy as np

# Cache for vignetting masks — key: (h,w, quantized_strength)
_VIG_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_CACHE_MAX = 16


def _get_vig_mask(h: int, w: int, strength: float) -> np.ndarray:
    # Quantize strength to 1% to avoid cache explosion
    q = int(round(float(strength) * 100))
    key = (h, w, q)
    if key in _VIG_CACHE:
        return _VIG_CACHE[key]
    ys, xs = np.ogrid[:h, :w]
    cx, cy = w * 0.5, h * 0.5
    r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    max_r = math.sqrt(cx * cx + cy * cy)
    # Physical cos4 approx: (r/max_r)^2.1 gives smooth natural falloff for 4° FOV
    # Add subtle asymmetry: bottom slightly less vignetted (sensor tilt) — 3% shift
    # by biasing y centre 1.5% down
    cy_eff = cy * 1.015
    r_eff = np.sqrt((xs - cx) ** 2 + (ys - cy_eff) ** 2)
    norm = np.clip(r_eff / (max_r + 1e-6), 0, 1).astype(np.float32)
    # Cosine-fourth + mechanical: vig = 1 - s*(norm^2.1 + 0.12*norm^4)
    vig = 1.0 - (q / 100.0) * (np.power(norm, 2.1).astype(np.float32) + 0.12 * np.power(norm, 4.0).astype(np.float32))
    vig = np.clip(vig, 0.28, 1.0).astype(np.float32)
    # LRU eviction
    if len(_VIG_CACHE) >= _CACHE_MAX:
        oldest = next(iter(_VIG_CACHE))
        del _VIG_CACHE[oldest]
    _VIG_CACHE[key] = vig
    return vig


def clear_vignetting_cache() -> None:
    _VIG_CACHE.clear()


def apply_vignetting(base: np.ndarray, strength: float) -> np.ndarray:
    """
    Apply radial vignetting to an image buffer (camera image-space).

    ------------------------------------------------------------
    Inputs:
      base     : (H, W, 3) uint8 or float32 image (e.g., 640×640 FOV frame).
      strength : 0.0..0.92 vignetting strength (0 = off)
    Returns:
      base : vignetted, clipped to [0,255].
    Notes:
      - Physical cos4-based, exponent 2.1 + 4th order, asymmetric centre, clamp 0.28-1.0
      - Fast LRU cache quantized to 1%, bypass at strength<1e-3.
    ------------------------------------------------------------
    """
    if strength <= 1e-3:
        return base
    h, w = base.shape[0], base.shape[1]
    vig = _get_vig_mask(h, w, float(strength))
    if base.dtype == np.uint8:
        base_f = base.astype(np.float32)
        base_f *= vig[:, :, None]
        return np.clip(base_f, 0, 255).astype(np.uint8)
    base *= vig[:, :, None]
    return np.clip(base, 0, 255)