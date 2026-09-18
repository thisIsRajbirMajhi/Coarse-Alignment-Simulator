# local_terminal/detection.py - Image-only optical detection per LocalTerminal.md
#
# NOTE: the ground-truth DetectionEngine.evaluate_target() API
# (beacon_power/wavelength passed directly) has been deleted. Perception is
# image-only: detect_beacon_candidates + estimate_wavelength_nm measure spots
# from pixels; signature scoring compares against the LOCAL config.
from __future__ import annotations

import math
from typing import Any

import numpy as np


def detect_beacon_candidates(frame, *, minimum_peak: float = 40.0) -> list[dict[str, Any]]:
    """Find bright compact optical sources using *only* the captured image.

    Returned positions, size, colour and SNR are measured quantities.  This is
    deliberately independent of ``RemoteTerminal`` or world coordinates so it
    can be used unchanged with a real camera feed.
    """
    if frame is None:
        return []
    arr = np.asarray(frame)
    if arr.ndim not in (2, 3) or arr.size == 0:
        return []
    if arr.ndim == 2:
        bgr = np.repeat(arr[..., None], 3, axis=2)
    else:
        bgr = arr[..., :3]
    image = bgr.astype(np.float32)
    gray = image.mean(axis=2)
    # A local scene can be bright; select peaks substantially above the robust
    # background while retaining a fixed floor for a dark scene.
    bg = float(np.median(gray))
    noise = float(np.median(np.abs(gray - bg)) * 1.4826)
    threshold = max(float(minimum_peak), bg + max(12.0, 4.0 * noise))
    mask = (gray >= threshold).astype(np.uint8)
    if not np.any(mask):
        return []
    try:
        import cv2
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    except Exception:
        # Dependency-free fallback: the strongest pixel is still a useful
        # acquisition measurement when OpenCV is unavailable.
        y, x = np.unravel_index(int(np.argmax(gray)), gray.shape)
        return [{"x": float(x), "y": float(y), "peak_dn": float(gray[y, x]),
                 "snr_db": 0.0, "diameter_px": 1.0,
                 "bgr": tuple(float(v) for v in image[y, x])}]

    candidates: list[dict[str, Any]] = []
    h, w = gray.shape
    for label in range(1, count):
        x, y, cw, ch, area = stats[label]
        # Reject isolated hot pixels and broad bright scenery.
        if area < 2 or area > max(400, (h * w) // 20):
            continue
        component = labels[y:y + ch, x:x + cw] == label
        values = gray[y:y + ch, x:x + cw][component]
        weights = np.maximum(values - bg, 1.0)
        ys, xs = np.nonzero(component)
        cx = float(x + np.average(xs, weights=weights))
        cy = float(y + np.average(ys, weights=weights))
        peak = float(values.max())
        # Estimate background/noise around the source, excluding its core.
        pad = max(5, int(max(cw, ch)))
        bx0, bx1 = max(0, x - pad), min(w, x + cw + pad)
        by0, by1 = max(0, y - pad), min(h, y + ch + pad)
        border = gray[by0:by1, bx0:bx1].copy()
        border[y - by0:y - by0 + ch, x - bx0:x - bx0 + cw][component] = np.nan
        local_bg = float(np.nanmedian(border)) if np.isfinite(border).any() else bg
        local_noise = float(np.nanstd(border)) if np.isfinite(border).any() else noise
        snr = 20.0 * math.log10(max(peak - local_bg, 1e-6) / max(local_noise, 1.0))
        colour = image[y:y + ch, x:x + cw][component]
        candidates.append({
            "x": cx, "y": cy, "peak_dn": peak,
            "snr_db": float(max(0.0, min(snr, 60.0))),
            "diameter_px": float(max(cw, ch)),
            "bgr": tuple(float(v) for v in colour.mean(axis=0)),
        })
    return candidates


def estimate_wavelength_nm(bgr: tuple[float, float, float]) -> tuple[float, float]:
    """Estimate the renderer/camera spectral class from measured BGR colour.

    The second value is a 0..1 confidence.  A production monochrome camera
    would replace this with a filter-bank measurement; the interface remains
    image-derived either way.
    """
    references = {
        1550.0: (220.0, 240.0, 255.0), 1064.0: (245.0, 230.0, 255.0),
        850.0: (200.0, 210.0, 255.0), 532.0: (100.0, 255.0, 120.0),
        650.0: (80.0, 100.0, 255.0),
    }
    # Compare chromaticity, not absolute brightness: propagation and range
    # change brightness dramatically but should not alter the spectral class.
    sample = np.asarray(bgr, dtype=float)
    sample = sample / max(float(sample.max()), 1.0)
    wavelength, distance = min(
        ((wl, float(np.linalg.norm(sample - np.asarray(tint) / max(tint)))) for wl, tint in references.items()),
        key=lambda item: item[1],
    )
    return float(wavelength), float(np.clip(1.0 - distance / 0.4, 0.0, 1.0))


def estimate_spot_brightness(
    frame,
    spot_fov: tuple[float, float] | None,
    patch_half: int = 4,
) -> tuple[float, float]:
    """Measure peak DN and background-contrast SNR at a candidate spot.

    Returns (peak_dn, snr_db). SNR is estimated as
    20*log10(max(peak-bg, eps) / max(noise, eps)) where bg/noise come from
    a surrounding border. Returns (0.0, 0.0) when frame/spot is missing.
    Pure helper — no state, safe to call with None.
    """
    try:
        import numpy as _np

        if frame is None or spot_fov is None:
            return 0.0, 0.0
        arr = _np.asarray(frame)
        if arr.size == 0:
            return 0.0, 0.0
        if arr.ndim == 3:
            gray = arr[..., :].astype(float).mean(axis=2)
        else:
            gray = arr.astype(float)
        fh, fw = gray.shape[:2]
        cx, cy = float(spot_fov[0]), float(spot_fov[1])
        if not (-patch_half <= cx < fw + patch_half and -patch_half <= cy < fh + patch_half):
            return 0.0, 0.0
        x0 = max(0, int(round(cx)) - patch_half)
        x1 = min(fw, int(round(cx)) + patch_half + 1)
        y0 = max(0, int(round(cy)) - patch_half)
        y1 = min(fh, int(round(cy)) + patch_half + 1)
        if x1 <= x0 or y1 <= y0:
            return 0.0, 0.0
        patch = gray[y0:y1, x0:x1]
        peak = float(patch.max())
        # Background border: outer ring 2x patch around center, excluding patch.
        bx0 = max(0, x0 - patch_half * 2)
        bx1 = min(fw, x1 + patch_half * 2)
        by0 = max(0, y0 - patch_half * 2)
        by1 = min(fh, y1 + patch_half * 2)
        border = gray[by0:by1, bx0:bx1].copy()
        border[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0] = float("nan")
        with _np.errstate(all="ignore"):
            bg = float(_np.nanmedian(border))
            noise = float(_np.nanstd(border))
        if not math.isfinite(bg):
            bg = 0.0
        if not math.isfinite(noise) or noise < 1e-6:
            noise = 1.0
        contrast = max(0.0, peak - bg)
        snr_db = 20.0 * math.log10(max(contrast, 1e-6) / max(noise, 1e-6))
        return peak, float(max(0.0, min(snr_db, 60.0)))
    except Exception:
        return 0.0, 0.0
