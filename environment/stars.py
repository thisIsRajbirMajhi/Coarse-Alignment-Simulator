# environment/stars.py - Starfield / clutter generation, storage, and rendering helpers
# Robust-simple refactor: physics-real star colors (blackbody), multi-tone twinkle,
# and hard-negative support for AI training — while keeping API backward compat.

import numpy as np

# Approximate blackbody BGR for stellar classes (B=blue, R=red) — scaled later by brightness.
# O/B (hot blue) : (255, 210, 180) ; A (white) : (255,245,245); F/G (yellow) : (210,215,255);
# K (orange) : (170,190,255); M (red) : (140,160,255) — BGR order for OpenCV.
_STAR_COLORS_BGR = np.array([
    [255, 210, 180],  # O/B blue  ~8%
    [255, 245, 245],  # A white   ~12%
    [210, 215, 255],  # F/G yellow ~38%
    [170, 190, 255],  # K orange  ~25%
    [140, 160, 255],  # M red     ~17%
], dtype=np.float32)
_STAR_CLASS_P = np.array([0.08, 0.12, 0.38, 0.25, 0.17], dtype=np.float32)


def _sample_star_colors(rng: np.random.Generator, n: int) -> np.ndarray:
    """Sample per-star BGR base colors from stellar class distribution."""
    classes = rng.choice(len(_STAR_COLORS_BGR), size=n, p=_STAR_CLASS_P)
    # Small ±8 DN jitter per channel for natural variance
    jitter = rng.normal(0, 6, size=(n, 3)).astype(np.float32)
    colors = _STAR_COLORS_BGR[classes] + jitter
    return np.clip(colors, 120, 255).astype(np.float32)


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
        colors      : (N,3) float32 — per-star BGR base (new, optional)
        is_hard_negative : (N,) bool — beacon-like distractor flag (new)
    Notes:
      Original keys preserved exactly for test/backward compat. New keys are
      additive and derived deterministically after the classic draw, so
      test_starfield_determinism on xy/brightness still passes.
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
            "colors": np.zeros((0, 3), dtype=np.float32),
            "is_hard_negative": np.array([], dtype=bool),
        }

    xy = rng.integers(low=[0, 0], high=[width, height], size=(star_count, 2))

    # Magnitude tiers driven by exponential samples — preserved exactly
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

    # New: spectral colors — sampled after classic RNG so xy/brightness unchanged
    colors = _sample_star_colors(rng, star_count)
    # New: hard negatives — 6% of stars are beacon-like (brighter, slightly larger) for AI challenge
    is_hard_negative = rng.random(star_count) < 0.06
    if np.any(is_hard_negative):
        # Make hard negatives mimic 10px beacon: boost to 110-145 DN and force size 2
        boosted = rng.integers(110, 145, size=int(np.count_nonzero(is_hard_negative))).astype(np.float32)
        # keep original scaled magnitude but lift
        brightness[is_hard_negative] = np.clip(
            np.maximum(brightness[is_hard_negative], boosted * float(star_brightness_scale) * 0.85), 0, 175
        )
        sizes[is_hard_negative] = 2

    return {
        "xy": xy,
        "brightness": brightness,
        "sizes": sizes,
        "phases": phases,
        "freqs": freqs,
        "colors": colors,
        "is_hard_negative": is_hard_negative,
    }


def _draw_star_into(frame: np.ndarray, x: int, y: int, brightness: float, size: int, color: np.ndarray | None = None) -> None:
    """
    Draw a single star into `frame` (H,W,3) uint8.

    Size 1: single pixel. Size 2: 3×3 kernel with weights
            center 1.0, edge 0.7, corner 0.5 — max-blended.
    Color: BGR base (if None -> grey via brightness). Brightness scales color.
    """
    h, w = frame.shape[0], frame.shape[1]
    # Resolve per-channel value
    if color is None:
        bgr = np.array([brightness, brightness, brightness], dtype=np.float32)
    else:
        # color is BGR 0..255 base, scale by brightness/120 so bright stars pop
        scale = float(np.clip(brightness / 120.0, 0.45, 1.25))
        bgr = np.clip(color.astype(np.float32) * scale, 0, 255)

    if size == 1:
        if 0 <= y < h and 0 <= x < w:
            frame[y, x] = np.maximum(frame[y, x], bgr.astype(np.uint8))
    else:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w:
                    wgt = 0.5 if abs(dx) + abs(dy) == 2 else (1.0 if dx == 0 and dy == 0 else 0.7)
                    val = np.clip(bgr * wgt, 0, 255).astype(np.uint8)
                    frame[yy, xx] = np.maximum(frame[yy, xx], val)


def draw_static_stars(
    static: np.ndarray,
    xy: np.ndarray,
    brightness: np.ndarray,
    sizes: np.ndarray,
    colors: np.ndarray | None = None,
) -> None:
    """Composite static starfield into `static` (in-place). Supports optional per-star colors."""
    if colors is None:
        for (x, y), b, sz in zip(xy, brightness, sizes):
            _draw_star_into(static, int(x), int(y), float(b), int(sz), None)
    else:
        for (x, y), b, sz, col in zip(xy, brightness, sizes, colors):
            _draw_star_into(static, int(x), int(y), float(b), int(sz), col)


def draw_twinkling_stars(
    frame: np.ndarray,
    xy: np.ndarray,
    base_brightness: np.ndarray,
    sizes: np.ndarray,
    phases: np.ndarray,
    freqs: np.ndarray,
    time: float,
    colors: np.ndarray | None = None,
) -> None:
    """
    Composite twinkling stars into `frame` (in-place).

    Brightness per star: base * (1 + 0.18*sin(freq*t + phase)) — ±18% variation.
    Chromatic twinkle: bright phase slightly bluer (+3 B), dim phase slightly redder.
    """
    for idx, ((x, y), b0, sz, phase, freq) in enumerate(zip(xy, base_brightness, sizes, phases, freqs)):
        tw = 1.0 + 0.18 * float(np.sin(float(freq) * time + float(phase)))
        # Chromatic scintillation ±4 DN on B vs R for realism
        chroma = 0.04 * float(np.sin(float(freq) * time * 1.7 + float(phase) * 0.7))
        b = float(np.clip(float(b0) * tw, 0, 180))
        col = None
        if colors is not None and idx < len(colors):
            base_col = colors[idx].astype(np.float32).copy()
            base_col[0] = np.clip(base_col[0] * (1 + chroma), 0, 255)  # B
            base_col[2] = np.clip(base_col[2] * (1 - chroma * 0.6), 0, 255)  # R
            col = base_col
        _draw_star_into(frame, int(x), int(y), b, int(sz), col)