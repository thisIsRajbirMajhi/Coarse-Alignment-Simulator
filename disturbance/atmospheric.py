# disturbance/atmospheric.py - Atmospheric Disturbance — Clear/Haze/Fog/Rain/Low Light + User Defined

from __future__ import annotations

import math

import cv2
import numpy as np

from disturbance.constants import ATMOSPHERIC_PRESET_MAP, ATMOSPHERIC_PRESETS


def _resolve_preset(
    preset: str,
    contrast_reduction: float | None = None,
    brightness_reduction: float | None = None,
) -> dict:
    """Map preset name to params, honouring User Defined overrides."""
    key = str(preset).strip()
    # Normalise
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
    # fallback
    if key not in ATMOSPHERIC_PRESET_MAP:
        # try case-insensitive lookup
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
    Reduce contrast (0..100%) and brightness (0..100%).
    Contrast: frame = ((frame - 128) * (1 - c)) + 128
    Brightness: frame = frame - b_norm where b_norm = brightness_pct/100* 80 (empirical)
      i.e., 100% => -80 DN dimming.
    Clipped 0..255.
    """
    if contrast_pct <= 0 and brightness_pct <= 0:
        return frame
    f = frame.astype(np.float32)
    c = float(np.clip(contrast_pct, 0, 100)) / 100.0
    b = float(np.clip(brightness_pct, 0, 100)) / 100.0
    if c > 1e-6:
        # contrast factor
        alpha = 1.0 - c
        # keep mid grey 128 fixed
        f = (f - 128.0) * alpha + 128.0
    if b > 1e-6:
        # brightness reduction: up to -70 DN at 100%, scaled
        delta = b * 72.0  # 100% => -72 DN
        f = f - delta
        # slight gamma-ish dimming for low light realism
        if b > 0.35:
            f = f * (1.0 - 0.10 * b)
    f = np.clip(f, 0, 255)
    return f.astype(np.uint8)


def _add_rain_streaks(frame: np.ndarray, intensity: float = 0.3) -> np.ndarray:
    """Add sparse diagonal rain streaks — cheap OpenCV lines with alpha blend."""
    if frame.size == 0 or intensity <= 0:
        return frame
    h, w = frame.shape[:2]
    # number of streaks scaled with intensity and resolution
    n = int(180 * intensity * (w * h / (640 * 480)) ** 0.5)
    n = int(np.clip(n, 20, 1200))
    overlay = frame.astype(np.float32)
    # single mask for all streaks (M2 fix: was per-streak alloc 200MB)
    line_mask = np.zeros_like(frame, dtype=np.uint8)
    # collect alphas per line for varied opacity — use uniform alpha for batch to avoid per-pixel vary
    # draw all lines onto mask with white, then blend once with mean alpha 0.18
    for _ in range(n):
        x = int(np.random.randint(0, w))
        y = int(np.random.randint(0, h))
        length = int(np.random.randint(9, 22))
        thickness = int(np.random.choice([1, 1, 2]))
        angle = math.radians(np.random.uniform(68, 76))
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))
        val = 200  # mid of 175-225
        color = (val, val, val) if frame.ndim == 3 else val
        cv2.line(line_mask, (x, y), (x2, y2), color, thickness, cv2.LINE_AA)  # type: ignore
    # blend where mask >0 with fixed alpha 0.18 (was per-line 0.12-0.28)
    alpha = 0.18
    nz = line_mask > 0
    # line_mask is uint8 0 or ~200, convert to float for blend
    if np.any(nz):
        # approximate blended color 200 with alpha
        overlay[nz] = overlay[nz] * (1 - alpha) + line_mask[nz].astype(np.float32) * alpha
    overlay = np.clip(overlay, 0, 255).astype(np.uint8)
    return overlay


def apply_atmospheric_disturbance(
    frame: np.ndarray,
    preset: str = "Clear",
    contrast_reduction: float | None = None,
    brightness_reduction: float | None = None,
    *,
    intensity: float | None = None,
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

    # Optional blur for fog/haze scattering (small Gaussian)
    if blur_sigma > 0.05:
        ksize = int(np.clip(round(blur_sigma * 3.5) * 2 + 1, 3, 11))
        if ksize % 2 == 0:
            ksize += 1
        out = cv2.GaussianBlur(out, (ksize, ksize), sigmaX=blur_sigma)

    # Contrast / brightness reduction
    out = _apply_contrast_brightness(out, contrast, brightness)

    # Haze overlay — add low-freq desaturation towards grey if haze_factor >0
    if haze_factor > 1e-6:
        # blend toward 165 grey (hazy sky)
        haze_col = 165
        alpha = haze_factor
        out_f = out.astype(np.float32)
        if out.ndim == 3:
            out_f = out_f * (1 - alpha) + haze_col * alpha
        else:
            out_f = out_f * (1 - alpha) + haze_col * alpha
        out = np.clip(out_f, 0, 255).astype(np.uint8)

    # Rain streaks (only for Rain preset or when preset is Rain)
    if str(preset).lower() == "rain" or preset == "Rain":
        # intensity for rain = contrast/100 roughly
        rain_intensity = 0.22 + float(params.get("haze", 0.12)) * 0.6 + contrast / 400.0
        rain_intensity = float(np.clip(rain_intensity, 0.18, 0.55))
        out = _add_rain_streaks(out, intensity=rain_intensity)

    # Low Light also optionally desaturate a bit
    if str(preset).lower() in ("low light", "low_light"):
        # slight colour desaturation for night-like
        if out.ndim == 3:
            grey = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            grey3 = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
            out = cv2.addWeighted(out, 0.68, grey3, 0.32, 0)

    return out.astype(frame.dtype, copy=False)
