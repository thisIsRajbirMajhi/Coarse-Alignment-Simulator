# evaluation/requirement_checker.py - Pass/fail per Requirements.pdf §11-12 (5 targets)
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Thresholds per spec (Requirements.pdf Table §11-12)
# Acq <=2s, error <=10px, loss <5%, reacq <=1s, FPS >=20 (>=25 in older benchmark, use >=20 per task)
SPEC_THRESHOLDS: dict[str, dict[str, Any]] = {
    "acquisition_time": {"metric": "acquisition_time_s", "threshold": 2.0, "comparator": "<=", "unit": "s", "description": "Acquisition time ≤ 2 s"},
    "tracking_error": {"metric": "p95_error_px", "threshold": 10.0, "comparator": "<=", "unit": "px", "description": "Tracking error p95 ≤ 10 px (also mean ≤10px)"},
    "target_loss": {"metric": "lost_pct", "threshold": 5.0, "comparator": "<", "unit": "%", "description": "Target loss < 5%"},
    "reacquisition_time": {"metric": "reacq_max_s", "threshold": 1.0, "comparator": "<=", "unit": "s", "description": "Re-acquisition time ≤ 1 s (max)"},
    "processing_speed": {"metric": "fps", "threshold": 20.0, "comparator": ">=", "unit": "FPS", "description": "Processing speed ≥ 20 FPS"},
}


def _compare(value: float | None, threshold: float, comparator: str) -> bool | None:
    if value is None:
        return None  # unknown -> fail if required, but mark as None
    if comparator == "<=":
        return float(value) <= float(threshold)
    if comparator == "<":
        return float(value) < float(threshold)
    if comparator == ">=":
        return float(value) >= float(threshold)
    if comparator == ">":
        return float(value) > float(threshold)
    return False


def _get_metric(summary: dict, metric: str) -> float | None:
    v = summary.get(metric)
    if v is None:
        return None
    try:
        f = float(v)
        # NaN guard
        import math
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def check_requirements(summary: dict) -> dict:
    """Check 5 spec targets. Returns dict with per-requirement pass/fail + overall."""
    # Resolve alternate metrics for robustness
    # tracking_error: primary p95_error_px, fallback mean_error_px or rmse or max_error_px
    # reacquisition: primary reacq_max_s, fallback reacq_mean_s or reacq_median_s; if no reacq events, pass (no loss to reacquire)
    # fps: primary fps, fallback processing_fps
    # loss: lost_pct
    # acq: acquisition_time_s

    results: dict[str, dict[str, Any]] = {}

    # 1) Acquisition
    acq_val = _get_metric(summary, "acquisition_time_s")
    acq_cfg = SPEC_THRESHOLDS["acquisition_time"]
    acq_pass = _compare(acq_val, acq_cfg["threshold"], acq_cfg["comparator"])
    # If no acquisition (None) => FAIL (never locked)
    if acq_pass is None:
        acq_pass = False
    results["acquisition_time"] = {
        "id": "acquisition_time",
        "description": acq_cfg["description"],
        "metric": acq_cfg["metric"],
        "value": acq_val,
        "threshold": float(acq_cfg["threshold"]),
        "comparator": acq_cfg["comparator"],
        "unit": acq_cfg["unit"],
        "pass": bool(acq_pass),
    }

    # 2) Tracking error — check p95 and mean; both must meet 10px if available
    p95 = _get_metric(summary, "p95_error_px")
    mean_e = _get_metric(summary, "mean_error_px")
    rmse = _get_metric(summary, "rmse_px")
    max_e = _get_metric(summary, "max_error_px")
    # Primary is p95, but also mean
    err_values = []
    err_passes = []
    for name, val in [("p95_error_px", p95), ("mean_error_px", mean_e)]:
        if val is not None:
            err_values.append((name, val))
            err_passes.append(_compare(val, 10.0, "<="))
    if not err_values:
        # No error data -> use rmse fallback
        if rmse is not None:
            err_values.append(("rmse_px", rmse))
            err_passes.append(_compare(rmse, 10.0, "<="))
        elif max_e is not None:
            err_values.append(("max_error_px", max_e))
            err_passes.append(_compare(max_e, 10.0, "<="))
    # Overall tracking error passes only if all available checks pass and at least one present
    if not err_passes:
        track_pass = False
        track_val = None
        track_metric = "p95_error_px"
    else:
        track_pass = all(bool(p) for p in err_passes)
        # report the most relevant (p95 if present else mean)
        track_val = p95 if p95 is not None else mean_e if mean_e is not None else rmse
        track_metric = "p95_error_px" if p95 is not None else ("mean_error_px" if mean_e is not None else "rmse_px")

    results["tracking_error"] = {
        "id": "tracking_error",
        "description": SPEC_THRESHOLDS["tracking_error"]["description"],
        "metric": track_metric,
        "value": track_val,
        "threshold": 10.0,
        "comparator": "<=",
        "unit": "px",
        "pass": bool(track_pass),
        "details": {k: v for k, v in err_values},
        "all_metrics": {"p95_error_px": p95, "mean_error_px": mean_e, "rmse_px": rmse, "max_error_px": max_e},
    }

    # 3) Target loss <5%
    lost = _get_metric(summary, "lost_pct")
    if lost is None:
        # derive from lock_retention if present
        lr = _get_metric(summary, "lock_retention_pct")
        if lr is not None:
            lost = float(100.0 - lr)
    loss_cfg = SPEC_THRESHOLDS["target_loss"]
    loss_pass = _compare(lost, loss_cfg["threshold"], loss_cfg["comparator"])
    if loss_pass is None:
        loss_pass = False
    results["target_loss"] = {
        "id": "target_loss",
        "description": loss_cfg["description"],
        "metric": loss_cfg["metric"],
        "value": lost,
        "threshold": float(loss_cfg["threshold"]),
        "comparator": loss_cfg["comparator"],
        "unit": loss_cfg["unit"],
        "pass": bool(loss_pass),
    }

    # 4) Re-acquisition <=1s (max). If no reacq events, treat as PASS (no loss scenario requires reacq)
    reacq_max = _get_metric(summary, "reacq_max_s")
    reacq_mean = _get_metric(summary, "reacq_mean_s")
    reacq_count = summary.get("reacquisition_count", 0) or summary.get("reacq_count", 0)
    try:
        reacq_count = int(reacq_count)
    except Exception:
        reacq_count = 0
    # Also check reacq_times list
    reacq_times = summary.get("reacq_times_s") or summary.get("reacquisition_times") or []
    if reacq_count == 0 and not reacq_times:
        # No reacquisition needed — PASS per spec (reacq time N/A)
        reacq_pass = True
        reacq_val = None
        reacq_metric = "reacq_max_s"
    else:
        # Use max if available, else mean
        reacq_val = reacq_max if reacq_max is not None else reacq_mean
        reacq_metric = "reacq_max_s" if reacq_max is not None else "reacq_mean_s"
        reacq_cfg = SPEC_THRESHOLDS["reacquisition_time"]
        reacq_pass = _compare(reacq_val, reacq_cfg["threshold"], reacq_cfg["comparator"])
        if reacq_pass is None:
            reacq_pass = False

    results["reacquisition_time"] = {
        "id": "reacquisition_time",
        "description": SPEC_THRESHOLDS["reacquisition_time"]["description"],
        "metric": reacq_metric,
        "value": reacq_val,
        "threshold": float(SPEC_THRESHOLDS["reacquisition_time"]["threshold"]),
        "comparator": SPEC_THRESHOLDS["reacquisition_time"]["comparator"],
        "unit": "s",
        "pass": bool(reacq_pass),
        "count": int(reacq_count),
        "all_times": [float(x) for x in (reacq_times or [])],
    }

    # 5) FPS >=20
    fps_val = _get_metric(summary, "fps")
    if fps_val is None:
        fps_val = _get_metric(summary, "processing_fps")
        fps_metric = "processing_fps"
    else:
        fps_metric = "fps"
        # Also consider processing_fps as secondary? Primary is wall FPS derived from timestamps, which should be >=20
        # If fps is low due to wall but processing_fps is high, still use fps as spec says FPS >=20
        pass
    fps_cfg = SPEC_THRESHOLDS["processing_speed"]
    fps_pass = _compare(fps_val, fps_cfg["threshold"], fps_cfg["comparator"])
    if fps_pass is None:
        fps_pass = False
    results["processing_speed"] = {
        "id": "processing_speed",
        "description": fps_cfg["description"],
        "metric": fps_metric,
        "value": fps_val,
        "threshold": float(fps_cfg["threshold"]),
        "comparator": fps_cfg["comparator"],
        "unit": fps_cfg["unit"],
        "pass": bool(fps_pass),
        "details": {"fps": _get_metric(summary, "fps"), "processing_fps": _get_metric(summary, "processing_fps")},
    }

    overall = all(bool(v["pass"]) for v in results.values())
    return {
        "overall_pass": bool(overall),
        "overall": "PASS" if overall else "FAIL",
        "thresholds": SPEC_THRESHOLDS,
        "results": results,
        "summary": summary,
    }


def render_json(check_result: dict, path: str | Path) -> Path:
    """Write pass/fail table + summary to JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_dir():
        p = p / "report.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(check_result, f, indent=2, default=str)
    return p


def render_html(check_result: dict, path: str | Path) -> Path:
    """Render HTML report with colored pass/fail table."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_dir():
        p = p / "report.html"
    results = check_result.get("results", {})
    summary = check_result.get("summary", {})
    overall = check_result.get("overall", "FAIL")
    overall_pass = check_result.get("overall_pass", False)

    def _fmt(v: Any, digits: int = 3) -> str:
        if v is None:
            return "—"
        try:
            f = float(v)
            if f != f or f == float("inf") or f == float("-inf"):
                return "—"
            return f"{f:.{digits}f}"
        except (TypeError, ValueError):
            return str(v)

    rows_html = ""
    for key in ["acquisition_time", "tracking_error", "target_loss", "reacquisition_time", "processing_speed"]:
        r = results.get(key, {})
        val = r.get("value")
        thr = r.get("threshold")
        comp = r.get("comparator", "")
        passed = bool(r.get("pass", False))
        color = "#1b7f2b" if passed else "#c0392b"
        bg = "#e8f5e9" if passed else "#fdecea"
        badge = "PASS" if passed else "FAIL"
        desc = r.get("description", key)
        metric = r.get("metric", "")
        rows_html += f"""
        <tr style="background:{bg};">
            <td style="padding:8px 12px; border:1px solid #ddd;">{desc}</td>
            <td style="padding:8px 12px; border:1px solid #ddd; font-family:monospace;">{metric}</td>
            <td style="padding:8px 12px; border:1px solid #ddd; font-family:monospace;">{_fmt(val)}</td>
            <td style="padding:8px 12px; border:1px solid #ddd; font-family:monospace;">{comp} {_fmt(thr)}</td>
            <td style="padding:8px 12px; border:1px solid #ddd; color:{color}; font-weight:700;">{badge}</td>
        </tr>"""
        # Add details for tracking_error and reacq if present
        if key == "tracking_error" and r.get("all_metrics"):
            am = r["all_metrics"]
            rows_html += f"""<tr><td colspan="5" style="padding:4px 12px; border:1px solid #ddd; font-size:12px; color:#555;">
            details: p50={_fmt(am.get('p50_error_px'))} p95={_fmt(am.get('p95_error_px'))} mean={_fmt(am.get('mean_error_px'))} rmse={_fmt(am.get('rmse_px'))} max={_fmt(am.get('max_error_px'))}
            </td></tr>"""
        if key == "reacquisition_time":
            rows_html += f"""<tr><td colspan="5" style="padding:4px 12px; border:1px solid #ddd; font-size:12px; color:#555;">
            count={r.get('count', 0)} times={', '.join(_fmt(x,2) for x in (r.get('all_times') or [])[:8]) or '—'} 
            </td></tr>"""

    summary_rows = ""
    for k, v in summary.items():
        if k in ("reacq_times_s",):
            v_str = ", ".join(_fmt(x, 2) for x in (v or [])[:12]) or "—"
        elif isinstance(v, float):
            v_str = _fmt(v)
        elif v is None:
            v_str = "—"
        else:
            v_str = str(v)
        summary_rows += f'<tr><td style="padding:4px 8px; border:1px solid #eee; font-family:monospace;">{k}</td><td style="padding:4px 8px; border:1px solid #eee; font-family:monospace;">{v_str}</td></tr>\n'

    overall_color = "#1b7f2b" if overall_pass else "#c0392b"
    overall_bg = "#e8f5e9" if overall_pass else "#fdecea"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FSOC Coarse Alignment — Performance Report</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif; margin:24px; color:#222; background:#fafafa;}}
 .card{{background:#fff; border:1px solid #ddd; border-radius:8px; padding:16px 20px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,0.06);}}
 h1{{margin:0 0 8px 0; font-size:20px;}}
 h2{{margin:0 0 12px 0; font-size:16px; border-bottom:1px solid #eee; padding-bottom:6px;}}
 table{{border-collapse:collapse; width:100%; font-size:13px;}}
 th{{background:#f5f5f5; padding:8px 12px; border:1px solid #ddd; text-align:left;}}
 .badge{{display:inline-block; padding:4px 10px; border-radius:12px; color:#fff; font-weight:700; font-size:13px;}}
 .meta{{font-size:12px; color:#666;}}
</style>
</head>
<body>
<div class="card" style="border-left:6px solid {overall_color}; background:{overall_bg};">
<h1>Performance Report — <span class="badge" style="background:{overall_color};">{overall}</span></h1>
<div class="meta">Thresholds: Acq ≤2s, Error p95/mean ≤10px, Loss &lt;5%, Reacq ≤1s, FPS ≥20 · Generated by evaluation/requirement_checker.py</div>
</div>

<div class="card">
<h2>Requirement Check (Requirements.pdf §11–12)</h2>
<table>
<tr><th>Requirement</th><th>Metric</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
{rows_html}
</table>
</div>

<div class="card">
<h2>Summary (MetricsLogger.summary)</h2>
<table>
<tr><th>Key</th><th>Value</th></tr>
{summary_rows}
</table>
</div>

<div class="card meta">
<strong>Notes:</strong> GT never fed to controller — scoring only (evaluation/ground_truth.py). 
Error = hypot(est - gt) in FOV px. Loss = 100 - lock_retention. Reacquisition measured as REACQUIRE→TRACK duration. FPS = frames / duration_s.
</div>
</body>
</html>"""
    p.write_text(html, encoding="utf-8")
    return p


# Convenience single-call helper
def evaluate_and_render(summary: dict, out_dir: str | Path) -> dict:
    """Check + write JSON + HTML into out_dir. Returns check_result."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cr = check_requirements(summary)
    render_json(cr, out / "report.json")
    # also write JSON alias summary.json for RunLogger compatibility
    try:
        (out / "check_result.json").write_text(json.dumps(cr, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
    render_html(cr, out / "report.html")
    return cr
