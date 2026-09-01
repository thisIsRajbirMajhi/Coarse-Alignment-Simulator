"""
Module: perf_log.error_stats
Purpose: Isolated error distribution — split from PerformanceLogger.summary 126 lines.
Public API: compute_error_stats
Notes: Extracted from perf_log/metrics.py:259. Handles avg/max/min/median/p95/rms/std + intuitive 15px=100%.
"""

import math


def compute_error_stats(tracking_errors: list[float]) -> dict:
    n = len(tracking_errors)
    if not n:
        return {"avg": 0.0, "max": 0.0, "min": 0.0, "median": 0.0, "p95": 0.0, "rms": 0.0, "std": 0.0}
    avg = sum(tracking_errors) / n
    mx = max(tracking_errors)
    mn = min(tracking_errors)
    rms = math.sqrt(sum(x * x for x in tracking_errors) / n)
    mean = avg
    var = sum((x - mean) ** 2 for x in tracking_errors) / n
    std = math.sqrt(var) if var > 0 else 0.0
    s = sorted(tracking_errors)
    median = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    p95_idx = int(math.ceil(0.95 * n)) - 1
    p95_idx = max(0, min(p95_idx, n - 1))
    p95 = s[p95_idx]
    return {"avg": avg, "max": mx, "min": mn, "median": median, "p95": p95, "rms": rms, "std": std}


def error_pct_from_px(px: float) -> float:
    return round(max(0.0, min(100.0, float(px) / 15.0 * 100.0)), 2) if px is not None else 0.0
