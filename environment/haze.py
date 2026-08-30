"""
Module: environment.haze
Purpose: Low-frequency haze/fog texture generation and storage.
Physics: Filtered white noise (downsampled 8× → cubic upscale → Gaussian
         blur σ=12 → normalized to [-1,1]) scaled by haze_strength * 8.0.
Public API: build_haze_field, haze_modulation
Notes: haze field is stored as float32 (H, W) for cheap dynamic drift.
"""

import cv2
import numpy as np

# ============================================================
# SECTION: Haze Field Generation
# ============================================================

def build_haze_field(
    width: int,
    height: int,
    rng: np.random.Generator,
    haze_strength: float,
) -> np.ndarray:
    """
    Generate the haze field used to perturb the sky gradient.

    ------------------------------------------------------------
    Inputs:
      width, height : scene resolution
      rng           : seeded Generator for reproducibility
      haze_strength : 0.0..1.0 (0 = no haze)
    Returns:
      haze_base : (H, W) float32 in ~[-8, 8] — add to base as haze[:,:,None]
                  Zero-filled if haze_strength ≈ 0.
    Notes:
      - Downsamples noise to (H/8, W/8) for performance; 5000×5000 → 625×625.
    ------------------------------------------------------------
    """
    if haze_strength <= 1e-6:
        return np.zeros((height, width), dtype=np.float32)
    small_h = max(1, height // 8)
    small_w = max(1, width // 8)
    noise_small = rng.normal(0, 1, (small_h, small_w)).astype(np.float32)
    noise_full = cv2.resize(noise_small, (width, height), interpolation=cv2.INTER_CUBIC)
    noise_full = cv2.GaussianBlur(noise_full, (0, 0), sigmaX=12, sigmaY=12)
    n_min, n_max = noise_full.min(), noise_full.max()
    if n_max > n_min:
        noise_full = (noise_full - n_min) / (n_max - n_min) * 2 - 1  # -> [-1,1]
    haze = noise_full * float(haze_strength) * 8.0
    return haze.astype(np.float32)

# ============================================================
# SECTION: Dynamic Drift Helper
# ============================================================

def haze_modulation(time: float) -> float:
    """
    Small sinusoidal brightness modulation for dynamic mode.

    Replaces true advection (np.roll) which would double-add haze.
    Adds ±1.2 DN at 0.3 rad/s — subtle wind shimmer.
    """
    return float(np.sin(time * 0.3) * 1.2)
