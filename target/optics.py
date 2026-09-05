# target/optics.py - Real beacon optics — Airy/Gaussian PSF, motion streak, blooming
# Robust-simple: renders realistic light spot, not perfect square/circle.

from __future__ import annotations

import math

import cv2
import numpy as np


def _airy_psf_kernel(size: int = 11, alpha: float = 1.6) -> np.ndarray:
    """Airy-like kernel — central bright disk + faint first ring (approximated with Gaussian mixture)."""
    if size % 2 == 0:
        size += 1
    c = size // 2
    y, x = np.ogrid[-c:c+1, -c:c+1]
    r = np.sqrt(x*x + y*y).astype(np.float32)
    # Central Gaussian core + weak ring at ~0.7*size
    core = np.exp(-0.5 * (r / (size * 0.18)) ** 2)
    ring = 0.12 * np.exp(-0.5 * ((r - size * 0.32) / (size * 0.10)) ** 2)
    # First dark ring suppression
    ring[r < size * 0.22] = 0
    psf = core + ring * float(alpha) * 0.5
    psf = psf / (psf.max() + 1e-6)
    return psf.astype(np.float32)


def gaussian_psf_kernel(size: int = 9, sigma: float = 1.8) -> np.ndarray:
    """Gaussian PSF — for defocused / fog-scattered beacons."""
    if size % 2 == 0:
        size += 1
    c = size // 2
    y, x = np.ogrid[-c:c+1, -c:c+1]
    r2 = (x*x + y*y).astype(np.float32)
    psf = np.exp(-0.5 * r2 / (sigma * sigma))
    psf = psf / (psf.max() + 1e-6)
    return psf.astype(np.float32)


def render_beacon_patch(
    size_w: int,
    size_h: int,
    brightness: float,
    shape: str = "square",
    motion_vector: tuple[float, float] = (0.0, 0.0),
    fog_factor: float = 0.0,
    jitter_px: float = 0.0,
    bloom_strength: float = 0.0,
    color_bgr: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """
    Render a realistic beacon patch (size_h, size_w, 3) uint8.

    Args:
      size_w, size_h: requested beacon size px (5-20) — drives kernel size
      brightness: 0-255 peak
      shape: square/circle — both use PSF but square gets slight boxy bias
      motion_vector: (vx*dt, vy*dt) px per frame for streak
      fog_factor: 0..1 fog density -> larger, softer, dimmer
      jitter_px: AoA jitter amplitude -> subpixel shift
      bloom_strength: 0..0.4 halo strength for low-light
      color_bgr: optional warm tint (BGR) for 1550nm

    Returns BGR uint8 patch (size_h, size_w, 3) with realistic PSF.
    """
    size_w = int(np.clip(size_w, 5, 20))
    size_h = int(np.clip(size_h, 5, 20))
    brightness = float(np.clip(brightness, 0, 255))
    fog_factor = float(np.clip(fog_factor, 0, 1))
    bloom_strength = float(np.clip(bloom_strength, 0, 0.4))

    # Determine kernel size: beacon area maps to PSF diameter ~ 0.85*size
    k_size = int(max(size_w, size_h) * 1.35)
    k_size = int(np.clip(k_size, 7, 21))
    if k_size % 2 == 0:
        k_size += 1

    # Fog enlarges and softens
    fog_sigma_boost = 1.0 + fog_factor * 0.9
    fog_dim = 1.0 - fog_factor * 0.22
    peak = brightness * fog_dim

    # Choose PSF
    if fog_factor > 0.35:
        # Scattered -> Gaussian softer
        sigma = (k_size * 0.22) * fog_sigma_boost
        psf = gaussian_psf_kernel(k_size, sigma=float(sigma))
    else:
        psf = _airy_psf_kernel(k_size, alpha=1.0 + fog_factor * 0.6)
        # Slight Gaussian soften for realism
        psf = cv2.GaussianBlur(psf, (0, 0), sigmaX=0.6)

    # Square bias: square beacons have slightly flatter top (boxy)
    if shape == "square":
        psf = np.power(psf, 0.88)
        psf = psf / (psf.max() + 1e-6)

    # Convert PSF 0..1 to DN via peak
    patch_f = psf * float(peak)
    # Add subpixel jitter shift
    if abs(jitter_px) > 0.3:
        shift_x = float(np.clip(jitter_px * 0.5, -1.5, 1.5))
        shift_y = float(np.clip(jitter_px * 0.3, -1.2, 1.2))
        M = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
        patch_f = cv2.warpAffine(patch_f, M, (k_size, k_size), borderMode=cv2.BORDER_REFLECT_101)

    # Motion streak: elongate along velocity
    mv_mag = math.hypot(motion_vector[0], motion_vector[1])
    if mv_mag > 3.5:
        # Angle and length
        ang = math.degrees(math.atan2(motion_vector[1], motion_vector[0]))
        # Use getRotationMatrix2D to stretch — simplest: directional blur via kernel
        # Create small motion kernel 1xL
        L = int(np.clip(mv_mag * 0.55, 3, 9))
        if L % 2 == 0:
            L += 1
        # Horizontal kernel then rotate
        kernel = np.zeros((L, L), dtype=np.float32)
        kernel[L//2, :] = 1.0 / L
        # Rotate kernel to motion angle
        Mrot = cv2.getRotationMatrix2D((L/2, L/2), -ang, 1.0)
        kernel = cv2.warpAffine(kernel, Mrot, (L, L), borderMode=cv2.BORDER_CONSTANT)
        kernel = kernel / (np.sum(kernel) + 1e-6)
        # Convolve patch
        patch_f = cv2.filter2D(patch_f, -1, kernel, borderType=cv2.BORDER_REFLECT_101)
        # Re-normalize peak after streak (streak dims)
        patch_f = patch_f / (patch_f.max() + 1e-6) * float(peak) * 0.92

    # Resize PSF to requested size_w/h
    patch_resized = cv2.resize(patch_f, (size_w, size_h), interpolation=cv2.INTER_LINEAR)

    # Bloom halo: soft outer glow for bright beacons in low light / fog
    if bloom_strength > 1e-3 and brightness > 160:
        bloom = cv2.GaussianBlur(patch_resized, (0, 0), sigmaX=size_w * 0.45, sigmaY=size_h * 0.45)
        bloom = bloom * float(bloom_strength) * (brightness / 255.0)
        patch_resized = np.clip(patch_resized + bloom, 0, 255)

    # Convert to BGR
    if color_bgr is not None:
        # Tint: blend PSF DN with color
        b, g, r = color_bgr
        # Warm 1550nm is slightly yellow-white, not pure white
        patch_bgr = np.zeros((size_h, size_w, 3), dtype=np.float32)
        patch_bgr[:, :, 0] = np.clip(patch_resized * (b / 255.0 * 0.85 + 0.15), 0, 255)
        patch_bgr[:, :, 1] = np.clip(patch_resized * (g / 255.0 * 0.92 + 0.08), 0, 255)
        patch_bgr[:, :, 2] = np.clip(patch_resized * (r / 255.0), 0, 255)
    else:
        # Slight warm bias even without explicit color
        patch_bgr = np.zeros((size_h, size_w, 3), dtype=np.float32)
        patch_bgr[:, :, 0] = patch_resized * 0.94  # B slightly less
        patch_bgr[:, :, 1] = patch_resized * 0.98
        patch_bgr[:, :, 2] = patch_resized

    return np.clip(patch_bgr, 0, 255).astype(np.uint8)


def get_beacon_color_bgr(beacon_id: int, brightness: float) -> tuple[float, float, float]:
    """Per-beacon ID warm tint — subtly different for multi-beacon ID challenge."""
    # IDs get slight hue shift: even = neutral, odd = slightly warm, 2 = slightly cool
    base = (235, 240, 255)  # BGR near white
    if beacon_id % 3 == 1:
        base = (225, 235, 255)  # warmer (more R)
    elif beacon_id % 3 == 2:
        base = (245, 242, 255)  # cooler (more B)
    scale = float(np.clip(brightness / 255.0, 0.75, 1.0))
    return (float(base[0] * scale), float(base[1] * scale), float(base[2] * scale))
