# disturbance/image_noise.py - Configurable Image Noise — Salt & Pepper, Gaussian, Poisson (one or more at once)

from __future__ import annotations

import numpy as np

from disturbance.constants import (
    GAUSSIAN_SIGMA_LIMITS,
    GAUSSIAN_SIGMA_MAX_USER,
    SALT_PEPPER_LIMITS,
)


def _clip_frame(frame: np.ndarray) -> np.ndarray:
    return np.clip(frame, 0, 255)


def apply_salt_pepper(
    frame: np.ndarray,
    density: float = 0.10,
    *,
    salt_vs_pepper: float = 0.5,
) -> np.ndarray:
    """
    Salt & Pepper — randomly sets ~density fraction of pixels to 0 or 255.

    Args:
      frame: HxWx3 uint8
      density: fraction of image corrupted [0,0.20] — 0.10 ≈ 10% (spec default)
      salt_vs_pepper: ratio of salt (255) vs pepper (0), 0.5 = equal

    Returns same shape/dtype.
    """
    if frame.size == 0 or density <= 1e-9:
        return frame
    density = float(np.clip(density, 0.0, 0.20))
    out = frame.copy()
    h, w = frame.shape[:2]
    # total pixels to corrupt
    total = int(h * w * float(density))
    if total <= 0:
        return out
    # random coordinates
    ys = np.random.randint(0, h, size=total)
    xs = np.random.randint(0, w, size=total)
    # split salt / pepper
    salt_n = int(total * float(salt_vs_pepper))
    # pepper = black
    if total - salt_n > 0:
        py = ys[salt_n:]
        px = xs[salt_n:]
        if out.ndim == 3:
            out[py, px, :] = 0
        else:
            out[py, px] = 0
    # salt = white
    if salt_n > 0:
        sy = ys[:salt_n]
        sx = xs[:salt_n]
        if out.ndim == 3:
            out[sy, sx, :] = 255
        else:
            out[sy, sx] = 255
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
    Unified image noise — one or more at once (spec: configurable).

    Order (so salt&pepper corrupts after gaussian/poisson if wanted):
      1) Gaussian
      2) Poisson
      3) Salt & Pepper (last, overwrites)

    If intensity is given (0..10), it drives defaults when individual enables are False:
      I>0 enables Gaussian with sigma=I*2, Poisson scale=1+I/10, S&P density= I/100
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
        # Map intensity 0..10 to per-type strengths
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return frame
        # 10% at I=10 for S&P ≈ I*0.01 ; Gaussian sigma = I*2 (20 at max) ; Poisson scale =1
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
    # Order: Gaussian -> Poisson -> SaltPepper (so salt&pepper overwrites)
    if enable_gaussian:
        out = apply_gaussian_noise(out, sigma=float(gaussian_sigma), max_sigma=float(gaussian_sigma_max))
    if enable_poisson:
        out = apply_poisson_noise(out, scale=float(poisson_scale), peak=float(poisson_peak))
    if enable_salt_pepper:
        out = apply_salt_pepper(out, density=float(salt_pepper_density), salt_vs_pepper=float(salt_pepper_ratio))
    return out
