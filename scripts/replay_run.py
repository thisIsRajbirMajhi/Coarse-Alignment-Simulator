#!/usr/bin/env python3
"""
scripts/replay_run.py — Replay / re-score a previous structured run.

Loads outputs/runs/<timestamp>/frames.csv (produced by MetricsLogger/RunLogger)
and/or a video+GT, recomputes summary + requirement check, and re-renders report.html.

Also supports: if given a run dir, just re-renders report.html from existing frames.csv
without re-simulating (deterministic replay of metrics).

Usage:
  python scripts/replay_run.py outputs/runs/20250924_143000
  python scripts/replay_run.py outputs/runs/20250924_143000/frames.csv --out outputs/runs/20250924_143000
  python scripts/replay_run.py --frames outputs/runs/xxx/frames.csv --events outputs/runs/xxx/events.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.evaluation.metrics import MetricsLogger
from src.evaluation.requirement_checker import check_requirements, render_html, render_json


def resolve_frames_path(inp: str | Path) -> Path:
    p = Path(inp)
    if p.is_dir():
        # Prefer frames.csv inside dir
        cand = p / "frames.csv"
        if cand.exists():
            return cand
        # Fallback: search recursively one level?
        return cand
    return p


def replay(frames_path: str | Path, out_dir: str | Path | None = None,
           events_path: str | Path | None = None) -> dict:
    frames_path = resolve_frames_path(frames_path)
    if not frames_path.exists():
        raise FileNotFoundError(f"frames.csv not found: {frames_path}")

    # Determine output dir
    if out_dir is None:
        # Default: same directory as frames.csv
        out_dir = frames_path.parent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load metrics
    ml = MetricsLogger.load(frames_path)
    summary = ml.summary()

    # If events available, enrich reacq stats from events (optional)
    if events_path is not None:
        ep = Path(events_path)
        if ep.exists():
            try:
                events = [json.loads(l) for l in ep.read_text(encoding="utf-8").splitlines() if l.strip()]
                # Optionally cross-validate summary reacq count with events
                summary["_events_file"] = str(ep)
                summary["_events_count"] = len(events)
            except Exception:
                pass
    else:
        # Auto-detect events.jsonl near frames.csv
        cand_ev = frames_path.parent / "events.jsonl"
        if cand_ev.exists():
            summary["_events_file"] = str(cand_ev)
            try:
                summary["_events_count"] = len([l for l in cand_ev.read_text(encoding="utf-8").splitlines() if l.strip()])
            except Exception:
                pass

    check = check_requirements(summary)

    # Write outputs: summary.json + report.html + report.json (do not overwrite frames.csv)
    summary_out = {"summary": summary, "check": check}
    (out_dir / "summary.json").write_text(json.dumps(summary_out, indent=2, default=str), encoding="utf-8")
    render_json(check, out_dir / "report.json")
    render_html(check, out_dir / "report.html")

    print(f"Loaded {len(ml)} frames from {frames_path}")
    print(f"Summary: total={summary.get('total_frames')} acq={summary.get('acquisition_time_s')} "
          f"p95={summary.get('p95_error_px')} loss={summary.get('lost_pct'):.1f}% "
          f"fps={summary.get('fps'):.1f} overall={check.get('overall')}")
    print(f"Outputs -> {out_dir} (summary.json, report.json, report.html)")

    # Also print per-requirement table to stdout (ascii-safe)
    for k, v in check.get("results", {}).items():
        status = "PASS" if v.get("pass") else "FAIL"
        val = v.get("value"); thr = v.get("threshold"); comp = v.get("comparator")
        desc = str(v.get('description','')).encode('ascii', 'replace').decode('ascii')
        print(f"  {k:22s} {str(val):>8} {comp} {thr}  [{status}]  - {desc}")

    return {"summary": summary, "check": check, "out_dir": out_dir, "frames": frames_path}

def main():
    ap = argparse.ArgumentParser(description="Replay / re-score a run from frames.csv")
    ap.add_argument("input", nargs="?", default=None, help="Run dir or frames.csv path (default: latest under outputs/runs)")
    ap.add_argument("--frames", type=str, default=None, help="Explicit frames.csv path")
    ap.add_argument("--events", type=str, default=None, help="Explicit events.jsonl path")
    ap.add_argument("--out", type=str, default=None, help="Output dir (default: same as input dir)")
    args = ap.parse_args()

    # Resolve input precedence: --frames > positional > latest
    frames_in = None
    if args.frames:
        frames_in = Path(args.frames)
    elif args.input:
        frames_in = Path(args.input)
    else:
        # Find latest run under outputs/runs
        base = REPO / "outputs" / "runs"
        if base.is_dir():
            cands = [p for p in base.iterdir() if p.is_dir() and (p / "frames.csv").exists()]
            if cands:
                cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                frames_in = cands[0] / "frames.csv"
                print(f"No input given — using latest: {frames_in}")
            else:
                ap.error("No runs found under outputs/runs; provide input path")
        else:
            ap.error("Provide input path (run dir or frames.csv)")

    if frames_in is None:
        ap.error("No frames input resolved")

    events_in = Path(args.events) if args.events else None
    # If input is a run dir and --events not given, auto-use events.jsonl inside dir
    out_dir = Path(args.out) if args.out else (frames_in.parent if frames_in.is_file() else frames_in)

    replay(frames_in, out_dir=out_dir, events_path=events_in)

if __name__ == "__main__":
    main()
