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
    center: tuple[float, float]  # (cx, cy) refined centroid where available
    width: float
    height: float
    confidence: float  # [0, 1] calibrated where possible
    class_id: int = 0  # 0 = beacon (single class)
    latency_ms: float = 0.0  # detector time for this frame (diagnostics)
    # Phase-1 robustness fields (optional, backward compatible):
    pos_var: float = 9.0  # measurement variance px^2 for KF R (from conf/size)
    source: str = "unknown"  # "yolo" | "classical" | "fused"
    area: float = 0.0  # bbox area px^2
    circularity: float = 1.0  # 1.0 = compact/blob-like, 0 = streak/noise

    def to_dict(self) -> dict:
        return {
            "bbox": tuple(float(v) for v in self.bbox),
            "center": tuple(float(v) for v in self.center),
            "width": float(self.width),
            "height": float(self.height),
            "confidence": float(self.confidence),
            "class_id": int(self.class_id),
            "pos_var": float(self.pos_var),
            "source": str(self.source),
            "area": float(self.area if self.area else self.width * self.height),
            "circularity": float(self.circularity),
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
# Phase-1 helpers: sub-pixel localization, uncertainty, fusion
# ----------------------------------------------------------------------------

def intensity_refined_centroid(gray: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Intensity-weighted centroid inside bbox; falls back to geometric center.

    More accurate than (x1+x2)/2 for bloomed/asymmetric beacons (±0.5-1px gain).
    Never raises — returns geometric center on any failure.
    """
    try:
        h, w = gray.shape[:2]
        ix1, iy1 = max(0, int(x1)), max(0, int(y1))
        ix2, iy2 = min(w, int(np.ceil(x2))), min(h, int(np.ceil(y2)))
        if ix2 <= ix1 or iy2 <= iy1:
            return bbox_to_center(x1, y1, x2, y2)
        roi = gray[iy1:iy2, ix1:ix2].astype(np.float64)
        if roi.size == 0:
            return bbox_to_center(x1, y1, x2, y2)
        roi = np.clip(roi - float(np.min(roi)), 0.0, None)
        total = float(np.sum(roi))
        if total < 1e-9:
            return bbox_to_center(x1, y1, x2, y2)
        ys, xs = np.mgrid[iy1:iy2, ix1:ix2].astype(np.float64)
        cx = float(np.sum(xs * roi) / total)
        cy = float(np.sum(ys * roi) / total)
        # Sanity: keep inside expanded bbox (rejects bleed from neighbours)
        if not (x1 - 3 <= cx <= x2 + 3 and y1 - 3 <= cy <= y2 + 3):
            return bbox_to_center(x1, y1, x2, y2)
        return cx, cy
    except Exception:
        return bbox_to_center(x1, y1, x2, y2)


def measurement_noise_for(confidence: float, width: float, height: float) -> float:
    """Map detection quality -> measurement variance px^2 for KF R.

    High-conf compact boxes -> ~2-4; weak/diffuse -> up to ~50.
    Keeps KF from over-trusting dim/blobby observations.
    """
    try:
        c = float(np.clip(confidence, 0.05, 1.0))
        size = max(2.0, float(width + height) / 2.0)
        # base from confidence: conf=1 -> 2.0, conf=0.25 -> ~12, conf=0.05 -> ~40
        base = 2.0 / (c ** 1.5)
        # size penalty: nominal 5-20px; huge boxes are less precise
        size_factor = float(np.clip(size / 12.0, 0.7, 2.5))
        return float(np.clip(base * size_factor, 1.0, 60.0))
    except Exception:
        return 9.0


def calibrate_classical_conf(mean_intensity: float, area: float, circularity: float) -> float:
    """Calibrated confidence for classical spots (was mean(ROI)/255).

    Combines brightness + compactness + plausible size so sky noise scores low.
    """
    try:
        b = float(np.clip(mean_intensity / 255.0, 0.0, 1.0))
        # Size term: peak at ~25-400 px^2, penalize tiny specks and huge blobs
        if area < 6:
            s = 0.2
        elif area <= 400:
            s = 0.7 + 0.3 * (1.0 - abs(area - 100.0) / 400.0)
        else:
            s = float(np.clip(400.0 / area, 0.1, 0.7))
        circ = float(np.clip(circularity, 0.0, 1.0))
        shape = 0.5 + 0.5 * circ
        conf = 0.55 * b + 0.25 * s + 0.20 * shape
        return float(np.clip(conf, 0.0, 1.0))
    except Exception:
        return 0.5


def bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    try:
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        union = aa + bb - inter
        return float(inter / union) if union > 1e-9 else 0.0
    except Exception:
        return 0.0


def fuse_detections_nms(dets: list[Detection], iou_thresh: float = 0.45) -> list[Detection]:
    """Cross-source NMS fusion: YOLO + classical boxes merged, best kept.

    Keeps highest (confidence / sqrt(pos_var)) box per overlapping cluster.
    Pure-python, no scipy. Never raises.
    """
    try:
        if len(dets) <= 1:
            return list(dets)
        def _score(d: Detection) -> float:
            try:
                return float(d.confidence) / float(np.sqrt(max(1.0, d.pos_var)))
            except Exception:
                return float(d.confidence)
        ordered = sorted(dets, key=_score, reverse=True)
        kept: list[Detection] = []
        for d in ordered:
            dup = False
            for k in kept:
                # Near-duplicate if IoU high OR centers within few px (small beacons)
                try:
                    dist = float(np.hypot(d.center[0] - k.center[0], d.center[1] - k.center[1]))
                except Exception:
                    dist = 1e9
                if bbox_iou(d.bbox, k.bbox) >= iou_thresh or dist < 6.0:
                    dup = True
                    break
            if not dup:
                if d.source in ("yolo", "classical") and len(kept) < 20:
                    d.source = "fused" if any(
                        bbox_iou(d.bbox, o.bbox) >= 0.1 for o in dets if o is not d
                    ) else d.source
                kept.append(d)
        return kept
    except Exception:
        return list(dets)


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
                    gray_ref = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
                    for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
                        if int(k) != 0:
                            continue
                        # Clamp to frame for safety
                        x1c, y1c = max(0.0, float(x1)), max(0.0, float(y1))
                        x2c, y2c = min(float(w), float(x2)), min(float(h), float(y2))
                        if x2c <= x1c or y2c <= y1c:
                            continue
                        # Sub-pixel refinement: intensity centroid inside bbox
                        cx, cy = intensity_refined_centroid(gray_ref, x1c, y1c, x2c, y2c)
                        bw, bh = float(x2c - x1c), float(y2c - y1c)
                        dets.append(
                            Detection(
                                bbox=(float(x1c), float(y1c), float(x2c), float(y2c)),
                                center=(float(cx), float(cy)),
                                width=bw,
                                height=bh,
                                confidence=float(np.clip(c, 0.0, 1.0)),
                                class_id=0,
                                pos_var=measurement_noise_for(float(c), bw, bh),
                                source="yolo",
                                area=bw * bh,
                                circularity=1.0,
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
            # Shape filter: reject streaks/noise (circularity + aspect)
            try:
                peri = cv2.arcLength(cnt, True)
                circ = (4.0 * np.pi * area / (peri * peri)) if peri > 1e-6 else 0.0
            except Exception:
                circ = 1.0
            circ = float(np.clip(circ, 0.0, 1.0))
            aspect = max(bw, bh) / max(1.0, min(bw, bh))
            if circ < 0.15 and aspect > 5.0:
                continue  # thin streak, not a beacon blob
            x1, y1, x2, y2 = float(x), float(y), float(x + bw), float(y + bh)
            cx, cy = intensity_refined_centroid(gray, x1, y1, x2, y2)
            roi = gray[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
            mean_i = float(np.mean(roi)) if roi.size else 0.0
            conf = calibrate_classical_conf(mean_i, float(area), circ)
            dets.append(
                Detection(
                    bbox=(x1, y1, x2, y2),
                    center=(cx, cy),
                    width=float(bw),
                    height=float(bh),
                    confidence=float(np.clip(conf, 0.0, 1.0)),
                    class_id=0,
                    pos_var=measurement_noise_for(conf, float(bw), float(bh)),
                    source="classical",
                    area=float(area),
                    circularity=circ,
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
    """Fused detector: YOLO + classical merged via NMS.

    Previously YOLO-only-if-any (classical ignored when YOLO fired). Now both
    run and are fused so dim/small beacons missed by one path are still found,
    with duplicates merged. Falls back gracefully if either path fails.
    Guarantees loop never crashes on missing weights."""

    def __init__(self, config: DetectorConfig | None = None, model_path: str | None = None):
        self.config = (config or DetectorConfig()).validate()
        self.yolo = YOLO26Detector(self.config, model_path=model_path)
        self.classical = BrightSpotDetector(self.config)
        self.last_used: str = "none"
        self.last_latency_ms: float = 0.0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        yolo_dets: list[Detection] = []
        try:
            yolo_dets = self.yolo.detect(frame)
        except Exception:
            yolo_dets = []
        classical_dets: list[Detection] = []
        if self.config.use_classical_fallback:
            try:
                classical_dets = self.classical.detect(frame)
            except Exception:
                classical_dets = []
        if yolo_dets and classical_dets:
            fused = fuse_detections_nms(
                list(yolo_dets) + list(classical_dets),
                iou_thresh=float(self.config.iou_threshold) if self.config.iou_threshold < 0.9 else 0.45,
            )
            self.last_used = "fused"
            self.last_latency_ms = float(self.yolo.last_latency_ms + self.classical.last_latency_ms)
        elif yolo_dets:
            fused = yolo_dets
            self.last_used = "yolo"
            self.last_latency_ms = self.yolo.last_latency_ms
        elif classical_dets:
            fused = classical_dets
            self.last_used = "classical"
            self.last_latency_ms = self.classical.last_latency_ms
        else:
            self.last_used = "none"
            self.last_latency_ms = self.yolo.last_latency_ms
            return []
        fused.sort(key=lambda d: (d.confidence / max(1.0, d.pos_var ** 0.5)), reverse=True)
        fused = fused[: int(self.config.max_detections)]
        return fused
