# evaluation/metrics.py - MetricsLogger for structured performance logging (Requirements.pdf §11-12)
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .ground_truth import compute_error_px


# Canonical CSV column order — fixed for report compatibility
FRAME_COLUMNS = [
    "frame_index",
    "timestamp_s",
    "state",
    "ground_truth_x",
    "ground_truth_y",
    "estimate_x",
    "estimate_y",
    "error_px",
    "detection_confidence",
    "processing_ms",
    "pan",
    "tilt",
]


@dataclass
class FrameRecord:
    frame_index: int
    timestamp_s: float
    state: str | None
    ground_truth_x: float | None
    ground_truth_y: float | None
    estimate_x: float | None
    estimate_y: float | None
    error_px: float | None
    detection_confidence: float | None
    processing_ms: float | None
    pan: float | None
    tilt: float | None

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsLogger:
    """Per-frame structured logger. Keeps GT + estimate isolated but scores error_t = hypot(est-gt).

    Example:
        ml = MetricsLogger()
        ml.add(frame_index=0, timestamp_s=0.0, state="SEARCH",
               ground_truth_x=320, ground_truth_y=240,
               estimate_x=322, estimate_y=238, detection_confidence=0.9,
               processing_ms=12.3, pan=0.0, tilt=0.0)
        ml.save(Path("outputs/runs/xxx/frames.csv"))
        print(ml.summary())
    """

    def __init__(self) -> None:
        self._frames: list[FrameRecord] = []
        self._wall_start = time.time()

    # -- core add ---------------------------------------------------------------
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
            **kwargs: Any) -> FrameRecord:
        """Add one frame. If error_px is None it is computed as hypot(est-gt). Extra kwargs are ignored (forward compat)."""
        # Normalize None-ish
        def _f(v: Any) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            except (TypeError, ValueError):
                return None

        gtx, gty = _f(ground_truth_x), _f(ground_truth_y)
        ex, ey = _f(estimate_x), _f(estimate_y)
        err = _f(error_px)
        if err is None:
            err = compute_error_px(ex, ey, gtx, gty)
        rec = FrameRecord(
            frame_index=int(frame_index),
            timestamp_s=float(timestamp_s),
            state=str(state) if state is not None else None,
            ground_truth_x=gtx,
            ground_truth_y=gty,
            estimate_x=ex,
            estimate_y=ey,
            error_px=err,
            detection_confidence=_f(detection_confidence),
            processing_ms=_f(processing_ms),
            pan=_f(pan),
            tilt=_f(tilt),
        )
        self._frames.append(rec)
        return rec

    # Convenience: add from typical sim/snapshot dicts without leaking GT into control path
    def add_from_snapshot(self,
                          frame_index: int,
                          timestamp_s: float,
                          state: str | None,
                          gt_xy: tuple[float | None, float | None] | None,
                          est_xy: tuple[float | None, float | None] | None,
                          detection_confidence: float | None = None,
                          processing_ms: float | None = None,
                          pan: float | None = None,
                          tilt: float | None = None) -> FrameRecord:
        gtx, gty = (None, None) if gt_xy is None else gt_xy
        ex, ey = (None, None) if est_xy is None else est_xy
        return self.add(frame_index=frame_index, timestamp_s=timestamp_s, state=state,
                        ground_truth_x=gtx, ground_truth_y=gty,
                        estimate_x=ex, estimate_y=ey,
                        detection_confidence=detection_confidence,
                        processing_ms=processing_ms, pan=pan, tilt=tilt)

    @property
    def frames(self) -> list[FrameRecord]:
        return list(self._frames)

    def __len__(self) -> int:
        return len(self._frames)

    def clear(self) -> None:
        self._frames.clear()

    def to_list(self) -> list[dict]:
        return [r.to_dict() for r in self._frames]

    # -- persistence ------------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        """Save frames.csv with canonical columns. Creates parent dirs. Returns Path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # If path is a directory, append frames.csv
        if p.is_dir() or str(p).endswith(("/", "\\")):
            p = p / "frames.csv"
        if p.suffix == "":
            p = p.with_suffix(".csv")
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FRAME_COLUMNS)
            w.writeheader()
            for r in self._frames:
                d = r.to_dict()
                # Ensure only canonical columns, coerce None -> ""
                row = {k: ("" if d.get(k) is None else d.get(k)) for k in FRAME_COLUMNS}
                w.writerow(row)
        return p

    def save_json(self, path: str | Path) -> Path:
        """Alternative JSON dump of frames (not canonical but useful for debugging)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self.to_list(), f, indent=2)
        return p

    @classmethod
    def load(cls, path: str | Path) -> "MetricsLogger":
        """Load frames.csv back into a logger (for replay/report)."""
        p = Path(path)
        ml = cls()
        if not p.exists():
            return ml
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                def _parse(k: str) -> float | None | str | None:
                    v = row.get(k, "")
                    if v == "" or v is None:
                        return None
                    if k in ("state",):
                        return str(v)
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return v
                # error_px already in CSV, but add() will recompute if None — pass it explicitly
                ml.add(
                    frame_index=int(float(row.get("frame_index", i))),
                    timestamp_s=float(row.get("timestamp_s", 0.0) or 0.0),
                    state=row.get("state") or None,
                    ground_truth_x=_parse("ground_truth_x"),
                    ground_truth_y=_parse("ground_truth_y"),
                    estimate_x=_parse("estimate_x"),
                    estimate_y=_parse("estimate_y"),
                    error_px=_parse("error_px"),
                    detection_confidence=_parse("detection_confidence"),
                    processing_ms=_parse("processing_ms"),
                    pan=_parse("pan"),
                    tilt=_parse("tilt"),
                )
        return ml

    # -- summary ----------------------------------------------------------------
    def summary(self) -> dict:
        """Compute summary dict with RMSE, mean/max/95pct, lost%, lock_retention, acq_time, reacq stats, FPS."""
        n = len(self._frames)
        if n == 0:
            return {
                "total_frames": 0,
                "duration_s": 0.0,
                "fps": 0.0,
                "processing_fps": 0.0,
                "mean_processing_ms": None,
                "max_processing_ms": None,
                "p95_processing_ms": None,
                "mean_error_px": None,
                "rmse_px": None,
                "max_error_px": None,
                "p50_error_px": None,
                "p95_error_px": None,
                "lost_pct": 100.0,
                "lock_retention_pct": 0.0,
                "locked_frames": 0,
                "acquisition_time_s": None,
                "reacquisition_count": 0,
                "reacq_times_s": [],
                "reacq_mean_s": None,
                "reacq_max_s": None,
                "reacq_median_s": None,
            }

        timestamps = [r.timestamp_s for r in self._frames]
        duration = float(timestamps[-1] - timestamps[0]) if n > 1 else float(timestamps[0] or 0.0)
        # If duration is too small (e.g., all timestamps 0), fallback to wall or frame-count * 1/30
        if duration < 1e-6:
            # estimate from frame count at 30Hz default
            duration = float(n) / 30.0
        fps = float(n / duration) if duration > 1e-9 else 0.0

        # Processing time stats
        proc = [float(r.processing_ms) for r in self._frames if r.processing_ms is not None]
        if proc:
            mean_proc = float(sum(proc) / len(proc))
            max_proc = float(max(proc))
            proc_sorted = sorted(proc)
            p95_proc = float(proc_sorted[int(len(proc_sorted) * 0.95)] if len(proc_sorted) > 1 else proc_sorted[-1])
            processing_fps = 1000.0 / mean_proc if mean_proc > 1e-9 else 0.0
        else:
            mean_proc = max_proc = p95_proc = None
            processing_fps = 0.0

        # Locked vs lost: TRACK + COAST count as locked for retention (COAST is still coasting on prediction, not lost)
        # Spec loss <5% means not in SEARCH/LOST/REACQUIRE. This matches V2 FSM where COAST is degraded tracking.
        def _is_locked(state: str | None) -> bool:
            if state is None:
                return False
            s = str(state).upper()
            return s in ("TRACK", "LOCKED", "TRACKING", "COAST", "COASTING")

        # Error stats — only over locked frames (spec Tracking Error while tracking, not SEARCH)
        # If no locked frames, fallback to any frame with valid error (to still report)
        errors_locked = [float(r.error_px) for r in self._frames if r.error_px is not None and not math.isnan(float(r.error_px)) and _is_locked(r.state)]
        errors_any = [float(r.error_px) for r in self._frames if r.error_px is not None and not math.isnan(float(r.error_px))]
        errors = errors_locked if errors_locked else errors_any
        if errors:
            mean_err = float(sum(errors) / len(errors))
            rmse = float(math.sqrt(sum(x * x for x in errors) / len(errors)))
            max_err = float(max(errors))
            es = sorted(errors)
            p50 = float(es[len(es) // 2])
            p95 = float(es[int(len(es) * 0.95)] if len(es) > 1 else es[-1])
        else:
            mean_err = rmse = max_err = p50 = p95 = None

        locked_frames = sum(1 for r in self._frames if _is_locked(r.state))
        lock_retention = float(locked_frames / n * 100.0) if n else 0.0
        lost_pct = float(100.0 - lock_retention)

        # Acquisition time: timestamp of first locked frame - timestamp of first frame
        acq_time: float | None = None
        for r in self._frames:
            if _is_locked(r.state):
                acq_time = float(r.timestamp_s - timestamps[0])
                break

        # Reacquisition stats: detect REACQUIRE periods and measure time to next TRACK
        reacq_times: list[float] = []
        in_reacq_since: float | None = None
        for r in self._frames:
            s = str(r.state or "").upper()
            if s == "REACQUIRE" and in_reacq_since is None:
                in_reacq_since = float(r.timestamp_s)
            elif _is_locked(s) and in_reacq_since is not None:
                reacq_times.append(float(r.timestamp_s - in_reacq_since))
                in_reacq_since = None
            elif s not in ("REACQUIRE",) and in_reacq_since is not None and s in ("SEARCH", "LOST", "COAST"):
                # If REACQUIRE exited without tracking, discard that attempt (or keep? spec wants successful reacq)
                # We discard incomplete REACQUIRE that went to SEARCH without TRACK
                pass
            # If state leaves REACQUIRE to SEARCH without TRACK, reset
            if s == "SEARCH" and in_reacq_since is not None:
                in_reacq_since = None

        reacq_mean = float(sum(reacq_times) / len(reacq_times)) if reacq_times else None
        reacq_max = float(max(reacq_times)) if reacq_times else None
        if reacq_times:
            rs = sorted(reacq_times)
            reacq_median = float(rs[len(rs) // 2])
        else:
            reacq_median = None

        return {
            "total_frames": int(n),
            "duration_s": float(duration),
            "fps": float(fps),
            "processing_fps": float(processing_fps),
            "mean_processing_ms": None if mean_proc is None else float(mean_proc),
            "max_processing_ms": None if max_proc is None else float(max_proc),
            "p95_processing_ms": None if p95_proc is None else float(p95_proc),
            "mean_error_px": None if mean_err is None else float(mean_err),
            "rmse_px": None if rmse is None else float(rmse),
            "max_error_px": None if max_err is None else float(max_err),
            "p50_error_px": None if p50 is None else float(p50),
            "p95_error_px": None if p95 is None else float(p95),
            "lost_pct": float(lost_pct),
            "lock_retention_pct": float(lock_retention),
            "locked_frames": int(locked_frames),
            "acquisition_time_s": None if acq_time is None else float(acq_time),
            "reacquisition_count": int(len(reacq_times)),
            "reacq_times_s": [float(x) for x in reacq_times],
            "reacq_mean_s": None if reacq_mean is None else float(reacq_mean),
            "reacq_max_s": None if reacq_max is None else float(reacq_max),
            "reacq_median_s": None if reacq_median is None else float(reacq_median),
        }
