# disturbance/image_noise.py - Physical image noise stack — hot-pixel-persistent S&P, Gaussian, Poisson
# Robust-simple: S&P now supports fixed hot pixels vs transient, order is Poisson -> Gaussian -> S&P
# (shot before read before defects) for physical correctness, yet backward-compat API kept.

from __future__ import annotations

import numpy as np

from disturbance.constants import (
    GAUSSIAN_SIGMA_LIMITS,
    GAUSSIAN_SIGMA_MAX_USER,
    SALT_PEPPER_LIMITS,
)

# Persistent hot-pixel map — fixed positions that survive many frames (real sensor defects)
# Key: (h,w) -> (ys, xs, is_salt) ; regenerated on size change or reset
_HOT_PIXEL_CACHE: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
_HOT_PIXEL_PERSISTENT_RATIO = 0.35  # 35% of S&P are persistent hot pixels, 65% transient


def clear_hot_pixel_cache() -> None:
    _HOT_PIXEL_CACHE.clear()


def _get_persistent_hot_pixels(h: int, w: int, density: float, salt_vs_pepper: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Get or create persistent hot pixel map for given frame size."""
    key = (h, w)
    if key not in _HOT_PIXEL_CACHE:
        # Use 0.8 * density as persistent pool (slightly fewer than transient total)
        persist_density = float(density) * _HOT_PIXEL_PERSISTENT_RATIO * 0.5
        n = int(h * w * persist_density)
        n = int(np.clip(n, 4, 800))
        ys = np.random.randint(0, h, size=n)
        xs = np.random.randint(0, w, size=n)
        is_salt = np.random.random(n) < float(salt_vs_pepper)
        _HOT_PIXEL_CACHE[key] = (ys, xs, is_salt)
    return _HOT_PIXEL_CACHE[key]


def _clip_frame(frame: np.ndarray) -> np.ndarray:
    return np.clip(frame, 0, 255)


def apply_salt_pepper(
    frame: np.ndarray,
    density: float = 0.10,
    *,
    salt_vs_pepper: float = 0.5,
    persistent: bool | None = None,
) -> np.ndarray:
    """
    Salt & Pepper — fixed hot pixels + transient speckles.

    Real sensor: ~35% defects are persistent (same position each frame),
    65% are transient (random). This mix is *challenging* for AI: persistent
    hot pixels look like beacons (fixed bright dot) vs moving beacon.

    Args:
      frame: HxWx3 uint8
      density: fraction corrupted [0,0.20] — 0.10 ≈ 10% (spec)
      salt_vs_pepper: ratio of salt vs pepper, 0.5 = equal
      persistent: None = auto-mix (35/65), True = only persistent, False = only transient

    Returns same shape/dtype.
    """
    if frame.size == 0 or density <= 1e-9:
        return frame
    density = float(np.clip(density, 0.0, 0.20))
    out = frame.copy()
    h, w = frame.shape[:2]

    # Split density into persistent vs transient
    if persistent is None:
        persist_dens = density * _HOT_PIXEL_PERSISTENT_RATIO
        transient_dens = density * (1 - _HOT_PIXEL_PERSISTENT_RATIO)
    elif persistent:
        persist_dens = density
        transient_dens = 0.0
    else:
        persist_dens = 0.0
        transient_dens = density

    # Persistent hot pixels — same positions for this (h,w)
    if persist_dens > 1e-9:
        # Scale persistent cache to requested density: subsample cache
        cache_ys, cache_xs, cache_is_salt = _get_persistent_hot_pixels(h, w, density, float(salt_vs_pepper))
        # Adjust count to persist_dens
        want = int(h * w * float(persist_dens))
        if want > 0:
            # Subsample cache deterministically per call: random choice without replacement
            idx = np.random.choice(len(cache_ys), size=min(want, len(cache_ys)), replace=False) if len(cache_ys) > 0 else np.array([], dtype=int)
            py = cache_ys[idx][~cache_is_salt[idx]] if len(idx) > 0 else np.array([], dtype=int)
            px = cache_xs[idx][~cache_is_salt[idx]] if len(idx) > 0 else np.array([], dtype=int)
            sy = cache_ys[idx][cache_is_salt[idx]] if len(idx) > 0 else np.array([], dtype=int)
            sx = cache_xs[idx][cache_is_salt[idx]] if len(idx) > 0 else np.array([], dtype=int)
            if len(py) > 0:
                if out.ndim == 3:
                    out[py, px, :] = 0
                else:
                    out[py, px] = 0
            if len(sy) > 0:
                if out.ndim == 3:
                    out[sy, sx, :] = 255
                else:
                    out[sy, sx] = 255
        # If want > cache size, fill remainder with transient-like
        if want > len(cache_ys):
            extra = want - len(cache_ys)
            ys2 = np.random.randint(0, h, size=extra)
            xs2 = np.random.randint(0, w, size=extra)
            salt_n2 = int(extra * float(salt_vs_pepper))
            if extra - salt_n2 > 0:
                if out.ndim == 3:
                    out[ys2[salt_n2:], xs2[salt_n2:], :] = 0
                else:
                    out[ys2[salt_n2:], xs2[salt_n2:]] = 0
            if salt_n2 > 0:
                if out.ndim == 3:
                    out[ys2[:salt_n2], xs2[:salt_n2], :] = 255
                else:
                    out[ys2[:salt_n2], xs2[:salt_n2]] = 255

    # Transient speckles — random each frame
    if transient_dens > 1e-9:
        total = int(h * w * float(transient_dens))
        if total > 0:
            ys = np.random.randint(0, h, size=total)
            xs = np.random.randint(0, w, size=total)
            salt_n = int(total * float(salt_vs_pepper))
            if total - salt_n > 0:
                if out.ndim == 3:
                    out[ys[salt_n:], xs[salt_n:], :] = 0
                else:
                    out[ys[salt_n:], xs[salt_n:]] = 0
            if salt_n > 0:
                if out.ndim == 3:
                    out[ys[:salt_n], xs[:salt_n], :] = 255
                else:
                    out[ys[:salt_n], xs[:salt_n]] = 255
    return out


def apply_gaussian_noise(
    frame: np.ndarray,
    sigma: float = 8.0,
    *,
    max_sigma: float = 20.0,
) -> np.ndarray:
    """
    Additive Gaussian — N(0, sigma^2) per pixel/channel, clipped.

    Max StdDev 20 px (DN) default, user-definable up to 50 via max_sigma.
    sigma is clipped to [0, max_sigma] where max_sigma <= 50.

    Args:
      frame: uint8
      sigma: std dev in DN (px brightness) [0, 50]
      max_sigma: user-defined cap (extends beyond 20 if needed)
    """
    if frame.size == 0 or sigma <= 1e-9:
        return frame
    cap = float(np.clip(max_sigma, 0.0, GAUSSIAN_SIGMA_MAX_USER))
    sigma = float(np.clip(sigma, 0.0, cap))
    if sigma <= 1e-9:
        return frame
    noise = np.random.normal(0.0, sigma, frame.shape).astype(np.float32)
    out = frame.astype(np.float32) + noise
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    # Preserve dtype
    return out.astype(frame.dtype, copy=False)


def apply_poisson_noise(
    frame: np.ndarray,
    scale: float = 1.0,
    *,
    peak: float = 100.0,
) -> np.ndarray:
    """
    Poisson shot noise — Poisson(frame * scale * (peak/100))/scale approx, with Normal fallback for large rates.

    scale ~ intensity multiplier; 1.0 = native. peak ~ reference peak DN (30..255) —
    higher peak = larger lambda for bright pixels = relatively less noisy.
    For speed with large frames we use Normal approx when rate > 30 and frame large.

    Stateless, no dt needed.
    """
    if frame.size == 0 or scale <= 1e-9:
        return frame
    # Normalise to float; Poisson expects lambda = pixel value * scale * (peak/100)
    # DN 0..255 -> lambda 0..255*scale*(peak/100)
    peak = float(np.clip(peak, 30.0, 255.0))
    eff_scale = float(scale) * (float(peak) / 100.0)
    f = frame.astype(np.float32) * float(eff_scale)
    # For DN 0 => 0 stays 0; avoid lambda 0issues
    # Use vectorized: Poisson where lam <= 200 and size small else Normal
    flat = f.reshape(-1)
    out_flat = np.empty_like(flat)
    # Small lambda exact Poisson (float lam, no int truncation), large lambda Normal approx
    large = flat > 120
    if np.any(~large):
        lam_s = np.clip(flat[~large].astype(np.float64), 0, 9000)
        if lam_s.size > 400_000:
            out_flat[~large] = np.random.normal(lam_s, np.sqrt(np.maximum(lam_s, 1.0)))
        else:
            try:
                out_flat[~large] = np.random.poisson(lam_s).astype(float)
            except Exception:
                out_flat[~large] = np.random.normal(lam_s, np.sqrt(np.maximum(lam_s, 1.0)))
    if np.any(large):
        lam_l = flat[large].astype(np.float64)
        out_flat[large] = np.random.normal(lam_l, np.sqrt(np.maximum(lam_l, 1.0)))
    out = (out_flat.reshape(f.shape) / float(eff_scale))
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    # reshape to frame shape (handles 3ch via flat reshape already correct if 3D, need original shape)
    out = out.reshape(frame.shape)
    return out.astype(frame.dtype, copy=False)


def apply_image_noise(
    frame: np.ndarray,
    *,
    enable_salt_pepper: bool = False,
    enable_gaussian: bool = False,
    enable_poisson: bool = False,
    salt_pepper_density: float = 0.10,
    salt_pepper_ratio: float = 0.50,
    gaussian_sigma: float = 8.0,
    gaussian_sigma_max: float = 20.0,
    poisson_scale: float = 1.0,
    poisson_peak: float = 100.0,
    # Backward-compat intensity-based shortcut (0..10 controls overall mix)
    intensity: float | None = None,
) -> np.ndarray:
    """
    Unified image noise — physical order: Poisson (shot) -> Gaussian (read) -> S&P (defects).

    Previous order Gaussian->Poisson was non-physical. Correct sensor stack:
      photons -> Poisson shot noise (signal-dependent) -> Gaussian read noise (signal-independent)
      -> Salt&Pepper defects (hot pixels). This order both looks real and is hardest for AI:
      S&P overwrites blurred noisy pixels, creating sharp fake beacons.

    If intensity is given (0..10), it drives defaults when individual enables are False:
      I>0 enables Gaussian with sigma=I*2, Poisson scale=1, S&P density=I/100
    But explicit enables override intensity shortcut.

    Args:
      frame: uint8 HxWx3 or HxW
      enable_*: per-type toggles
      salt_pepper_density: 0..0.20 (10% default)
      salt_pepper_ratio: 0..1 (0.5 equal)
      gaussian_sigma: 0..50 (max 20 default, user extensible via gaussian_sigma_max)
      gaussian_sigma_max: user cap up to 50
      poisson_scale: scale multiplier for Poisson rate (0.5..5.0)
      poisson_peak: reference peak 30..255
      intensity: optional 0..10 legacy shortcut

    Returns noisy frame same shape/dtype.
    """
    if frame.size == 0:
        return frame

    # Legacy intensity shortcut — when caller passes intensity but no explicit enables
    if intensity is not None and not (enable_salt_pepper or enable_gaussian or enable_poisson):
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return frame
        enable_gaussian = iv > 0.1
        enable_poisson = iv > 0.8
        enable_salt_pepper = iv > 1.0
        if iv < 0.5 and enable_salt_pepper:
            enable_salt_pepper = False
            enable_poisson = False
        gaussian_sigma = iv * 2.0
        poisson_scale = 1.0
        salt_pepper_density = float(np.clip(iv * 0.01, 0, 0.20))

    out = frame
    # Physical order: Poisson (shot, light-dependent) -> Gaussian (read, independent) -> S&P (defects)
    if enable_poisson:
        out = apply_poisson_noise(out, scale=float(poisson_scale), peak=float(poisson_peak))
    if enable_gaussian:
        out = apply_gaussian_noise(out, sigma=float(gaussian_sigma), max_sigma=float(gaussian_sigma_max))
    if enable_salt_pepper:
        out = apply_salt_pepper(out, density=float(salt_pepper_density), salt_vs_pepper=float(salt_pepper_ratio))
    return out
