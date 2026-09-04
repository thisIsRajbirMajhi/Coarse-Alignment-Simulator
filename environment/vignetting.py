# environment/vignetting.py - Radial edge-darkening (vignetting) for optical realism
#
# PHYSICAL MODEL: Real lens vignetting is a SENSOR/IMAGE-SPACE effect —
#   darkening is centered on the camera's optical axis (FOV centre), NOT on
#   the world centre. Previous implementation baked vignetting into the
#   5000×5000 world buffer (dark corners at world 2500,2500), so panning the
#   camera did not move the dark corners. Correct model: apply vignetting to
#   the 640×640 camera FOV frame after capture (so it follows the camera).
#   This module is now used at camera image stage (PTZCamera.capture post-
#   crop or MainWindow post-capture), NOT during Scene._build_background.

import math

import numpy as np

# Cache for vignetting masks — key: (h,w, quantized_strength)
_VIG_CACHE: dict[tuple[int,int,int], np.ndarray] = {}
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
    vig = 1.0 - (q / 100.0) * (r / max_r) ** 1.8
    vig = np.clip(vig, 0.35, 1.0).astype(np.float32)
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
                 Modified efficiently; works for any size. If uint8, it is
                 converted to float32 internally for multiplication then
                 clipped back to uint8 range.
      strength : 0.0..0.92 vignetting strength (0 = off)
    Returns:
      base : same array shape, vignetted, clipped to [0,255] (same dtype
             as input after clipping; float input stays float, uint8 stays
             uint8 after conversion).
    Notes:
      - Centered on image centre (w*0.5, h*0.5) — follows camera, not world.
      - strength ~0.0 bypasses computation entirely (fast path).
      - max_r is corner distance; exponent 1.8 gives smooth perceptual falloff.
      - Clamped to [0.35, 1.0] to avoid pure black corners.
    ------------------------------------------------------------
    """
    if strength <= 1e-3:
        return base
    h, w = base.shape[0], base.shape[1]
    vig = _get_vig_mask(h, w, float(strength))
    # Handle uint8 camera frames (640×640) correctly: promote to float, multiply, clip back.
    if base.dtype == np.uint8:
        base_f = base.astype(np.float32)
        base_f *= vig[:, :, None]
        return np.clip(base_f, 0, 255).astype(np.uint8)
    # float32 path (legacy world-stage float buffer)
    base *= vig[:, :, None]
    return np.clip(base, 0, 255)