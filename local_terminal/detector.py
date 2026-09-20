# local_terminal/detector.py - Image-plane beacon spot detector (Plan.md §5.1-5.2).
#
# Thresholds are detection defaults pending ROC calibration (§9.4), not physics.
# Deterministic: same frame in -> same detections out (no RNG anywhere here).

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class DetectorConfig:
    """Photometric gates per Plan.md §5.1 (defaults; calibrate via ROC sweep)."""

    peak_min: float = 30.0        # peak pixel intensity floor (/255)
    sigma_min_px: float = 2.5     # Spot sigma floor (allows discretization margin for MIN_SPOT_SIGMA_PX=3.0)
    r2_min: float = 0.75          # Gaussian-fit compactness floor
    snr_min_db: float = 6.0       # SNR above local background floor
    isolation_px: float = 10.0    # merge candidates closer than this
    bg_annulus_px: int = 6        # background ring width around region
    max_candidates: int = 8       # cap, brightest-first

    def validate(self) -> "DetectorConfig":
        self.peak_min = float(np.clip(self.peak_min, 1.0, 255.0))
        self.sigma_min_px = float(np.clip(self.sigma_min_px, 0.5, 50.0))
        self.r2_min = float(np.clip(self.r2_min, 0.0, 1.0))
        self.snr_min_db = float(np.clip(self.snr_min_db, 0.0, 40.0))
        self.isolation_px = float(np.clip(self.isolation_px, 1.0, 100.0))
        self.bg_annulus_px = int(np.clip(int(self.bg_annulus_px), 1, 32))
        self.max_candidates = int(np.clip(int(self.max_candidates), 1, 64))
        return self


@dataclass
class Detection:
    """One photometric candidate in FOV pixel coordinates."""

    fov_x: float
    fov_y: float
    peak: float
    sigma_px: float
    snr_db: float
    compactness_r2: float
    pixel_count: int

    def to_dict(self) -> dict:
        return {
            "fov_x": float(self.fov_x),
            "fov_y": float(self.fov_y),
            "peak": float(self.peak),
            "sigma_px": float(self.sigma_px),
            "snr_db": float(self.snr_db),
            "compactness_r2": float(self.compactness_r2),
            "pixel_count": int(self.pixel_count),
        }


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        if frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY).astype(np.float64)
        return frame[:, :, 0].astype(np.float64)
    return frame.astype(np.float64)


def _log_gaussian_fit(vals: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    """Fit ln(I) = ln(peak) − r²/(2σ²) over thresholded pixels.

    Thresholding cuts the Gaussian tails, so moment-based σ underestimates the
    true width (a σ=3.0 spot measures ~2.4). The log-linear fit is immune: the
    model holds at every radius, so the slope recovers the true σ and the
    fit R² doubles as the Gaussian-compactness metric.

    Returns (sigma_px, r2). sigma is 0.0 when the slope is non-negative
    (brightness growing outward — not a spot).
    """
    y = np.log(np.clip(vals, 1e-3, None))
    x = r2
    x_c = x - x.mean()
    denom = float(np.sum(x_c ** 2))
    if denom < 1e-9 or y.size < 3:
        return 0.0, 0.0
    slope = float(np.sum(x_c * (y - y.mean())) / denom)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot < 1e-9:
        return 0.0, 0.0
    ss_res = float(np.sum((y - (y.mean() + slope * x_c)) ** 2))
    r2fit = float(max(0.0, min(1.0, 1.0 - ss_res / ss_tot)))
    if slope >= -1e-12:
        return 0.0, r2fit
    return math.sqrt(-1.0 / (2.0 * slope)), r2fit


def detect_candidates(frame: np.ndarray, config: DetectorConfig | None = None) -> list[Detection]:
    """Find beacon-spot candidates in a FOV frame (Plan.md §5.1-5.2).

    Args:
        frame: H×W (or H×W×3) uint8 FOV image.
        config: thresholds; defaults per Plan.md §5.1.

    Returns brightest-first detections passing ALL gates. Regions failing any
    gate are discarded silently (never logged/blacklisted — §5.1).
    """
    cfg = (config or DetectorConfig()).validate()
    if frame is None or frame.size == 0:
        return []
    gray = _to_gray(frame)
    h, w = gray.shape

    bg_floor = float(np.median(gray))
    thresh = max(cfg.peak_min, bg_floor + 8.0)
    mask = (gray >= thresh).astype(np.uint8)
    if not mask.any():
        return []
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    found: list[Detection] = []
    for idx in range(1, n):
        x0, y0, bw, bh, area = (int(stats[idx, 0]), int(stats[idx, 1]), int(stats[idx, 2]),
                                int(stats[idx, 3]), int(stats[idx, 4]))
        comp = labels[y0:y0 + bh, x0:x0 + bw] == idx
        if not comp.any():
            continue
        patch = gray[y0:y0 + bh, x0:x0 + bw]
        vals = patch[comp]
        peak = float(vals.max())
        if peak < cfg.peak_min:
            continue
        weights = (vals - bg_floor) / max((vals - bg_floor).sum(), 1e-9)
        yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float64)
        cx = float(np.sum(xx[comp] * weights)) + x0
        cy = float(np.sum(yy[comp] * weights)) + y0
        rr = ((xx[comp] + x0) - cx) ** 2 + ((yy[comp] + y0) - cy) ** 2
        sigma, r2 = _log_gaussian_fit(vals - bg_floor, rr)
        if sigma < cfg.sigma_min_px:
            continue
        if r2 < cfg.r2_min:
            continue
        # Local background: expanded window minus component pixels.
        ex0, ey0 = max(0, x0 - cfg.bg_annulus_px), max(0, y0 - cfg.bg_annulus_px)
        ex1, ey1 = min(w, x0 + bw + cfg.bg_annulus_px), min(h, y0 + bh + cfg.bg_annulus_px)
        win = gray[ey0:ey1, ex0:ex1]
        win_mask = np.zeros_like(win, dtype=bool)
        win_mask[y0 - ey0:y0 - ey0 + bh, x0 - ex0:x0 - ex0 + bw] = comp
        bg = win[~win_mask]
        if bg.size < 4:
            continue
        bg_mean, bg_std = float(bg.mean()), float(max(bg.std(), 1e-3))
        snr_db = 20.0 * math.log10(max(peak - bg_mean, 1e-3) / bg_std)
        if snr_db < cfg.snr_min_db:
            continue
        found.append(Detection(fov_x=cx, fov_y=cy, peak=peak, sigma_px=sigma,
                               snr_db=snr_db, compactness_r2=r2, pixel_count=area))

    # Spatial isolation: merge closer than isolation_px, keep brighter.
    found.sort(key=lambda d: d.peak, reverse=True)
    kept: list[Detection] = []
    for det in found:
        if all(math.hypot(det.fov_x - k.fov_x, det.fov_y - k.fov_y) >= cfg.isolation_px for k in kept):
            kept.append(det)
        if len(kept) >= cfg.max_candidates:
            break
    return kept


__all__ = ["Detection", "DetectorConfig", "detect_candidates"]
