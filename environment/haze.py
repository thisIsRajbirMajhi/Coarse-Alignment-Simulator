# environment/haze.py - Low-frequency haze/fog texture generation and storage
#
# PHYSICAL NOTE: This world haze adds low-frequency brightness noise (±8 DN)
#   to the sky gradient — it is a plausible ambient skylight variation, NOT
#   true fog attenuation (which would reduce contrast and desaturate toward
#   grey, as done by disturbance.atmospheric for image-space fog). The scalar
#   haze_modulation (±1.2 DN shimmer) is also a cheap wind hint, NOT true
#   advected haze (which would require scrolling the noise field). This is
#   intentional: cheap, visually plausible, and avoids double-adding haze if
#   we rolled the field each tick.

import cv2
import numpy as np

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

def haze_modulation(time: float) -> float:
    """
    Small sinusoidal brightness modulation for dynamic mode.

    Replaces true advection (np.roll) which would double-add haze and require
    full-frame scroll each tick. Adds ±1.2 DN at 0.3 rad/s — subtle wind
    shimmer, cheap and plausible. NOT true moving fog (see module header).
    """
    return float(np.sin(time * 0.3) * 1.2)