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
    # Non-linear Rayleigh: steep near horizon, flat at zenith.
    # Lighter: work on a (H,1) column, broadcast to (H,W,3) at the end —
    # avoids full-res temporaries and per-channel assignment loops.
    t = np.linspace(0, 1, height, dtype=np.float32)[:, None]  # 0 top, 1 bottom
    # Smoothstep + gamma: t^1.55 gives denser horizon
    t_nl = np.power(t, 1.55, dtype=np.float32)
    horizon_mix = np.power(t, 0.9, dtype=np.float32)
    top_f = float(bg_top)
    bot_f = float(bg_bottom)
    # Blend with slight exponential for real sky curvature
    grad_col = top_f + (bot_f - top_f) * t_nl  # (H,1) float32
    # Rayleigh blue bias — altitude-dependent, applied per-channel on column
    b_col = grad_col + horizon_mix * 5.5
    g_col = grad_col + horizon_mix * 1.8
    r_col = grad_col + horizon_mix * 0.9

    # Horizon glow band — bottom 18% linear warm lift (earth albedo + scattering)
    glow_start = int(height * 0.82)
    if glow_start < height:
        glow_h = height - glow_start
        glow = np.linspace(0, 1, glow_h, dtype=np.float32)[:, None]
        # Warm glow: +3 DN B, +4.2 DN G, +6 DN R
        b_col[glow_start:] += glow * 3.0
        g_col[glow_start:] += glow * 4.2
        r_col[glow_start:] += glow * 6.0

    # Broadcast columns to full width in one concat (single H*W*3 alloc).
    base = np.concatenate(
        [np.broadcast_to(b_col, (height, width))[..., None],
         np.broadcast_to(g_col, (height, width))[..., None],
         np.broadcast_to(r_col, (height, width))[..., None]],
        axis=2,
    ).astype(np.float32, copy=False)
    # NOTE: zenith darkening intentionally omitted — vignetting.py owns
    # edge falloff (image-space). Keeps base neutral and deterministic.
    return np.clip(base, 0, 255, out=base)