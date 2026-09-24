# logging/frame_logger.py - Incremental per-frame writer backed by MetricsLogger
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.evaluation.metrics import MetricsLogger, FRAME_COLUMNS
from src.evaluation.ground_truth import compute_error_px
from .schemas import FRAME_CSV_COLUMNS


class FrameLogger:
    """Incremental CSV logger that delegates scoring to MetricsLogger.

    Wraps MetricsLogger for live runs where frames are flushed incrementally
    (useful for long benchmarks so partial results survive crashes).

    Args:
        csv_path: Destination frames.csv path. File is created on first add()
                  with header; subsequent add() appends rows.
        metrics: Optional pre-existing MetricsLogger to keep in sync (if None,
                 a new one is created).
    """

    def __init__(self, csv_path: str | Path | None = None, metrics: MetricsLogger | None = None) -> None:
        self.metrics = metrics if metrics is not None else MetricsLogger()
        self.csv_path: Path | None = Path(csv_path) if csv_path is not None else None
        self._header_written = False
        if self.csv_path is not None and self.csv_path.exists():
            # If file exists and has header, we will append; otherwise overwrite header
            try:
                if self.csv_path.stat().st_size > 0:
                    self._header_written = True
                else:
                    self._header_written = False
            except Exception:
                self._header_written = False

    def _ensure_header(self) -> None:
        if self.csv_path is None or self._header_written:
            return
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        # Write header if file is new/empty
        needs_header = True
        if self.csv_path.exists():
            try:
                needs_header = self.csv_path.stat().st_size == 0
            except Exception:
                needs_header = True
        if needs_header:
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FRAME_CSV_COLUMNS)
                w.writeheader()
        self._header_written = True

    def add(self,
            frame_index: int,
            timestamp_s: float,
            state: str | None = None,
            ground_truth_x: float | None = None,
            ground_truth_y: float | None = None,
            estimate_x: float | None = None,
            estimate_y: float | None = None,
            error_px: float | None = None,
            detection_confidence: float | None = None,
            processing_ms: float | None = None,
            pan: float | None = None,
            tilt: float | None = None,
            **kwargs: Any) -> dict:
        """Add frame to in-memory MetricsLogger and append to CSV if csv_path is set."""
        if error_px is None:
            error_px = compute_error_px(estimate_x, estimate_y, ground_truth_x, ground_truth_y)
        rec = self.metrics.add(frame_index=frame_index, timestamp_s=timestamp_s, state=state,
                               ground_truth_x=ground_truth_x, ground_truth_y=ground_truth_y,
                               estimate_x=estimate_x, estimate_y=estimate_y, error_px=error_px,
                               detection_confidence=detection_confidence, processing_ms=processing_ms,
                               pan=pan, tilt=tilt, **kwargs)
        if self.csv_path is not None:
            self._ensure_header()
            d = rec.to_dict()
            row = {k: ("" if d.get(k) is None else d.get(k)) for k in FRAME_CSV_COLUMNS}
            try:
                with self.csv_path.open("a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=FRAME_CSV_COLUMNS)
                    w.writerow(row)
            except Exception:
                pass
        return rec.to_dict()

    def flush(self) -> None:
        """No-op for CSV append mode; kept for API symmetry."""
        pass

    def summary(self) -> dict:
        return self.metrics.summary()

    def save(self, path: str | Path | None = None) -> Path:
        """Save full in-memory log to a (potentially different) path."""
        p = Path(path) if path is not None else (self.csv_path or Path("frames.csv"))
        return self.metrics.save(p)
