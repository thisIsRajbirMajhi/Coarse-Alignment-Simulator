# local_terminal/detector.py - V2 classical spot detector (Plan V2 §8-§9, §17).
#
# Minimal deterministic pipeline:
#   frame → gray → background (median) → threshold → connected components
#   → area/SNR gates → centroid → SpotCandidate[]
# plus temporal confirmation (2-3 frames) to reject hot pixels.
# No Gaussian fit, no composite confidence, no ML.

from __future__ import annotations

import math

import cv2
import numpy as np

from local_terminal.models import AutonomyConfig, SpotCandidate


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        if frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY).astype(np.float64)
        return frame[:, :, 0].astype(np.float64)
    return frame.astype(np.float64)


def detect_spots(frame, config: AutonomyConfig | None = None) -> list[SpotCandidate]:
    """V2 fast spot detector: threshold + connected components + area/SNR."""
    cfg = (config or AutonomyConfig()).validate()
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    gray = _to_gray(frame)
    bg_floor = float(np.median(gray))
    thresh = bg_floor + float(cfg.candidate_peak_margin)
    mask = (gray >= thresh).astype(np.uint8)
    if not mask.any():
        return []
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_snr = float(cfg.candidate_min_snr_db)
    min_area = int(cfg.candidate_min_area_px)
    max_area = int(cfg.candidate_max_area_px)
    out: list[SpotCandidate] = []
    for idx in range(1, n):
        x0, y0, bw, bh, area = (int(stats[idx, 0]), int(stats[idx, 1]), int(stats[idx, 2]),
                                int(stats[idx, 3]), int(stats[idx, 4]))
        if area < min_area or area > max_area:
            continue
        comp = labels[y0:y0 + bh, x0:x0 + bw] == idx
        if not comp.any():
            continue
        patch = gray[y0:y0 + bh, x0:x0 + bw]
        vals = patch[comp]
        peak = float(vals.max())
        weights = (vals - bg_floor) / max((vals - bg_floor).sum(), 1e-9)
        yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float64)
        cx = float(np.sum(xx[comp] * weights)) + x0
        cy = float(np.sum(yy[comp] * weights)) + y0
        bg_ring = 6
        ex0, ey0 = max(0, x0 - bg_ring), max(0, y0 - bg_ring)
        ex1, ey1 = min(gray.shape[1], x0 + bw + bg_ring), min(gray.shape[0], y0 + bh + bg_ring)
        win = gray[ey0:ey1, ex0:ex1]
        win_mask = np.zeros_like(win, dtype=bool)
        win_mask[y0 - ey0:y0 - ey0 + bh, x0 - ex0:x0 - ex0 + bw] = comp
        bg = win[~win_mask]
        if bg.size < 4:
            continue
        bg_mean, bg_std = float(bg.mean()), float(max(bg.std(), 1e-3))
        snr_db = 20.0 * math.log10(max(peak - bg_mean, 1e-3) / bg_std)
        if snr_db < min_snr:
            continue
        out.append(SpotCandidate(x=cx, y=cy, peak=peak, snr_db=snr_db, area_px=int(area)))
    out.sort(key=lambda d: d.peak, reverse=True)
    return out[:8]


class TemporalConfirmer:
    """Require N consecutive detections near same location (§9.3)."""

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
            votes = 1
            for prev_frame in self._history[:-1]:
                if any(math.hypot(cand.x - p.x, cand.y - p.y) <= self.gate_px for p in prev_frame):
                    votes += 1
            if votes >= self.confirm_frames:
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
