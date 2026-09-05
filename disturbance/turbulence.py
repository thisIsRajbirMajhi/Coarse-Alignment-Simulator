# disturbance/turbulence.py - Kolmogorov / von Kármán turbulence — phase screens, seeing blur, scintillation

import math

import cv2
import numpy as np

from common.rng import get_rng

from disturbance.constants import INNER_SCALE, OUTER_SCALE, RYTOV_CAP, TILT_TAU, WAVELENGTH
from disturbance.dt_provider import DtProvider
from disturbance.helpers import r0_from_intensity, rytov_variance
from disturbance.state import _turb_state

def _kolmogorov_displacement(
    h: int,
    w: int,
    r0: float,
    intensity: float,
    wavelength: float = WAVELENGTH,
    outer_scale: float = OUTER_SCALE,
    inner_scale: float = INNER_SCALE,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate displacement fields dx,dy [pixels] from Kolmogorov PSD.

    Phase PSD: Φ_φ(κ)=0.023 r0^{-5/3} (κ²+1/L0²)^{-11/6} exp(-κ² l0²)
    Displacement PSD ∝ κ²·Φ_φ · (λ)²·1e6 → pixels.

    Tilt RMS target: 0.32·I^{0.85}+0.08·I → 0.7 px @I=2, 6.5 px @I=10.
    """
    fx = np.fft.fftfreq(w)
    fy = np.fft.fftfreq(h)
    FX, FY = np.meshgrid(fx, fy)
    kappa = np.sqrt(FX**2 + FY**2)
    kappa[0, 0] = 1e-6
    k0 = 1.0 / float(outer_scale)
    kappa_phys = kappa * 180.0
    phil = 0.023 * (float(r0) ** (-5.0/3.0)) * (kappa_phys**2 + k0**2) ** (-11.0/6.0) * np.exp(-(kappa_phys * float(inner_scale))**2)
    phil_d = phil * (kappa_phys**2) * (float(wavelength) * 0.9) ** 2 * 1e6
    phil_d = np.clip(phil_d, 0, 1e4)
    _rng = get_rng(rng)
    amp = np.sqrt(phil_d)
    rnd_x = _rng.normal(0, 1, (h, w)) + 1j * _rng.normal(0, 1, (h, w))
    rnd_y = _rng.normal(0, 1, (h, w)) + 1j * _rng.normal(0, 1, (h, w))
    dx = np.fft.ifft2(rnd_x * amp).real
    dy = np.fft.ifft2(rnd_y * amp).real
    target_rms = 0.32 * (float(intensity) ** 0.85) + 0.08 * float(intensity)
    cur_rms = math.sqrt(np.mean(dx**2 + dy**2) + 1e-9)
    if cur_rms > 1e-6:
        scale = target_rms / cur_rms
        dx *= scale; dy *= scale
    max_disp = 1.8 * float(intensity) + 2.0
    dx = np.clip(dx, -max_disp, max_disp)
    dy = np.clip(dy, -max_disp, max_disp)
    return dx.astype(np.float32), dy.astype(np.float32)

def apply_turbulence(
    frame: np.ndarray,
    intensity: float,
    wavelength: float = WAVELENGTH,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """
    Kolmogorov + Rytov turbulence — now dt-aware.

    Args:
      frame: H×W×3 uint8
      intensity: 0..10
      wavelength: m (default 1.55 µm)
      dt: seconds, sim-speed-scaled dt_eff. If None, falls back to wall-clock
          _elapsed_dt(_turb_state) for backward compat.

    Steps:
      1) r0, σ_R² from intensity
      2) Seeing blur (Gaussian, σ from 0.98 λ/r0)
      3) Warp via Kolmogorov displacement + temporal blend α=exp(-dt/0.11) + wind roll
      4) Scintillation log-normal gain

    Returns warped+blurred+scintillated frame (same shape/dtype).
    """
    if intensity <= 0 or frame.size == 0:
        return frame
    h, w = frame.shape[:2]

    # dt — single source via DtProvider (was 3× duplicated)
    dt = DtProvider.resolve(_turb_state, dt)

    r0 = r0_from_intensity(float(intensity), float(wavelength))
    sigma_R2 = rytov_variance(float(intensity))

    # 1) Seeing blur
    ksize = int(np.clip(round(3 + float(intensity) * 1.9), 3, 21))
    if ksize % 2 == 0:
        ksize += 1
    sigma_blur = max(0.5, 0.42 * (1.22 * float(wavelength) / float(r0)) / 35e-6 * 0.7)
    sigma_blur = float(np.clip(sigma_blur, 0.6, 4.5))
    blurred = cv2.GaussianBlur(frame, (ksize, ksize), sigmaX=sigma_blur)

    # 2) Warp field
    prev_dx = _turb_state.get("dx")
    prev_dy = _turb_state.get("dy")
    _rng = get_rng(rng)
    if h * w > 250_000:
        h2, w2 = max(32, h // 2), max(32, w // 2)
        dx_s, dy_s = _kolmogorov_displacement(h2, w2, r0, float(intensity), float(wavelength), rng=_rng)
        dx_new = cv2.resize(dx_s, (w, h), interpolation=cv2.INTER_CUBIC) * 1.9
        dy_new = cv2.resize(dy_s, (w, h), interpolation=cv2.INTER_CUBIC) * 1.9
    else:
        dx_new, dy_new = _kolmogorov_displacement(h, w, r0, float(intensity), float(wavelength), rng=_rng)

    tau_tilt = TILT_TAU
    alpha = float(math.exp(-float(dt) / float(tau_tilt)))
    if prev_dx is not None and prev_dx.shape == (h, w):
        wind_px = 1.2
        dx_shifted = np.roll(prev_dx, int(round(wind_px)), axis=1)
        dy_shifted = np.roll(prev_dy, int(round(wind_px * 0.3)), axis=1)
        dx = alpha * dx_shifted + (1 - alpha) * dx_new
        dy = alpha * dy_shifted + (1 - alpha) * dy_new
    else:
        dx, dy = dx_new, dy_new
    _turb_state["dx"], _turb_state["dy"] = dx, dy

    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = xs + dx
    map_y = ys + dy
    warped = cv2.remap(blurred, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    # 3) Scintillation
    sigma_chi = float(math.sqrt(min(float(sigma_R2), RYTOV_CAP) / 4.0 + 1e-9))
    if sigma_chi > 0.04:
        small_h = max(1, h // 4)
        small_w = max(1, w // 4)
        chi_small = _rng.normal(-sigma_chi**2, sigma_chi, (small_h, small_w)).astype(np.float32)
        chi = cv2.resize(chi_small, (w, h), interpolation=cv2.INTER_CUBIC)
        chi = cv2.GaussianBlur(chi, (0, 0), sigmaX=2.2, sigmaY=2.2)
        gain = np.exp(chi)
        gain = np.clip(gain, 0.55, 1.9).astype(np.float32)
        if warped.ndim == 3:
            gain = gain[:, :, None]
        scint = np.clip(warped.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    else:
        chi0 = float(_rng.normal(-sigma_chi**2, sigma_chi)) if sigma_chi > 0 else 0.0
        gain0 = float(np.clip(math.exp(chi0), 0.75, 1.35))
        scint = np.clip(warped.astype(np.float32) * gain0, 0, 255).astype(np.uint8)

    return scint