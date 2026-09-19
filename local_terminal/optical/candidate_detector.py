# local_terminal/candidate_detector.py - Module 3: Candidate Detector (§7) + §8 spectral.
from __future__ import annotations

from typing import Any

from local_terminal.optical.detection import detect_beacon_candidates, estimate_wavelength_nm
from local_terminal.core.models import DetectionCandidate, ProcessedFrame, SpectralObservation


class CandidateDetector:
    """ProcessedFrame -> DetectionCandidate[]. Image-only; no world truth."""

    def __init__(self, config: Any | None = None):
        self.config = config
        self._next_measurement = 1

    def reset_counter(self, start: int = 1) -> None:
        """Restart measurement IDs (called when the track pool drains)."""
        self._next_measurement = int(max(1, start))

    def detect(self, processed: ProcessedFrame | None, timestamp: float = 0.0,
               raw_frame: Any = None) -> list[DetectionCandidate]:
        if processed is None or processed.raw_image is None:
            return []
        try:
            intensity_floor = 30.0
            min_area = 2
            try:
                det_cfg = getattr(self.config, "detection", self.config)
                intensity_floor = max(30.0, float(getattr(det_cfg, "intensity_threshold", 30.0)))
                min_area = int(getattr(det_cfg, "min_detection_area", 2) or 2)
            except Exception:
                pass
            raw_list = detect_beacon_candidates(processed.raw_image, minimum_peak=intensity_floor,
                                                min_area=min_area)
        except Exception:
            return []
        out: list[DetectionCandidate] = []
        for raw in raw_list:
            try:
                bgr = tuple(float(v) for v in raw.get("bgr", (0.0, 0.0, 0.0)))
                wl, conf = estimate_wavelength_nm(bgr)
                mid = f"M-{self._next_measurement}"
                self._next_measurement += 1
                out.append(DetectionCandidate(
                    candidate_measurement_id=mid,
                    centroid_x=float(raw.get("x", 0.0)),
                    centroid_y=float(raw.get("y", 0.0)),
                    bounding_box=(float(raw.get("x", 0.0)), float(raw.get("y", 0.0)),
                                  float(raw.get("diameter_px", 1.0)), float(raw.get("diameter_px", 1.0))),
                    area=float(raw.get("diameter_px", 1.0)) ** 2,
                    peak_intensity=float(raw.get("peak_dn", 0.0)),
                    integrated_intensity=float(raw.get("peak_dn", 0.0)) * float(raw.get("diameter_px", 1.0)) ** 2,
                    background_intensity=float(processed.background_estimate),
                    local_snr=float(raw.get("snr_db", 0.0)),
                    apparent_diameter=float(raw.get("diameter_px", 1.0)),
                    shape_metrics={"diameter_px": float(raw.get("diameter_px", 1.0))},
                    spectral_observation=SpectralObservation(
                        sensor_response=bgr, estimated_spectral_class=float(wl),
                        estimated_center=float(wl), confidence=float(conf)),
                    timestamp=float(timestamp),
                ))
            except Exception:
                continue
        return out
