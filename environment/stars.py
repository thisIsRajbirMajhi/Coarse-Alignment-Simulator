"""
Module: environment.stars
Purpose: Starfield / clutter generation, storage, and rendering helpers.
Physics: Magnitude distribution via exponential tiers + 2% rare-bright
         tail; size 1 px if mag ≤90 else 3×3 soft kernel (0.5/0.7/1.0).
Public API: generate_starfield, draw_static_stars, draw_twinkling_stars
Notes: Keeps crystal sharp — no Gaussian blur on star composite.
"""

import numpy as np

# ============================================================
# SECTION: Generation
# ============================================================

def generate_starfield(
    width: int,
    height: int,
    rng: np.random.Generator,
    star_count: int,
    star_brightness_scale: float,
) -> dict:
    """
    Generate star metadata.

    ------------------------------------------------------------
    Inputs:
      width, height         : scene bounds
      rng                   : seeded Generator
      star_count            : 0..4000
      star_brightness_scale : 0.5..1.8
    Returns:
      dict with keys:
        xy          : (N,2) int — positions
        brightness  : (N,) float32 — base mag 0..180 (scaled)
        sizes       : (N,) int32 — 1 or 2 (1=single pixel, 2=3×3)
        phases      : (N,) float32 — twinkle phase [0,2π)
        freqs       : (N,) float32 — twinkle freq [0.8,3.5)
        subpix      : (N,2) float — subpixel jitter hint
    ------------------------------------------------------------
    """
    star_count = int(np.clip(star_count, 0, 4000))
    if star_count == 0:
        return {
            "xy": np.zeros((0, 2), dtype=int),
            "brightness": np.array([], dtype=np.float32),
            "sizes": np.array([], dtype=np.int32),
            "phases": np.array([], dtype=np.float32),
            "freqs": np.array([], dtype=np.float32),
            "subpix": np.zeros((0, 2)),
        }

    xy = rng.integers(low=[0, 0], high=[width, height], size=(star_count, 2))

    # Magnitude tiers driven by exponential samples
    mag = np.empty(star_count, dtype=np.float32)
    exp_samples = rng.exponential(scale=1.0, size=star_count)
    dim_mask = exp_samples < 0.7
    med_mask = (exp_samples >= 0.7) & (exp_samples < 1.8)
    bright_mask = exp_samples >= 1.8
    mag[dim_mask] = rng.integers(35, 60, size=np.count_nonzero(dim_mask))
    mag[med_mask] = rng.integers(60, 85, size=np.count_nonzero(med_mask))
    mag[bright_mask] = rng.integers(85, 110, size=np.count_nonzero(bright_mask))
    rare = rng.random(star_count) < 0.02
    mag[rare] = rng.integers(95, 130, size=np.count_nonzero(rare))

    # Global scale
    mag = mag * float(star_brightness_scale)
    brightness = np.clip(mag, 0, 180).astype(np.float32)
    sizes = np.where(mag > 90, 2, 1).astype(np.int32)

    phases = rng.uniform(0, 2 * np.pi, size=star_count).astype(np.float32)
    freqs = rng.uniform(0.8, 3.5, size=star_count).astype(np.float32)
    subpix = rng.normal(0, 0.15, size=(star_count, 2))

    return {
        "xy": xy,
        "brightness": brightness,
        "sizes": sizes,
        "phases": phases,
        "freqs": freqs,
        "subpix": subpix,
    }

# ============================================================
# SECTION: Drawing Helpers (shared loop extracted to avoid duplication)
# ============================================================

def _draw_star_into(frame: np.ndarray, x: int, y: int, brightness: float, size: int) -> None:
    """
    Draw a single star into `frame` (H,W,3) uint8.

    Size 1: single pixel. Size 2: 3×3 kernel with weights
            center 1.0, edge 0.7, corner 0.5 — max-blended.
    """
    h, w = frame.shape[0], frame.shape[1]
    if size == 1:
        if 0 <= y < h and 0 <= x < w:
            b = int(brightness)
            frame[y, x] = (b, b, b)
    else:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w:
                    wgt = 0.5 if abs(dx) + abs(dy) == 2 else (1.0 if dx == 0 and dy == 0 else 0.7)
                    val = int(float(brightness) * wgt)
                    frame[yy, xx] = np.maximum(frame[yy, xx], [val, val, val])

def draw_static_stars(
    static: np.ndarray,
    xy: np.ndarray,
    brightness: np.ndarray,
    sizes: np.ndarray,
) -> None:
    """Composite static starfield into `static` (in-place)."""
    for (x, y), b, sz in zip(xy, brightness, sizes):
        _draw_star_into(static, int(x), int(y), float(b), int(sz))

def draw_twinkling_stars(
    frame: np.ndarray,
    xy: np.ndarray,
    base_brightness: np.ndarray,
    sizes: np.ndarray,
    phases: np.ndarray,
    freqs: np.ndarray,
    time: float,
) -> None:
    """
    Composite twinkling stars into `frame` (in-place).

    Brightness per star: base * (1 + 0.18*sin(freq*t + phase)) — ±18% variation.
    """
    for (x, y), b0, sz, phase, freq in zip(xy, base_brightness, sizes, phases, freqs):
        tw = 1.0 + 0.18 * float(np.sin(float(freq) * time + float(phase)))
        b = float(np.clip(float(b0) * tw, 0, 180))
        _draw_star_into(frame, int(x), int(y), b, int(sz))
