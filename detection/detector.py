"""
Module: detection.detector
Purpose: Beacon detection — raw per-frame input (no lock state), well-commented maths/physics.
Public API: BeaconDetector
Architecture:
  - constants.py : limits/defaults
  - config.py    : DetectorConfig (typed thresholds)
  - preprocessing.py : grayscale + threshold + closing
  - detector.py  : BeaconDetector — contour + moments → centroid, sorted by confidence
Notes:
  - Stateless: runs every new frame and returns position or None, regardless of lock state.
  - Physics: threshold → binary mask, contour area, image moments for centroid:
      M00 = Σ I(x,y)          (area)
      M10 = Σ x·I(x,y), M01 = Σ y·I(x,y)
      centroid = (M10/M00, M01/M00)  (first-order moments / area)
  - Confidence = area * (peak/255) — larger/brighter blobs rank higher.
"""

from __future__ import annotations

import cv2
import numpy as np

from detection.config import DetectorConfig
from detection.constants import DETECTOR_DEFAULTS
from detection.preprocessing import close_gaps, threshold_frame, to_grayscale

# ============================================================
# SECTION: BeaconDetector — stateless per-frame detection
# ============================================================

class BeaconDetector:
    """
    Stateless beacon detector — raw input for tracking.

    - detect(frame) → (x,y) brightest or None
    - detect_all(frame) → list[dict] sorted by confidence (area*peak)
    - detect_with_hitbox(...) convenience (not used for tracking)

    No memory: every frame is independent. Lock logic lives in tracking.Tracker.
    """

    def __init__(self, brightness_threshold: int = DETECTOR_DEFAULTS["brightness_threshold"], min_area: int = DETECTOR_DEFAULTS["min_area"], config: DetectorConfig | None = None):
        # Config-driven or legacy direct thresholds
        if config is not None:
            cfg = config.validate()
            self.config = cfg
            self.brightness_threshold = int(cfg.brightness_threshold)
            self.min_area = int(cfg.min_area)
        else:
            self.config = DetectorConfig(brightness_threshold=int(brightness_threshold), min_area=int(min_area)).validate()
            self.brightness_threshold = int(self.config.brightness_threshold)
            self.min_area = int(self.config.min_area)

    # --------------------------------------------------------
    # Config bridge — hot-apply without rebuild
    # --------------------------------------------------------

    def apply_config(self, config: DetectorConfig) -> None:
        cfg = config.validate()
        self.config = cfg
        self.brightness_threshold = int(cfg.brightness_threshold)
        self.min_area = int(cfg.min_area)

    def to_config(self) -> DetectorConfig:
        return DetectorConfig(brightness_threshold=int(self.brightness_threshold), min_area=int(self.min_area)).validate()

    # --------------------------------------------------------
    # Single-beacon — brightest
    # --------------------------------------------------------

    def detect(self, frame: np.ndarray) -> tuple[float, float] | None:
        """
        Return brightest beacon (x,y) in frame coords, or None.

        Wrapper over detect_all — picks most confident (area*peak) blob.
        """
        all_dets = self.detect_all(frame)
        if not all_dets:
            return None
        return (all_dets[0]["x"], all_dets[0]["y"])

    # --------------------------------------------------------
    # Multi-beacon — all blobs sorted by confidence
    # --------------------------------------------------------

    def detect_all(self, frame: np.ndarray, max_beacons: int = 12) -> list[dict]:
        """
        Return all bright blobs sorted by confidence.

        Pipeline (per frame, stateless):
          1) Grayscale: Y = 0.114B+0.587G+0.299R
          2) Threshold: mask = (Y > T) ? 255 : 0
          3) Closing: mask = close(mask, 3×3, 1) — fills scintillation holes
          4) Contours: findContours(RETR_EXTERNAL)
             For each contour:
               area = contourArea(cnt)  — reject if < min_area
               M = moments(cnt): M00, M10, M01
               if M00==0: skip (degenerate)
               cx = M10/M00, cy = M01/M00  — centroid (first moments / area)
               bbox = boundingRect(cnt)
               peak = max(gray[roi])  — brightest pixel in bbox
               confidence = area * (peak/255)  — larger/brighter → higher

        Returns list[dict] sorted descending by confidence, capped to max_beacons.
        Each dict: {x,y, area, peak, confidence, bbox}
        """
        gray = to_grayscale(frame)
        mask = threshold_frame(gray, self.brightness_threshold)
        mask = close_gaps(mask)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets: list[dict] = []
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < float(self.min_area):
                continue
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            # Centroid via image moments — sub-pixel accuracy from contour
            cx = float(M["m10"] / M["m00"])
            cy = float(M["m01"] / M["m00"])
            x, y, w, h = cv2.boundingRect(cnt)
            roi = gray[y:y+h, x:x+w]
            peak = int(roi.max()) if roi.size else 0
            conf = float(area * (float(peak) / 255.0))
            dets.append({"x": cx, "y": cy, "area": area, "peak": peak, "confidence": conf, "bbox": (x, y, w, h)})
        dets.sort(key=lambda d: d["confidence"], reverse=True)
        cap = int(self.config.max_beacons) if hasattr(self, "config") else int(max_beacons)
        # Respect caller cap but also config max
        cap = min(int(cap), int(max_beacons))
        return dets[:cap]

    def detect_with_hitbox(self, frame: np.ndarray, hitbox_radius: int | None = None) -> dict | None:
        """
        Convenience: returns detection plus hitbox radius (for GUI debug).
        Not used for tracking — GUI does hitbox gating against beacon's own hitbox.
        """
        d = self.detect(frame)
        if d is None:
            return None
        return {"pos": d, "hitbox_radius": hitbox_radius}
