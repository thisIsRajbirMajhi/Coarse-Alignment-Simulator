# tracking/detector — Detection representation + YOLO26 runtime interface + classical fallback
#
# Design intent (per technical report):
#   YOLO transforms one camera frame -> list of beacon candidates.
#   It does NOT decide target identity, velocity, or use simulator truth.
#   Association / Tracker / State own those decisions downstream.
#
# Data contract:
#   Detection(bbox, center, width, height, confidence, class_id=0)

from __future__ import annotations

import os as _os

# Fix for Windows DLL clash: image lib loads its own OpenMP runtime which can
# break the model lib (c10.dll 1114) if image lib is imported first.
# Setting this before any heavy import allows both to coexist.
_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("KMP_BLOCKTIME", "0")
_os.environ.setdefault("OMP_NUM_THREADS", "1")

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from common.config_base import BaseValidatedConfig, clip_field


# ----------------------------------------------------------------------------
# Detection object
# ----------------------------------------------------------------------------

@dataclass
class Detection:
    """Single beacon hypothesis from one frame."""

    bbox: tuple[float, float, float, float]  # (x1, y1, x2, y2) in FOV pixels
    center: tuple[float, float]  # (cx, cy) precomputed for convenience
    width: float
    height: float
    confidence: float  # [0, 1]
    class_id: int = 0  # 0 = beacon (single class)
    latency_ms: float = 0.0  # detector time for this frame (diagnostics)

    def to_dict(self) -> dict:
        return {
            "bbox": tuple(float(v) for v in self.bbox),
            "center": tuple(float(v) for v in self.center),
            "width": float(self.width),
            "height": float(self.height),
            "confidence": float(self.confidence),
            "class_id": int(self.class_id),
        }


def bbox_to_center(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Geometrically correct centroid: cx=(x1+x2)/2, cy=(y1+y2)/2."""
    return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0


def pixel_error(cx: float, cy: float, fov_w: int = 640, fov_h: int = 480) -> tuple[float, float, float]:
    """Error vs boresight. Returns (error_x, error_y, error_px)."""
    bx, by = float(fov_w) / 2.0, float(fov_h) / 2.0
    ex, ey = float(cx) - bx, float(cy) - by
    return ex, ey, float(np.hypot(ex, ey))


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

DETECTOR_LIMITS = {
    "conf_threshold": (0.05, 0.90),
    "iou_threshold": (0.30, 0.95),
    "imgsz": (320, 1024),
    "threshold": (50, 255),  # classical fallback bright threshold
    "min_area": (4, 5000),
    "max_detections": (1, 20),
}

DETECTOR_DEFAULTS = {
    "conf_threshold": 0.25,
    "iou_threshold": 0.70,
    "imgsz": 640,
    "threshold": 80,
    "min_area": 6,
    "max_detections": 5,
    "device": "auto",
    "model_path": "",
    "use_classical_fallback": True,
}


@dataclass
class DetectorConfig(BaseValidatedConfig):
    LIMITS = DETECTOR_LIMITS
    DEFAULTS = DETECTOR_DEFAULTS

    conf_threshold: float = DETECTOR_DEFAULTS["conf_threshold"]
    iou_threshold: float = DETECTOR_DEFAULTS["iou_threshold"]
    imgsz: int = DETECTOR_DEFAULTS["imgsz"]
    threshold: int = DETECTOR_DEFAULTS["threshold"]
    min_area: int = DETECTOR_DEFAULTS["min_area"]
    max_detections: int = DETECTOR_DEFAULTS["max_detections"]
    device: str = DETECTOR_DEFAULTS["device"]
    model_path: str = DETECTOR_DEFAULTS["model_path"]
    use_classical_fallback: bool = DETECTOR_DEFAULTS["use_classical_fallback"]

    def validate(self) -> "DetectorConfig":
        self.conf_threshold = float(clip_field(self.conf_threshold, *self.LIMITS["conf_threshold"]))
        self.iou_threshold = float(clip_field(self.iou_threshold, *self.LIMITS["iou_threshold"]))
        self.imgsz = int(clip_field(int(self.imgsz), *self.LIMITS["imgsz"]))
        self.threshold = int(clip_field(int(self.threshold), *self.LIMITS["threshold"]))
        self.min_area = int(clip_field(int(self.min_area), *self.LIMITS["min_area"]))
        self.max_detections = int(clip_field(int(self.max_detections), *self.LIMITS["max_detections"]))
        if self.device not in ("auto", "cpu", "cuda"):
            self.device = "auto"
        self.use_classical_fallback = bool(self.use_classical_fallback)
        return self


def resolve_default_model() -> str:
    """Prefer trained best.pt, else bundled nano weights."""
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "runs" / "detect" / "beacon_yolo26n_best" / "weights" / "best.pt",
        root / "weights" / "yolo26n.pt",
        root / "yolo26n.pt",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


# ----------------------------------------------------------------------------
# YOLO26 runtime detector (inference only)
# ----------------------------------------------------------------------------

class YOLO26Detector:
    """Thin inference-only wrapper. Loads model once, predicts per frame."""

    def __init__(self, config: DetectorConfig | None = None, model_path: str | None = None):
        self.config = (config or DetectorConfig()).validate()
        if model_path:
            self.config.model_path = str(model_path)
        if not self.config.model_path:
            self.config.model_path = resolve_default_model()
        self._model: Any = None
        self._load_error: str = ""
        self.last_latency_ms: float = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str:
        return self._load_error

    def load(self) -> bool:
        if self._model is not None:
            return True
        mp = self.config.model_path
        if not mp or not Path(mp).exists():
            self._load_error = f"model not found: {mp}"
            return False
        try:
            from ultralytics import YOLO

            self._model = YOLO(mp)
            return True
        except Exception as e:  # pragma: no cover - hardware dependent
            self._load_error = str(e)
            self._model = None
            return False

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Run inference on BGR HxWx3 frame -> Detection list. Never raises."""
        t0 = time.perf_counter()
        try:
            if self._model is None and not self.load():
                return []
            img = frame
            if img is None or img.size == 0:
                return []
            # Ensure 3-channel BGR for YOLO
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            results = self._model.predict(
                img,
                conf=float(self.config.conf_threshold),
                iou=float(self.config.iou_threshold),
                imgsz=int(self.config.imgsz),
                verbose=False,
            )
            dets: list[Detection] = []
            if results:
                r = results[0]
                boxes = getattr(r, "boxes", None)
                if boxes is not None and len(boxes) > 0:
                    xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else np.asarray(boxes.xyxy)
                    conf = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
                    cls = boxes.cls.cpu().numpy() if hasattr(boxes.cls, "cpu") else np.asarray(boxes.cls)
                    h, w = frame.shape[:2]
                    for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
                        if int(k) != 0:
                            continue
                        cx, cy = bbox_to_center(float(x1), float(y1), float(x2), float(y2))
                        # Clamp to frame for safety
                        x1c, y1c = max(0.0, float(x1)), max(0.0, float(y1))
                        x2c, y2c = min(float(w), float(x2)), min(float(h), float(y2))
                        if x2c <= x1c or y2c <= y1c:
                            continue
                        dets.append(
                            Detection(
                                bbox=(float(x1c), float(y1c), float(x2c), float(y2c)),
                                center=(float(cx), float(cy)),
                                width=float(x2c - x1c),
                                height=float(y2c - y1c),
                                confidence=float(c),
                                class_id=0,
                            )
                        )
            # Sort by confidence desc, cap count
            dets.sort(key=lambda d: d.confidence, reverse=True)
            dets = dets[: int(self.config.max_detections)]
            lat = (time.perf_counter() - t0) * 1000.0
            self.last_latency_ms = lat
            for d in dets:
                d.latency_ms = lat
            return dets
        except Exception:
            self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
            return []


# ----------------------------------------------------------------------------
# Classical bright-spot fallback (for tests / when model unavailable)
# ----------------------------------------------------------------------------

class BrightSpotDetector:
    """Adaptive threshold + contour detector. No learning, no GT.

    Robustness fixes:
      - cascade thresholds (configured -> 80 -> 50) so dim rendered beacons
        are still found without flooding empty sky with false alarms
      - 3x3 close to merge fragmented spots, blur to suppress single-pixel noise
      - size sanity (reject huge boxes = background, tiny = hot pixel)
    """

    def __init__(self, config: DetectorConfig | None = None):
        self.config = (config or DetectorConfig()).validate()
        self.last_latency_ms: float = 0.0
        self.last_threshold_used: int = int(self.config.threshold)

    def _detect_at(self, gray: np.ndarray, thresh: int) -> list[Detection]:
        _, th = cv2.threshold(gray, int(thresh), 255, cv2.THRESH_BINARY)
        kernel = np.ones((3, 3), np.uint8)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = gray.shape[:2]
        dets: list[Detection] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < int(self.config.min_area):
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            # Reject absurd sizes: beacon is 5-20px, allow margin for bloom
            if bw > w * 0.25 or bh > h * 0.25:
                continue
            if bw < 2 or bh < 2:
                continue
            x1, y1, x2, y2 = float(x), float(y), float(x + bw), float(y + bh)
            cx, cy = bbox_to_center(x1, y1, x2, y2)
            roi = gray[int(y1):int(y2), int(x1):int(x2)]
            conf = float(np.mean(roi) / 255.0) if roi.size else 0.5
            dets.append(
                Detection(
                    bbox=(x1, y1, x2, y2),
                    center=(cx, cy),
                    width=float(bw),
                    height=float(bh),
                    confidence=float(np.clip(conf, 0.0, 1.0)),
                    class_id=0,
                )
            )
        return dets

    def detect(self, frame: np.ndarray) -> list[Detection]:
        t0 = time.perf_counter()
        try:
            if frame is None or getattr(frame, "size", 0) == 0:
                return []
            gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            # Cascade: user threshold first, then progressively lower only if empty.
            # Prevents false alarms on empty sky while catching dim beacons.
            primary = int(self.config.threshold)
            cascade = [primary] + [t for t in (80, 50) if t != primary]
            dets: list[Detection] = []
            used = primary
            for t in cascade:
                dets = self._detect_at(gray, t)
                if dets:
                    used = t
                    break
            self.last_threshold_used = int(used)
            dets.sort(key=lambda d: (d.confidence, d.width * d.height), reverse=True)
            dets = dets[: int(self.config.max_detections)]
            lat = (time.perf_counter() - t0) * 1000.0
            self.last_latency_ms = lat
            for d in dets:
                d.latency_ms = lat
            return dets
        except Exception:
            self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
            return []


class UnifiedDetector:
    """Try YOLO first, fall back to classical if YOLO unavailable or empty
    and fallback is enabled. Guarantees loop never crashes on missing weights."""

    def __init__(self, config: DetectorConfig | None = None, model_path: str | None = None):
        self.config = (config or DetectorConfig()).validate()
        self.yolo = YOLO26Detector(self.config, model_path=model_path)
        self.classical = BrightSpotDetector(self.config)
        self.last_used: str = "none"
        self.last_latency_ms: float = 0.0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        dets = self.yolo.detect(frame)
        if dets:
            self.last_used = "yolo"
            self.last_latency_ms = self.yolo.last_latency_ms
            return dets
        if self.config.use_classical_fallback:
            dets = self.classical.detect(frame)
            self.last_used = "classical" if dets else "none"
            self.last_latency_ms = self.classical.last_latency_ms
            return dets
        self.last_used = "none"
        self.last_latency_ms = self.yolo.last_latency_ms
        return []
