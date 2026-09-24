# evaluation/__init__.py - Structured performance evaluation package (Requirements.pdf §11-12)
from .metrics import MetricsLogger
from .requirement_checker import check_requirements, render_json, render_html, SPEC_THRESHOLDS
from .ground_truth import compute_error_px, GroundTruthFrame, GroundTruthLog

__all__ = [
    "MetricsLogger",
    "check_requirements",
    "render_json",
    "render_html",
    "SPEC_THRESHOLDS",
    "compute_error_px",
    "GroundTruthFrame",
    "GroundTruthLog",
]
