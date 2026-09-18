# remote_terminal/optics.py - Optical spot and emission physics per RemoteTerminal.md
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def gaussian_profile_kernel(size: int = 15, sigma: float = 2.5) -> np.ndarray:
    """Gaussian beam profile kernel."""
    if size % 2 == 0:
        size += 1
    c = size // 2
    y, x = np.ogrid[-c:c + 1, -c:c + 1]
    r2 = (x * x + y * y).astype(np.float32)
    k = np.exp(-0.5 * r2 / (sigma * sigma))
    return (k / (k.max() + 1e-6)).astype(np.float32)


def tophat_profile_kernel(size: int = 15, radius: float = 4.0, edge_blur: float = 1.0) -> np.ndarray:
    """Top-hat beam profile with realistic diffraction edge rolloff."""
    if size % 2 == 0:
        size += 1
    c = size // 2
    y, x = np.ogrid[-c:c + 1, -c:c + 1]
    r = np.sqrt(x * x + y * y).astype(np.float32)
    k = np.where(r <= radius, 1.0, 0.0).astype(np.float32)
    if edge_blur > 0.1:
        k = cv2.GaussianBlur(k, (0, 0), sigmaX=edge_blur)
    return (k / (k.max() + 1e-6)).astype(np.float32)


def airy_profile_kernel(size: int = 15, alpha: float = 1.4) -> np.ndarray:
    """Airy diffraction pattern approximation (central disk + faint first ring)."""
    if size % 2 == 0:
        size += 1
    c = size // 2
    y, x = np.ogrid[-c:c + 1, -c:c + 1]
    r = np.sqrt(x * x + y * y).astype(np.float32)
    core = np.exp(-0.5 * (r / (size * 0.18)) ** 2)
    ring = 0.12 * np.exp(-0.5 * ((r - size * 0.32) / (size * 0.10)) ** 2)
    ring[r < size * 0.22] = 0
    psf = core + ring * float(alpha) * 0.5
    return (psf / (psf.max() + 1e-6)).astype(np.float32)


def get_wavelength_bgr_tint(wavelength_nm: float) -> tuple[float, float, float]:
    """
    Produce a physically intuitive BGR tint for laser/beacon wavelength.
    1550 nm: Telecom NIR, high-penetration warm gold/white
    1064 nm: Nd:YAG NIR, warm soft violet-white
    850 nm: Near-IR, faint warm ruby-white
    532 nm: Frequency-doubled Nd:YAG (Green beacon)
    650 nm: Red alignment laser
    """
    w = float(wavelength_nm)
    if w >= 1500.0:
        # 1550 nm: Near-infrared telecom standard -> warm gold-white
        return (220.0, 240.0, 255.0)
    elif w >= 1000.0:
        # 1064 nm: Nd:YAG -> subtle lavender-white
        return (245.0, 230.0, 255.0)
    elif w >= 800.0:
        # 850 nm: NIR -> warm soft ruby-white
        return (200.0, 210.0, 255.0)
    elif 500.0 <= w < 570.0:
        # 532 nm: Green
        return (100.0, 255.0, 120.0)
    elif 600.0 <= w < 700.0:
        # 635-670 nm: Red
        return (80.0, 100.0, 255.0)
    else:
        return (240.0, 240.0, 255.0)


def compute_temporal_factor(
    sim_time: float,
    mod_type: str = "AM",
    mod_freq_khz: float = 10.0,
    mod_depth: float = 1.0,
    mod_phase_deg: float = 0.0,
    pulse_enabled: bool = False,
    pulse_rate_khz: float = 10.0,
    duty_cycle: float = 0.5,
    identification_code: str = "",
    identification_code_enabled: bool = False,
    identification_chip_rate_hz: float = 8.0,
) -> float:
    """
    Compute instantaneous temporal modulation scaling factor [0.0, 1.0+].
    For high-frequency carrier (e.g. 10 kHz) in video frames (30-60 Hz),
    aliased beat / mean envelope + sub-harmonic flicker is rendered for visual perception.
    """
    code_factor = 1.0
    if identification_code_enabled and identification_code:
        # ASCII bits are an observable OOK overlay.  It is deliberately slow
        # enough for the simulated camera to sample, unlike the kHz carrier.
        bits = "".join(f"{ord(ch):08b}" for ch in identification_code)
        chip = int(math.floor(sim_time * max(0.5, identification_chip_rate_hz))) % len(bits)
        code_factor = 1.0 if bits[chip] == "1" else 0.25
    if pulse_enabled:
        # Repetition cycle: visual duty cycle factor
        f_eff = min(pulse_rate_khz * 1e3, 30.0)
        cycle = (sim_time * f_eff) % 1.0
        return (1.0 if cycle < duty_cycle else 0.05) * code_factor

    if mod_type == "AM":
        f_visual = min(mod_freq_khz * 0.5, 8.0)
        phi = math.radians(mod_phase_deg)
        sine_val = math.cos(2.0 * math.pi * f_visual * sim_time + phi)
        # AM: 1 + m * cos(wt)
        return float(max(0.05, 1.0 + mod_depth * 0.5 * sine_val)) * code_factor
    elif mod_type == "PM" or mod_type == "OOK":
        f_visual = min(mod_freq_khz * 0.5, 10.0)
        cycle = (sim_time * f_visual) % 1.0
        return (1.0 if cycle < 0.5 else 0.15) * code_factor
    elif mod_type == "PPM":
        f_visual = min(mod_freq_khz * 0.5, 12.0)
        cycle = (sim_time * f_visual) % 1.0
        return (1.0 if cycle < 0.25 else 0.1) * code_factor
    else:  # NONE / Continuous Wave
        return code_factor


def render_terminal_beacon_patch(
    power_w: float = 1.0,
    wavelength_nm: float = 1550.0,
    div_h_mrad: float = 1.0,
    div_v_mrad: float = 1.0,
    profile_type: str = "GAUSSIAN",
    temporal_factor: float = 1.0,
    pixel_scale_mrad: float = 0.035,
    min_patch_size: int = 7,
    max_patch_size: int = 45,
) -> np.ndarray:
    """
    Render realistic optical spot patch (H, W, 3) uint8 based on beam parameters.
    """
    # Angular divergence to pixel size: spot_px = divergence_mrad / pixel_scale_mrad
    scale = max(1e-4, pixel_scale_mrad)
    w_px = int(np.clip(round(div_h_mrad / scale * 0.25), min_patch_size, max_patch_size))
    h_px = int(np.clip(round(div_v_mrad / scale * 0.25), min_patch_size, max_patch_size))
    if w_px % 2 == 0:
        w_px += 1
    if h_px % 2 == 0:
        h_px += 1

    k_size = max(w_px, h_px)
    if profile_type == "TOP_HAT":
        psf = tophat_profile_kernel(k_size, radius=float(k_size * 0.35))
    elif profile_type == "CUSTOM":
        psf = airy_profile_kernel(k_size)
    else:
        psf = gaussian_profile_kernel(k_size, sigma=float(k_size * 0.22))

    if (w_px, h_px) != (k_size, k_size):
        psf = cv2.resize(psf, (w_px, h_px), interpolation=cv2.INTER_LINEAR)

    # Power scaling: 1.0 W gives saturated core (DN ~ 255) with soft halo
    # temporal_factor modulates intensity (can reach 0 when pulsed low or switched off)
    if power_w <= 0.0 or temporal_factor <= 0.0:
        return np.zeros((h_px, w_px, 3), dtype=np.uint8)

    base_dn = 255.0 * math.sqrt(max(0.0, min(1.0, power_w / 1.5)))
    peak_dn = float(np.clip(base_dn * max(0.0, temporal_factor), 0.0, 255.0))
    if peak_dn < 0.5:
        return np.zeros((h_px, w_px, 3), dtype=np.uint8)

    intensity = (psf * peak_dn).astype(np.float32)

    # Apply spectral wavelength tint
    tint = get_wavelength_bgr_tint(wavelength_nm)
    bgr = np.zeros((intensity.shape[0], intensity.shape[1], 3), dtype=np.float32)
    bgr[:, :, 0] = intensity * (tint[0] / 255.0)
    bgr[:, :, 1] = intensity * (tint[1] / 255.0)
    bgr[:, :, 2] = intensity * (tint[2] / 255.0)

    # Core saturation boost for realism
    core_mask = intensity > 210.0
    bgr[core_mask] = np.clip(bgr[core_mask] * 1.15, 0, 255)

    return np.clip(bgr, 0, 255).astype(np.uint8)
