# logging/schemas.py - Schemas for structured run outputs (outputs/runs/<ts>/...)
from __future__ import annotations

# Canonical per-frame CSV columns (must match evaluation.metrics.FRAME_COLUMNS)
FRAME_CSV_COLUMNS: list[str] = [
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

# events.jsonl — one JSON object per line
EVENT_FIELDS: list[str] = [
    "timestamp_s",
    "from_state",
    "to_state",
    "reason",
    "frame_index",
]

# run_metadata.json top-level keys
RUN_METADATA_FIELDS: list[str] = [
    "run_id",
    "timestamp",
    "seed",
    "model_hash",
    "config",
    "environment",
    "duration_s",
    "total_frames",
    "repo",
]

# summary.json keys (from MetricsLogger.summary + requirement check)
SUMMARY_FIELDS: list[str] = [
    "total_frames",
    "duration_s",
    "fps",
    "processing_fps",
    "mean_processing_ms",
    "max_processing_ms",
    "p95_processing_ms",
    "mean_error_px",
    "rmse_px",
    "max_error_px",
    "p50_error_px",
    "p95_error_px",
    "lost_pct",
    "lock_retention_pct",
    "locked_frames",
    "acquisition_time_s",
    "reacquisition_count",
    "reacq_times_s",
    "reacq_mean_s",
    "reacq_max_s",
    "reacq_median_s",
]

# Minimal JSON-schema-like descriptions for validation / docs (no external deps)
SCHEMAS: dict[str, dict] = {
    "frames.csv": {
        "type": "csv",
        "columns": FRAME_CSV_COLUMNS,
        "description": "Per-frame metrics: state, GT, estimate, error=hypot(est-gt), confidence, timing, pan/tilt.",
    },
    "events.jsonl": {
        "type": "jsonl",
        "fields": EVENT_FIELDS,
        "description": "State transition events (SEARCH→TRACK etc.) one JSON per line.",
    },
    "run_metadata.json": {
        "type": "json",
        "fields": RUN_METADATA_FIELDS,
        "description": "Run config dump + seed + model hash + timestamp.",
    },
    "summary.json": {
        "type": "json",
        "fields": SUMMARY_FIELDS,
        "description": "Aggregated metrics from MetricsLogger.summary() plus pass/fail table.",
    },
    "report.html": {
        "type": "html",
        "description": "Human-readable pass/fail report rendered from requirement_checker.",
    },
}
