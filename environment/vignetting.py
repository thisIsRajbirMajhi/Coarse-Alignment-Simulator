# environment/vignetting.py - Physical cos4 + off-axis lens vignetting
#
# PHYSICAL MODEL: Real lens vignetting follows cos^4(θ) + mechanical shading.
#   Previous 1.8 exponent approximated perception; new model uses exponent 2.1
#   (closer to cos4 at 4° FOV) with slight asymmetric tilt for realism.
#   Still sensor/image-space (FOV centre), follows camera.

import math
import threading

import numpy as np

# Cache for vignetting masks — key: (h,w, quantized_strength)
_VIG_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_VIG_LOCK = threading.Lock()
_CACHE_MAX = 16


def _get_vig_mask(h: int, w: int, strength: float) -> np.ndarray:
    # Quantize strength to 1% to avoid cache explosion
    q = int(round(float(strength) * 100))
    key = (h, w, q)
    with _VIG_LOCK:
        hit = _VIG_CACHE.get(key)
        if hit is not None:
            return hit
    # Single-pass radial field with asymmetric centre (sensor tilt 1.5% down).
    # Previous version computed r/max_r then discarded it — now r_eff only.
    ys, xs = np.ogrid[:h, :w]
    cx, cy = w * 0.5, h * 0.5
    max_r = math.sqrt(cx * cx + cy * cy)
    cy_eff = cy * 1.015
    dx = xs - cx
    dy = ys - cy_eff
    # sqrt + normalize in float32; norm^2.1 + 0.12*norm^4 (cos4 approx for 4° FOV)
    r_eff = np.sqrt(dx * dx + dy * dy, dtype=np.float32)
    norm = r_eff / (max_r + 1e-6)
    np.clip(norm, 0, 1, out=norm)
    n2 = norm * norm
    # norm^2.1 = norm^2 * norm^0.1 (one pow instead of two)
    falloff = n2 * np.power(norm, 0.1, dtype=np.float32) + 0.12 * (n2 * n2)
    vig = 1.0 - (q / 100.0) * falloff
    vig = np.clip(vig, 0.28, 1.0).astype(np.float32, copy=False)
    with _VIG_LOCK:
        if len(_VIG_CACHE) >= _CACHE_MAX:
            oldest = next(iter(_VIG_CACHE))
            del _VIG_CACHE[oldest]
        _VIG_CACHE[key] = vig
    return vig


def clear_vignetting_cache() -> None:
    with _VIG_LOCK:
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
        # In-place friendly: single float32 temp, out= ops avoid extra allocs.
        base_f = base.astype(np.float32, copy=True)
        base_f *= vig[:, :, None]
        np.clip(base_f, 0, 255, out=base_f)
        return base_f.astype(np.uint8, copy=False)
    np.multiply(base, vig[:, :, None], out=base, casting="unsafe")
    return np.clip(base, 0, 255, out=base)