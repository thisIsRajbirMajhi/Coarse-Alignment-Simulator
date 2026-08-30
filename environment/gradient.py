"""
Module: environment.gradient
Purpose: Vertical sky gradient generation (zenith → horizon).
Physics: Linear lerp of bg_top (zenith darker) → bg_bottom (horizon brighter)
         plus slight blue/G bias for skylight scattering at low elevation.
Public API: build_gradient
Notes: Output is float32 (H, W, 3) before vignetting/haze; crystal sharp.
"""

import numpy as np

# ============================================================
# SECTION: Sky Gradient Builder
# ============================================================

def build_gradient(
    width: int,
    height: int,
    bg_top: int,
    bg_bottom: int,
) -> np.ndarray:
    """
    Build vertical sky gradient buffer.

    ------------------------------------------------------------
    Inputs:
      width, height : scene resolution (px)
      bg_top        : zenith color (0..60, darker)
      bg_bottom     : horizon color (0..80, brighter)
    Returns:
      base : np.ndarray (H, W, 3) float32 in [0,255]
    Notes:
      - Channel 0 (B) gets +4.0 at horizon, channel 1 (G) +1.2 for
        physically-plausible skylight tint (Rayleigh-like blue bias).
      - Caller is responsible for merging haze/vignetting afterwards.
    ------------------------------------------------------------
    """
    # Vertical interpolation: top -> bottom
    grad_vals = np.linspace(float(bg_top), float(bg_bottom), height, dtype=np.float32)[:, None]
    base = np.full((height, width, 3), 0, dtype=np.float32)
    for c in range(3):
        base[:, :, c] = grad_vals

    # Slight blue bias for skylight — horizon more blue than zenith
    horizon_mix = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    base[:, :, 0] += horizon_mix * 4.0   # B boost at bottom
    base[:, :, 1] += horizon_mix * 1.2   # G slight
    base = np.clip(base, 0, 255)
    return base
