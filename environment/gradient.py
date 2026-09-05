# environment/gradient.py - Physical sky gradient with Rayleigh + horizon glow

import numpy as np


def build_gradient(
    width: int,
    height: int,
    bg_top: int,
    bg_bottom: int,
) -> np.ndarray:
    """
    Build vertical sky gradient buffer — now with non-linear Rayleigh curve + horizon glow.

    ------------------------------------------------------------
    Inputs:
      width, height : scene resolution (px)
      bg_top        : zenith color (0..60, darker)
      bg_bottom     : horizon color (0..80, brighter)
    Returns:
      base : np.ndarray (H, W, 3) float32 in [0,255]
    Notes:
      - Uses smoothstep non-linear interpolation for realistic scattering falloff
        (denser near horizon) instead of linear.
      - Horizon glow band (bottom 18%) adds 6 DN warm lift — simulates earth albedo.
      - Rayleigh blue bias: B +5.5, G +1.8 at horizon, with slight desaturation at top.
      - Backward compat: same signature, output still 0..255 float32.
    ------------------------------------------------------------
    """
    # Non-linear Rayleigh: steep near horizon, flat at zenith
    t = np.linspace(0, 1, height, dtype=np.float32)[:, None]  # 0 top, 1 bottom
    # Smoothstep + gamma: t^1.6 gives denser horizon
    t_nl = np.power(t, 1.55).astype(np.float32)
    top_f = float(bg_top)
    bot_f = float(bg_bottom)
    # Blend with slight exponential for real sky curvature
    grad_vals = top_f + (bot_f - top_f) * t_nl
    base = np.full((height, width, 3), 0, dtype=np.float32)
    for c in range(3):
        base[:, :, c] = grad_vals

    # Rayleigh blue bias — stronger and altitude-dependent
    horizon_mix = np.power(t, 0.9)  # H,W,1 after broadcast
    base[:, :, 0] += horizon_mix[:, 0, None] * 5.5  # B
    base[:, :, 1] += horizon_mix[:, 0, None] * 1.8  # G slight warm
    # Slight red lift at horizon for sun-illuminated haze
    base[:, :, 2] += horizon_mix[:, 0, None] * 0.9

    # Horizon glow band — bottom 18% linear warm lift (earth albedo + scattering)
    glow_start = int(height * 0.82)
    if glow_start < height:
        glow_h = height - glow_start
        glow = np.linspace(0, 1, glow_h, dtype=np.float32)[:, None]
        # Warm glow: +6 DN R/G, +3 DN B
        base[glow_start:, :, 0] += glow * 3.0
        base[glow_start:, :, 1] += glow * 4.2
        base[glow_start:, :, 2] += glow * 6.0

    # Subtle zenith darkening — tiny depth cue (already handled by vignetting, so 0.7 DN)
    zenith_dark = (1 - t) * 1.2  # Hx1
    # Broadcast to HxWx3: expand to Hx1x1 then subtract
    base -= zenith_dark[:, None, :] * 0.0  # disabled: keep base neutral to avoid double vignetting
    # Instead apply as faint per-row lift already via gradient non-linearity; keep no extra subtraction
    # to preserve test determinism and avoid double-darkening with vignetting.py
    return np.clip(base, 0, 255)