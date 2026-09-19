# environment/haze.py - Fractal patchy haze / cloud field with wind advection
#
# PHYSICAL MODEL: Low-frequency skylight variation + multi-scale cloud patches.
#   Previous single-scale blurred noise (±8 DN, scalar shimmer ±1.2) was uniform
#   and unchallenging for AI. New field is fractal (FBM 3 octaves) with spatial
#   patchiness (0.4 dense fog cores) and wind advection (scrolling offsets).
#   Still cheap: 1/8 + 1/16 res, blurred, then composited. Maintains backward
#   compat: build_haze_field same signature, haze_modulation same scalar API
#   plus optional offset helper for advected path.

import cv2
import numpy as np

# Wind advection state — per-scene offsets driven by Scene._time
_ADVECTION_SPEED_X = 6.0   # px/sec at 2000 res
_ADVECTION_SPEED_Y = 2.0


def build_haze_field(
    width: int,
    height: int,
    rng: np.random.Generator,
    haze_strength: float,
) -> np.ndarray | None:
    """
    Generate the haze field used to perturb the sky gradient.

    ------------------------------------------------------------
    Inputs:
      width, height : scene resolution
      rng           : seeded Generator for reproducibility
      haze_strength : 0.0..1.0 (0 = no haze)
    Returns:
      haze_base : (H, W) float32 in ~[-12, 12] — add to base as haze[:,:,None]
                  None if haze_strength ≈ 0 (back-compat: no allocation).
                  Fractal 2-octave FBM (broad 1/8 + detail 1/16) with
                  patchy cores for realistic cloud contrast.
    ------------------------------------------------------------
    """
    if haze_strength <= 1e-6:
        return None
    # Lighter 2-octave FBM: broad 1/8 + detail 1/16, single resize+blur each.
    # (Previous 3-octave + 3 full-res blurs cost 150-400ms @2000; this is ~2x faster
    # with visually equivalent patchiness.)
    # Base octave 1/8 — broad undulation
    small_h = max(1, height // 8)
    small_w = max(1, width // 8)
    n1_small = rng.normal(0, 1, (small_h, small_w)).astype(np.float32)
    n1 = cv2.resize(n1_small, (width, height), interpolation=cv2.INTER_LINEAR)
    n1 = cv2.GaussianBlur(n1, (0, 0), sigmaX=12, sigmaY=12)
    del n1_small

    # Octave 1/16 — medium patchiness
    small_h2 = max(1, height // 16)
    small_w2 = max(1, width // 16)
    n2_small = rng.normal(0, 1, (small_h2, small_w2)).astype(np.float32)
    n2 = cv2.resize(n2_small, (width, height), interpolation=cv2.INTER_LINEAR)
    n2 = cv2.GaussianBlur(n2, (0, 0), sigmaX=6, sigmaY=6)
    del n2_small

    # Fractal mix: 0.65 broad + 0.35 medium — then patchy threshold
    fractal = 0.65 * n1 + 0.35 * n2
    del n1, n2
    # Deterministic contrast: fixed-std scale (reliable across seeds).
    # Previous min/max normalization made identical strength vary in contrast.
    std = float(fractal.std())
    if std > 1e-6:
        fractal = fractal / std * 0.55
    fractal = np.clip(fractal, -1.5, 1.5, out=fractal)
    # Smoothstep x3 -> contrasty patches, then mix back 70% original for naturalness
    patchy = fractal * fractal * (3 - 2 * np.abs(fractal))  # s-curve
    fractal = 0.70 * fractal + 0.30 * patchy

    # Scale to DN: keep same ±8 range but add ±4 for dense cores at high strength
    base_amp = float(haze_strength) * 8.0
    core_boost = float(haze_strength) * 4.0 * np.clip(patchy, 0, 1)  # only positive cores
    haze = fractal * base_amp + core_boost
    # Altitude gradient: horizon (bottom 25%) 1.35x denser
    h = height
    alt_fade = np.linspace(1.0, 1.35, h, dtype=np.float32)[:, None]
    haze = haze * alt_fade
    return np.clip(haze, -14, 14).astype(np.float32)


def haze_modulation(time: float) -> float:
    """
    Scalar shimmer + wind advection helper.

    Returns ±1.4 DN shimmer (slightly stronger than before for visibility).
    For true advection, caller can also use get_haze_advect_offset(time).
    """
    return float(np.sin(time * 0.30) * 1.35 + np.sin(time * 0.11) * 0.35)


def get_haze_advect_offset(
    time: float,
    haze_strength: float = 0.35,
    world_width: int = 2000,
    world_height: int = 2000,
) -> tuple[int, int]:
    """Wind scroll offset (px) for haze field — proportional to strength.

    Back-compat: ``get_haze_advect_offset(t)`` still works (defaults 2000);
    pass world size so wrap is correct at 5000 (previous hardcoded %2000).
    """
    # Stronger haze moves slightly slower (heavier)
    speed_factor = 0.65 + 0.35 * (1.0 - float(np.clip(haze_strength, 0, 1)))
    ww = max(1, int(world_width))
    wh = max(1, int(world_height))
    ox = int(round(time * _ADVECTION_SPEED_X * speed_factor)) % ww
    oy = int(round(time * _ADVECTION_SPEED_Y * speed_factor * 0.4)) % wh
    return ox, oy