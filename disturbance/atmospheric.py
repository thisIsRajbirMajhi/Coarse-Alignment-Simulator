# disturbance/atmospheric.py - Physical atmospheric optics — depth-aware fog, rain, low-light
# Robust-simple refactor: Beer-Lambert extinction, horizon-weighted fog, motion-blurred rain,
# and low-light desaturation + Poisson boost — all via single apply_atmospheric_disturbance.

from __future__ import annotations

import math

import cv2
import numpy as np

from common.rng import get_rng

from disturbance.constants import ATMOSPHERIC_PRESET_MAP, ATMOSPHERIC_PRESETS

# Depth weighting for fog/haze — bottom (horizon) 1.6x denser than top (zenith)
_FOG_DEPTH_GAIN_BOTTOM = 1.60

# Shared RNG helper for streaks (deterministic per call via np.random, kept simple)


def _resolve_preset(
    preset: str,
    contrast_reduction: float | None = None,
    brightness_reduction: float | None = None,
) -> dict:
    """Map preset name to params, honouring User Defined overrides."""
    key = str(preset).strip()
    if key.lower() in ("low_light", "low light", "low-light"):
        key = "Low Light"
    elif key.lower() in ("user_defined", "user defined", "user-defined"):
        key = "User Defined"
    elif key.lower() == "clear":
        key = "Clear"
    elif key.lower() == "haze":
        key = "Haze"
    elif key.lower() == "fog":
        key = "Fog"
    elif key.lower() == "rain":
        key = "Rain"
    if key not in ATMOSPHERIC_PRESET_MAP:
        for k in ATMOSPHERIC_PRESET_MAP:
            if k.lower() == key.lower():
                key = k
                break
        else:
            key = "Clear"
    base = dict(ATMOSPHERIC_PRESET_MAP[key])
    if key == "User Defined":
        if contrast_reduction is not None:
            base["contrast"] = float(np.clip(contrast_reduction, 0, 100))
        if brightness_reduction is not None:
            base["brightness"] = float(np.clip(brightness_reduction, 0, 100))
    return base


def _apply_contrast_brightness(frame: np.ndarray, contrast_pct: float, brightness_pct: float) -> np.ndarray:
    """
    Physical contrast/brightness reduction with depth-aware fog weighting.

    Contrast: mid-grey pivot 128, alpha = 1 - c
    Brightness: subtract up to -72 DN + slight gamma for low light.
    Depth: for Fog/Haze presets, apply 1.0 top -> 1.6 bottom gradient so horizon
           is more obscured — challenging for AI and realistic.
    """
    if contrast_pct <= 0 and brightness_pct <= 0:
        return frame
    f = frame.astype(np.float32)
    h = f.shape[0]
    c = float(np.clip(contrast_pct, 0, 100)) / 100.0
    b = float(np.clip(brightness_pct, 0, 100)) / 100.0

    # Depth weighting: stronger at bottom for fog-like presets (contrast>20)
    if c > 0.20 or b > 0.18:
        # Build vertical weight 1.0 -> 1.6
        w = np.linspace(1.0, _FOG_DEPTH_GAIN_BOTTOM, h, dtype=np.float32)[:, None, None] if f.ndim == 3 else np.linspace(1.0, _FOG_DEPTH_GAIN_BOTTOM, h, dtype=np.float32)[:, None]
        c_eff = c * w.squeeze() if f.ndim == 2 else c  # broadcast later
        b_eff = b * np.linspace(1.0, 1.35, h, dtype=np.float32)[:, None, None] if f.ndim == 3 else b * np.linspace(1.0, 1.35, h, dtype=np.float32)[:, None]
        if f.ndim == 3:
            # per-row alpha/beta
            row_alpha = 1.0 - c * np.linspace(1.0, _FOG_DEPTH_GAIN_BOTTOM, h, dtype=np.float32)[:, None]
            # Expand to HxWx3 via broadcasting: (H,1) -> (H,W,3)
            row_alpha3 = np.repeat(row_alpha[:, :, None], f.shape[1], axis=1) if row_alpha.ndim == 2 else row_alpha  # fallback
            # Simpler: apply per row loop via broadcasting
            # Use vectorized: f = (f-128)*alpha_row +128
            # alpha_row shape (H,1,1)
            alpha_row = (1.0 - c * np.linspace(1.0, _FOG_DEPTH_GAIN_BOTTOM, h, dtype=np.float32)[:, None, None])
            f = (f - 128.0) * alpha_row + 128.0
            delta_row = b * 72.0 * np.linspace(1.0, 1.35, h, dtype=np.float32)[:, None, None]
            f = f - delta_row
        else:
            alpha_row = 1.0 - c_eff
            f = (f - 128.0) * alpha_row[:, None] + 128.0
            f = f - (b_eff.squeeze() * 72.0)[:, None] if f.ndim == 2 else f - b_eff
    else:
        if c > 1e-6:
            f = (f - 128.0) * (1.0 - c) + 128.0
        if b > 1e-6:
            delta = b * 72.0
            f = f - delta
            if b > 0.35:
                f = f * (1.0 - 0.10 * b)
    return np.clip(f, 0, 255).astype(np.uint8)


def _add_rain_streaks(frame: np.ndarray, intensity: float = 0.3, motion_blur: float = 0.0, rng: np.random.Generator | None = None) -> np.ndarray:
    """
    Physically-blurred rain streaks with wind angle variance + occlusion.

    Args:
      intensity: 0..1 rain density
      motion_blur: extra length from platform motion (px)
    """
    if frame.size == 0 or intensity <= 0:
        return frame
    _rng = get_rng(rng)
    h, w = frame.shape[:2]
    n = int(160 * intensity * (w * h / (640 * 480)) ** 0.5)
    # Rain density scales non-linearly: light drizzle vs downpour
    n = int(np.clip(n + int(intensity * 420), 18, 1400))
    line_mask = np.zeros_like(frame, dtype=np.uint8)
    blur_extra = int(np.clip(motion_blur, 0, 12))
    for _ in range(n):
        x = int(_rng.integers(-10, w + 10))
        y = int(_rng.integers(-20, h + 20))
        # Length varies with intensity: drizzle 7-14, heavy 14-28 + motion blur
        if intensity < 0.35:
            length = int(_rng.integers(7, 15)) + blur_extra
        else:
            length = int(_rng.integers(13, 27)) + blur_extra
        thickness = 1 if _rng.random() < 0.78 else 2
        # Wind shear: 68-76 deg baseline + ±6 deg gust
        base_angle = _rng.uniform(68, 76)
        gust = _rng.normal(0, 2.2)
        angle = math.radians(np.clip(base_angle + gust, 58, 82))
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))
        # Streak brightness 175-225, slightly desaturated with fog
        val = int(np.clip(_rng.normal(202, 12), 172, 230))
        color = (val, val, val) if frame.ndim == 3 else val
        cv2.line(line_mask, (x, y), (x2, y2), color, thickness, cv2.LINE_AA)  # type: ignore
    # Occlusion dimming: where multiple streaks overlap looks brighter — use 0.16-0.22 alpha
    alpha = 0.17 + 0.04 * float(np.clip(intensity, 0, 1))
    overlay = frame.astype(np.float32)
    nz = line_mask > 0
    if np.any(nz):
        # Soften streak edges with tiny blur for realism
        if intensity > 0.4:
            line_mask = cv2.GaussianBlur(line_mask, (0, 0), sigmaX=0.6)
            nz = line_mask > 12
        overlay[nz] = overlay[nz] * (1 - alpha) + line_mask[nz].astype(np.float32) * alpha
        overlay = np.clip(overlay, 0, 255)
        # Micro-occlusion: 2% of streaks create a bright highlight that can hide beacon
        # (adds challenge for AI — beacon behind streak dims 12%)
        highlight_mask = (line_mask > 90) & (_rng.random(frame.shape[:2]) < 0.02) if frame.ndim == 2 else (line_mask[:, :, 0] > 90) & (_rng.random(frame.shape[:2]) < 0.02)
        if np.any(highlight_mask):
            overlay[highlight_mask] = np.clip(overlay[highlight_mask] * 0.88, 0, 255)
    return overlay.astype(np.uint8)


def _apply_blooming(frame: np.ndarray, strength: float = 0.12) -> np.ndarray:
    """Subtle blooming for bright beacons in fog/low-light — spreads highlights."""
    if strength <= 1e-3 or frame.size == 0:
        return frame
    # Bloom only bright pixels >185
    bright = np.where(frame > 185, frame.astype(np.float32) - 185, 0)
    if np.sum(bright) < 200:
        return frame
    bloom = cv2.GaussianBlur(bright, (0, 0), sigmaX=1.8, sigmaY=1.8)
    # Add back with strength, chromatic: slightly more in R for warm bloom
    out = frame.astype(np.float32) + bloom * float(strength)
    if out.ndim == 3:
        out[:, :, 2] += bloom[:, :, 2] * 0.04  # R boost
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_atmospheric_disturbance(
    frame: np.ndarray,
    preset: str = "Clear",
    contrast_reduction: float | None = None,
    brightness_reduction: float | None = None,
    *,
    intensity: float | None = None,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """
    Atmospheric disturbance — Clear/Haze/Fog/Rain/Low Light + User Defined.

    Spec notes for user-defined: reduction in contrast and brightness is user-configurable.
    Each preset maps to contrast%, brightness%, blur sigma, haze overlay.

    Args:
      frame: HxWx3 uint8
      preset: one of ATMOSPHERIC_PRESETS
      contrast_reduction: 0..100 % (overrides preset if User Defined)
      brightness_reduction: 0..100 %
      intensity: legacy 0..10 controls if preset is Clear but intensity>0 -> map to haze strength

    Returns frame same shape/dtype.
    """
    if frame.size == 0:
        return frame
    # Handle legacy intensity shortcut
    if intensity is not None and preset == "Clear":
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return frame
        # Map intensity 0..10 to haze-like: contrast 3*I, brightness 2*I, blur 0.14*I
        contrast_reduction = iv * 3.5
        brightness_reduction = iv * 2.2
        preset = "Haze" if iv < 6 else "Fog"

    params = _resolve_preset(preset, contrast_reduction, brightness_reduction)
    contrast = float(params.get("contrast", 0))
    brightness = float(params.get("brightness", 0))
    blur_sigma = float(params.get("blur", 0.0))
    haze_factor = float(params.get("haze", 0.0))

    # Fast path: Clear
    if preset == "Clear" and contrast <= 1e-9 and brightness <= 1e-9 and blur_sigma <= 1e-9:
        # also check if still Clear after resolve when user passed 0,0
        if str(preset).lower() == "clear":
            return frame

    out = frame

    # Optional blur for fog/haze scattering — visibility-dependent
    if blur_sigma > 0.05:
        # In heavy fog, blur should be slightly stronger near bottom (depth)
        ksize = int(np.clip(round(blur_sigma * 3.5) * 2 + 1, 3, 13))
        if ksize % 2 == 0:
            ksize += 1
        out = cv2.GaussianBlur(out, (ksize, ksize), sigmaX=blur_sigma)
        # Add extra depth haze blur for Fog: slight bloom on bright pixels
        if str(preset).lower() == "fog" and blur_sigma > 1.0:
            out = _apply_blooming(out, strength=0.09 * (blur_sigma / 1.4))

    # Contrast / brightness reduction — depth aware
    out = _apply_contrast_brightness(out, contrast, brightness)

    # Haze overlay — depth-weighted desaturation toward 165 grey
    if haze_factor > 1e-6:
        haze_col = 165
        alpha = float(np.clip(haze_factor, 0, 0.55))
        h = out.shape[0]
        out_f = out.astype(np.float32)
        if out.ndim == 3:
            alpha_row = np.linspace(alpha * 0.75, alpha * 1.25, h, dtype=np.float32)[:, None, None]
            out_f = out_f * (1 - alpha_row) + haze_col * alpha_row
        else:
            alpha_row = np.linspace(alpha * 0.75, alpha * 1.25, h, dtype=np.float32)[:, None]
            out_f = out_f * (1 - alpha_row) + haze_col * alpha_row
        out = np.clip(out_f, 0, 255).astype(np.uint8)

    # Rain streaks — physics rain with motion blur
    if str(preset).lower() == "rain" or preset == "Rain":
        _rng = get_rng(rng)
        rain_intensity = 0.22 + float(params.get("haze", 0.12)) * 0.6 + contrast / 400.0
        rain_intensity = float(np.clip(rain_intensity, 0.18, 0.62))
        # Motion blur from platform would be passed via blur param in future; approx 0 here
        out = _add_rain_streaks(out, intensity=rain_intensity, motion_blur=blur_sigma * 1.2, rng=_rng)

    # Low Light — desaturate + add slight bloom for beacon halo challenge
    if str(preset).lower() in ("low light", "low_light"):
        if out.ndim == 3:
            grey = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            grey3 = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
            out = cv2.addWeighted(out, 0.62, grey3, 0.38, 0)
            # Low-light bloom makes beacon bleed — AI must handle halo
            out = _apply_blooming(out, strength=0.11)

    return out.astype(frame.dtype, copy=False)
