# logging/run_logger.py - RunLogger for outputs/runs/<timestamp>/ structured outputs
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.evaluation.metrics import MetricsLogger
from src.evaluation.requirement_checker import check_requirements, render_html
from .frame_logger import FrameLogger
from .schemas import FRAME_CSV_COLUMNS, EVENT_FIELDS


def _hash_configs(configs: dict[str, Any]) -> str:
    """Stable short hash of config dumps + optional model files (8 hex chars)."""
    try:
        blob = json.dumps(configs, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:8]
    except Exception:
        return "unknown"


def _safe_to_dict(obj: Any) -> Any:
    """Convert config objects to plain dicts for JSON (handles dataclasses with to_dict/validate)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _safe_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_to_dict(x) for x in obj]
    # Dataclass with to_dict
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        try:
            return _safe_to_dict(obj.to_dict())
        except Exception:
            pass
    # Fallback: __dict__
    if hasattr(obj, "__dict__"):
        try:
            return {k: _safe_to_dict(v) for k, v in vars(obj).items() if not k.startswith("_")}
        except Exception:
            pass
    # Primitive
    if isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        return str(obj)
    except Exception:
        return None


class RunLogger:
    """Orchestrates structured run outputs:
        outputs/runs/<timestamp>/ {
            run_metadata.json  (config dump + seed + model hash + timestamp)
            events.jsonl       (state transitions)
            frames.csv         (via MetricsLogger / FrameLogger)
            summary.json       (MetricsLogger.summary + requirement check)
            report.html        (human-readable pass/fail)
        }

    Usage:
        rl = RunLogger(base_dir="outputs/runs", configs={"env": env_cfg, ...}, seed=42)
        for step in range(N):
            # ... step sim, get state, GT, estimate, processing_ms, pan/tilt
            rl.log_frame(frame_index=i, timestamp_s=t, state=s, ...)
            if state_changed:
                rl.log_event(timestamp_s=t, from_state=prev, to_state=s, reason="...")
        out_dir = rl.finalize()  # writes summary.json + report.html, returns dir Path
    """

    def __init__(self,
                 base_dir: str | Path = "outputs/runs",
                 run_id: str | None = None,
                 configs: dict[str, Any] | None = None,
                 seed: int | None = None,
                 extra_meta: dict[str, Any] | None = None) -> None:
        ts = datetime.now(timezone.utc).astimezone()
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        # run_id uniqueness: timestamp + short random if collision
        if run_id is None:
            run_id = ts_str
            # ensure uniqueness if directory exists
            base = Path(base_dir)
            cand = base / run_id
            if cand.exists():
                run_id = f"{ts_str}_{int(time.time()*1000)%10000:04d}"
        self.run_id = str(run_id)
        self.base_dir = Path(base_dir)
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.seed = int(seed) if seed is not None else None
        self.configs = configs or {}
        self.extra_meta = extra_meta or {}
        self._timestamp_iso = ts.isoformat()
        self._wall_start = time.time()

        # model hash: hash of config dumps + optional extra_meta hash salt
        try:
            dump = {k: _safe_to_dict(v) for k, v in self.configs.items()}
            if self.extra_meta:
                dump["_extra"] = _safe_to_dict(self.extra_meta)
            self.model_hash = _hash_configs(dump)
        except Exception:
            self.model_hash = "unknown"

        # Metrics + frame logger
        self.metrics = MetricsLogger()
        self.frame_logger = FrameLogger(csv_path=self.run_dir / "frames.csv", metrics=self.metrics)

        # Events buffer
        self._events: list[dict] = []
        self._events_path = self.run_dir / "events.jsonl"
        # Truncate if exists
        try:
            if self._events_path.exists():
                self._events_path.write_text("", encoding="utf-8")
        except Exception:
            pass
        # Write metadata eagerly so run is discoverable even if finalize() not called
        self._write_metadata()

    def _write_metadata(self) -> Path:
        meta = {
            "run_id": self.run_id,
            "timestamp": self._timestamp_iso,
            "seed": self.seed,
            "model_hash": self.model_hash,
            "config": {k: _safe_to_dict(v) for k, v in self.configs.items()},
            "extra": _safe_to_dict(self.extra_meta),
            "environment": {
                "python": _safe_to_dict(sys_version()),
                "platform": _safe_to_dict(platform_info()),
            },
            "base_dir": str(self.base_dir),
            "run_dir": str(self.run_dir),
        }
        p = self.run_dir / "run_metadata.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, default=str, ensure_ascii=False)
        return p

    def log_frame(self,
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
        """Log one frame (appends to frames.csv + in-memory summary)."""
        return self.frame_logger.add(frame_index=frame_index, timestamp_s=timestamp_s, state=state,
                                     ground_truth_x=ground_truth_x, ground_truth_y=ground_truth_y,
                                     estimate_x=estimate_x, estimate_y=estimate_y, error_px=error_px,
                                     detection_confidence=detection_confidence, processing_ms=processing_ms,
                                     pan=pan, tilt=tilt, **kwargs)

    def log_event(self,
                  timestamp_s: float,
                  from_state: str,
                  to_state: str,
                  reason: str = "",
                  frame_index: int | None = None) -> None:
        """Append one state transition to events.jsonl and buffer."""
        ev = {
            "timestamp_s": float(timestamp_s),
            "from_state": str(from_state),
            "to_state": str(to_state),
            "reason": str(reason or ""),
            "frame_index": int(frame_index) if frame_index is not None else None,
        }
        self._events.append(ev)
        # Append to file incrementally
        try:
            self._events_path.parent.mkdir(parents=True, exist_ok=True)
            with self._events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        except Exception:
            pass

    def log_events_from_transitions(self, transitions: list[tuple]) -> None:
        """Helper to ingest supervisor.transitions = [(sim_time, src, dst, reason), ...]"""
        for t in transitions or []:
            try:
                if len(t) == 4:
                    ts, src, dst, reason = t
                    self.log_event(timestamp_s=float(ts), from_state=str(src), to_state=str(dst), reason=str(reason))
                elif len(t) == 3:
                    ts, src, dst = t
                    self.log_event(timestamp_s=float(ts), from_state=str(src), to_state=str(dst))
            except Exception:
                continue

    def finalize(self) -> Path:
        """Write summary.json + report.html (and ensure frames.csv + events.jsonl are flushed). Returns run_dir."""
        # Ensure frames.csv is fully written (FrameLogger already appends; also rewrite from metrics as fallback)
        try:
            if len(self.metrics) > 0:
                # Re-write canonical file from in-memory to ensure consistency (overwrite incremental)
                tmp = self.run_dir / "frames.csv"
                # If incremental and in-memory differ, overwrite with canonical from metrics (authoritative)
                self.metrics.save(tmp)
        except Exception:
            pass
        # Ensure events file exists even if no events
        try:
            if not self._events_path.exists():
                self._events_path.write_text("", encoding="utf-8")
        except Exception:
            pass

        summary = self.metrics.summary()
        # Enrich summary with run meta
        summary["_run_id"] = self.run_id
        summary["_seed"] = self.seed
        summary["_model_hash"] = self.model_hash
        summary["_timestamp"] = self._timestamp_iso
        summary["_total_events"] = len(self._events)

        # Requirement check
        check = check_requirements(summary)

        # Write summary.json (summary + check)
        out_summary = {
            "summary": summary,
            "check": check,
            "schemas": {"frames_csv": FRAME_CSV_COLUMNS, "events": EVENT_FIELDS},
        }
        p_summary = self.run_dir / "summary.json"
        with p_summary.open("w", encoding="utf-8") as f:
            json.dump(out_summary, f, indent=2, default=str, ensure_ascii=False)

        # Write report.html (human-readable)
        try:
            render_html(check, self.run_dir / "report.html")
        except Exception as e:
            # Fallback minimal HTML
            try:
                html_path = self.run_dir / "report.html"
                html_path.write_text(f"<html><body><h1>{check.get('overall','FAIL')}</h1><pre>{json.dumps(check, indent=2, default=str)}</pre></body></html>", encoding="utf-8")
            except Exception:
                pass

        # Also write report.json alias
        try:
            p_report = self.run_dir / "report.json"
            with p_report.open("w", encoding="utf-8") as f:
                json.dump(check, f, indent=2, default=str, ensure_ascii=False)
        except Exception:
            pass

        # Update metadata with final counts
        try:
            meta_path = self.run_dir / "run_metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                meta = {}
            meta["duration_s"] = float(summary.get("duration_s", 0.0))
            meta["total_frames"] = int(summary.get("total_frames", len(self.metrics)))
            meta["overall"] = check.get("overall", "FAIL")
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, default=str, ensure_ascii=False)
        except Exception:
            pass

        return self.run_dir

    @property
    def frames_path(self) -> Path:
        return self.run_dir / "frames.csv"

    @property
    def events_path(self) -> Path:
        return self._events_path


def sys_version() -> str:
    try:
        import sys as _sys
        return _sys.version
    except Exception:
        return "unknown"


def platform_info() -> str:
    try:
        import platform as _pl
        return f"{_pl.system()} {_pl.release()} {_pl.machine()} { _pl.python_version()}"
    except Exception:
        return "unknown"
