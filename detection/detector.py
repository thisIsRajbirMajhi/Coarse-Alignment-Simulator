"""
Detection module — supports single & multi-beacon.

Single-beacon: detect() returns brightest blob centroid (back-compat).
Multi-beacon: detect_all() returns every bright blob (sorted by brightness/area),
each with centroid, area, peak brightness and confidence — used for hitbox
association. Pure CV, no memory.
"""

import cv2
import numpy as np


class BeaconDetector:
    def __init__(self, brightness_threshold: int = 200, min_area: int = 2):
        self.brightness_threshold = int(brightness_threshold)
        self.min_area = int(min_area)

    def detect(self, frame: np.ndarray) -> tuple[float, float] | None:
        """Return brightest beacon (x,y) in frame coords, or None."""
        all_dets = self.detect_all(frame)
        if not all_dets:
            return None
        # most confident first
        return (all_dets[0]["x"], all_dets[0]["y"])

    def detect_all(self, frame: np.ndarray, max_beacons: int = 12) -> list[dict]:
        """
        Return list of detections sorted by confidence (area*peak).
        Each dict: {x,y, area, peak, confidence, bbox}
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        _, mask = cv2.threshold(gray, self.brightness_threshold, 255, cv2.THRESH_BINARY)
        # close small gaps from scintillation
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets: list[dict] = []
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < self.min_area:
                continue
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            cx = float(M["m10"] / M["m00"])
            cy = float(M["m01"] / M["m00"])
            x, y, w, h = cv2.boundingRect(cnt)
            # peak brightness in bbox
            roi = gray[y:y+h, x:x+w]
            peak = int(roi.max()) if roi.size else 0
            conf = float(area * (peak / 255.0))
            dets.append({"x": cx, "y": cy, "area": area, "peak": peak, "confidence": conf, "bbox": (x, y, w, h)})
        dets.sort(key=lambda d: d["confidence"], reverse=True)
        return dets[:max_beacons]

    def detect_with_hitbox(self, frame: np.ndarray, hitbox_radius: int | None = None) -> dict | None:
        """
        Convenience: returns detection plus whether it lies in hitbox vs perfect center.
        Not used for tracking — GUI uses beacons' own hitbox test against detection.
        """
        d = self.detect(frame)
        if d is None:
            return None
        return {"pos": d, "hitbox_radius": hitbox_radius}
