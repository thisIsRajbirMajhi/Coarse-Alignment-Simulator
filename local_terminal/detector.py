# local_terminal/detector.py - V2 classical spot detector (Plan V2 §8-§9, §17).
#
# Optimized for 60 FPS + max-star robustness: frame → gray (uint8) → background
# (downsampled median) → threshold → morph open → connected components
# → area/shape/SNR gates → centroid → SpotCandidate[] plus temporal confirmation.

from __future__ import annotations

import math

import cv2
import numpy as np

from local_terminal.models import AutonomyConfig, SpotCandidate


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        if frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        return frame[:, :, 0].copy()
    return frame.copy()


def detect_spots(frame, config: AutonomyConfig | None = None) -> list[SpotCandidate]:
    """V2 hardened spot detector: robust bg + matched filter + shape/SNR.
    Hardened vs stars/haze/hot-pixels:
      - percentile bg (30th) resists star-inflated median
      - Gaussian matched filter (sigma~1.2) boosts sigma2-3 beacons 2-3x vs 1px hot pixels
      - intensity-weighted centroid for subpixel accuracy
      - star/hard-negative rejection via area+fill+SNR tightened
    """
    cfg = (config or AutonomyConfig()).validate()
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    gray = _to_gray(frame)
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    # --- Robust background: 30th percentile on downsampled, fallback median ---
    try:
        small = gray[::4, ::4]
        # 30th percentile resists star contamination (median biased high by 4000 stars)
        # but clip to median if haze lifts background strongly (preserve sensitivity)
        p30 = float(np.percentile(small, 30))
        med = float(np.median(small))
        # Use p30 but not too far from median (haze/fog uniform lift)
        bg_floor = float(np.clip(p30, med - 12, med))
    except Exception:
        try:
            bg_floor = float(np.median(gray))
        except Exception:
            bg_floor = 12.0
    # Adaptive margin: under high background (fog ~40) increase slightly to cut haze false
    margin = float(cfg.candidate_peak_margin)
    if bg_floor > 35:
        margin += 2.0
    thresh = int(np.clip(bg_floor + margin, 0, 255))
    # --- Matched filter: Gaussian sigma 1.2 boosts beacon (sigma 2-3) 2-3x vs hot pixel ---
    try:
        # Small blur before threshold: single-pixel S&P collapses, beacon retains ~75% peak
        gray_for_thresh = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.1, sigmaY=1.1)
    except Exception:
        gray_for_thresh = gray
    _, mask = cv2.threshold(gray_for_thresh, thresh, 255, cv2.THRESH_BINARY)
    if not np.any(mask):
        return []
    # Morph open to remove haze texture and residual 1-2px defects while keeping beacons
    try:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        if not np.any(mask):
            return []
    except Exception:
        pass
    # Connected components on 8-bit mask (expects 0/255)
    mask_bin = (mask > 0).astype(np.uint8)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_bin, connectivity=8)
    if n <= 1:
        return []
    # Global bg stats for prefilter (fast)
    try:
        bg_pixels = gray[mask_bin == 0]
        if bg_pixels.size > 200:
            bg_mean_g = float(bg_pixels.mean())
            bg_std_g = float(max(float(bg_pixels.std()), 1.5))
        else:
            bg_mean_g, bg_std_g = bg_floor, 3.0
    except Exception:
        bg_mean_g, bg_std_g = bg_floor, 3.0

    min_snr = float(cfg.candidate_min_snr_db)
    # Enforce selective area even if config is permissive (4-4000) - beacons are 12-200
    cfg_min_area = int(cfg.candidate_min_area_px)
    cfg_max_area = int(cfg.candidate_max_area_px)
    min_area = max(12, cfg_min_area)
    max_area = min(250, cfg_max_area)

    # Cap components for 4000-star fields
    if n - 1 > 60:
        areas = stats[1:, cv2.CC_STAT_AREA]
        top_idx = np.argsort(areas)[::-1][:50] + 1
        iter_indices = top_idx
    else:
        iter_indices = range(1, n)

    out: list[SpotCandidate] = []
    # Precompute blurred gray for shape validation (hot pixel vs beacon)
    try:
        _gray_blur_q = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.1)
    except Exception:
        _gray_blur_q = gray
    for idx in iter_indices:
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < min_area or area > max_area:
            continue
        bw = int(stats[idx, cv2.CC_STAT_WIDTH])
        bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        if bw < 2 or bh < 2:
            continue
        # Shape: fill ratio and aspect for circular spots vs haze streaks
        fill = float(area) / max(1, bw * bh)
        if not (0.25 <= fill <= 0.90):
            continue
        aspect = float(min(bw, bh)) / max(1, max(bw, bh))
        if aspect < 0.35:
            continue
        # Hot-pixel discriminator: single-pixel S&P collapses after blur (<0.45), beacon stays >0.55
        try:
            _cx_i, _cy_i = int(round(float(centroids[idx, 0]))), int(round(float(centroids[idx, 1])))
            if 0 <= _cy_i < gray.shape[0] and 0 <= _cx_i < gray.shape[1]:
                _orig_pk = float(gray[_cy_i, _cx_i])
                _blur_pk = float(_gray_blur_q[_cy_i, _cx_i])
                if _orig_pk > 1 and _blur_pk / max(_orig_pk, 1) < 0.42 and area < 18:
                    continue
        except Exception:
            pass
        # Intensity-weighted centroid (subpixel, ~0.7px more accurate than binary centroid)
        try:
            x0w = int(stats[idx, cv2.CC_STAT_LEFT]); y0w = int(stats[idx, cv2.CC_STAT_TOP])
            patch_w = gray[max(0,y0w):y0w+bh, max(0,x0w):x0w+bw]
            lbl_w = labels[max(0,y0w):y0w+bh, max(0,x0w):x0w+bw]
            m = (lbl_w == idx)
            if np.any(m):
                ys, xs = np.where(m)
                ws = patch_w[m].astype(float) - bg_floor
                ws = np.clip(ws, 0, 255)
                wsum = float(ws.sum())
                if wsum > 1e-6:
                    cx = float(x0w + (xs * ws).sum() / wsum)
                    cy = float(y0w + (ys * ws).sum() / wsum)
                else:
                    cx, cy = float(centroids[idx, 0]), float(centroids[idx, 1])
            else:
                cx, cy = float(centroids[idx, 0]), float(centroids[idx, 1])
        except Exception:
            cx, cy = float(centroids[idx, 0]), float(centroids[idx, 1])
        # Peak in bounding box
        x0 = int(stats[idx, cv2.CC_STAT_LEFT])
        y0 = int(stats[idx, cv2.CC_STAT_TOP])
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(gray.shape[1], x0 + bw), min(gray.shape[0], y0 + bh)
        if x1c <= x0c or y1c <= y0c:
            continue
        patch = gray[y0c:y1c, x0c:x1c]
        lbl_patch = labels[y0c:y1c, x0c:x1c]
        vals = patch[lbl_patch == idx]
        if vals.size == 0:
            continue
        peak = float(vals.max())
        # Global SNR prefilter (fast)
        snr_g = 20.0 * math.log10(max(peak - bg_mean_g, 1e-3) / bg_std_g)
        if snr_g < min_snr - 1.0:  # lenient prefilter
            continue
        # Local SNR refine for top candidates (accurate, per-component ring)
        # Use 6px ring around bbox for local background
        bg_ring = 6
        ex0, ey0 = max(0, x0 - bg_ring), max(0, y0 - bg_ring)
        ex1, ey1 = min(gray.shape[1], x0 + bw + bg_ring), min(gray.shape[0], y0 + bh + bg_ring)
        win = gray[ey0:ey1, ex0:ex1]
        win_mask = np.zeros_like(win, dtype=bool)
        # Map component mask into win
        win_mask[y0 - ey0:y0 - ey0 + bh, x0 - ex0:x0 - ex0 + bw] = (lbl_patch == idx) if lbl_patch.shape == (bh, bw) else False
        # Fallback if shape mismatch
        if win_mask.shape != win.shape:
            bg_local = bg_pixels
        else:
            bg_local = win[~win_mask]
        if bg_local.size < 8:
            snr_db = snr_g
        else:
            bg_m = float(bg_local.mean())
            bg_s = float(max(float(bg_local.std()), 1.5))
            snr_db = 20.0 * math.log10(max(peak - bg_m, 1e-3) / bg_s)
        if snr_db < min_snr:
            continue
        # Quality score for ranking: prefer high SNR beacons over bright stars (stars often high peak but low SNR due to local bg)
        out.append(SpotCandidate(x=cx, y=cy, peak=peak, snr_db=snr_db, area_px=area))
    # Rank by composite quality (SNR-weighted) not raw peak: beacon high-SNR > star high-peak
    out.sort(key=lambda d: (d.snr_db * 0.7 + d.peak * 0.03 + d.area_px * 0.02), reverse=True)
    return out[:8]


class TemporalConfirmer:
    """Require N consecutive detections near same location (§9.3).
    Hardened: SNR/area consistency across frames prevents bright transient (S&P)
    from confirming via a nearby star coincidence."""

    def __init__(self, confirm_frames: int = 2, gate_px: float = 12.0):
        self.confirm_frames = int(max(1, min(5, confirm_frames)))
        self.gate_px = float(max(1.0, gate_px))
        self._history: list[list] = []

    def update(self, spots) -> list:
        self._history.append(list(spots or []))
        del self._history[:-self.confirm_frames]
        if len(self._history) < self.confirm_frames:
            return []
        confirmed = []
        for cand in self._history[-1]:
            # Find best matching predecessor in each prior frame
            matches = []
            ok = True
            for prev_frame in self._history[:-1]:
                best = None
                best_d2 = 1e9
                for p in prev_frame:
                    d = math.hypot(cand.x - p.x, cand.y - p.y)
                    if d <= self.gate_px and d*d < best_d2:
                        best_d2 = d*d
                        best = p
                if best is None:
                    ok = False
                    break
                # Consistency: area within 50% and SNR within 6dB across frames (reject random coincidences)
                try:
                    area_ok = abs(float(best.area_px) - float(cand.area_px)) <= max(6, 0.5*float(cand.area_px))
                    snr_ok = abs(float(best.snr_db) - float(cand.snr_db)) <= 7.0
                    if not (area_ok and snr_ok):
                        ok = False
                        break
                except Exception:
                    pass
                matches.append(best)
            if ok:
                confirmed.append(cand)
        return confirmed

    def reset(self) -> None:
        self._history.clear()


class SpotDetector:
    """V2 detector interface (§17): classical now, AI drop-in later."""

    def detect(self, frame, config=None) -> list:
        raise NotImplementedError


class ClassicalSpotDetector(SpotDetector):
    """V2 default detector: detect_spots + temporal confirmation."""

    def __init__(self, config=None, confirm_frames: int = 2, gate_px: float = 12.0):
        self.config = config
        self.confirmer = TemporalConfirmer(confirm_frames, gate_px)

    def detect(self, frame, config=None) -> list:
        cfg = config if config is not None else self.config
        return self.confirmer.update(detect_spots(frame, cfg))

    def reset(self) -> None:
        self.confirmer.reset()


__all__ = ["detect_spots", "TemporalConfirmer", "SpotDetector", "ClassicalSpotDetector"]
