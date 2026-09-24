#!/usr/bin/env python3
"""
scripts/run_benchmark.py — Structured benchmark with automatic performance logging
(Plan §11-12). Produces outputs/runs/<timestamp>/{run_metadata.json, frames.csv, events.jsonl, summary.json, report.html}

Uses evaluation.MetricsLogger + logging.RunLogger + evaluation.requirement_checker.

Example:
  python scripts/run_benchmark.py --seeds 2 --steps 600
  python scripts/run_benchmark.py --video data/video.mp4 --steps 300
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.evaluation.ground_truth import compute_error_px
from src.logging.run_logger import RunLogger

def _extract_gt(sim, fov_center=None, fov_size=(640, 480)):
    """GT extraction isolated from control path — for logging only."""
    try:
        from src.evaluation.ground_truth import GroundTruthLog
        gx, gy, vis = GroundTruthLog.extract_from_simulation(sim, fov_center=fov_center, fov_size=fov_size)
        return gx, gy, vis
    except Exception:
        return None, None, False

def _extract_estimate(tracker_tel: dict, fov_size=(640, 480)):
    """Estimate from tracker telemetry in FOV px. Returns None when not locked (so error is not scored during SEARCH)."""
    if not tracker_tel:
        return None, None, None
    # Only trust estimate when locked/tracking; otherwise SEARCH has dummy 0,0
    locked = tracker_tel.get("locked")
    if locked is False:
        # still allow COAST? COAST error still counts but is less stable — include it
        # For spec, COAST is not locked but we may still want error; treat as valid if state!=SEARCH
        state = str(tracker_tel.get("state", "")).upper()
        if state in ("SEARCH", "IDENTIFY", "ASSOCIATE", "LOST", "SEARCHING"):
            return None, None, None
    # Prefer active_spot_x/y or predicted_x/y
    ex = tracker_tel.get("active_spot_x", tracker_tel.get("predicted_x", tracker_tel.get("estimate_x")))
    ey = tracker_tel.get("active_spot_y", tracker_tel.get("predicted_y", tracker_tel.get("estimate_y")))
    conf = None
    # Try to derive confidence from autonomy candidates or detection_rate
    try:
        conf = float(tracker_tel.get("detection_rate_pct", 0)) / 100.0 if "detection_rate_pct" in tracker_tel else None
    except Exception:
        conf = None
    # Alternative: autonomy candidates confidence
    if conf is None:
        try:
            cands = tracker_tel.get("autonomy", {}).get("candidates", [])
            if cands:
                conf = float(cands[0].get("confidence", 0) or 0)
        except Exception:
            pass
    try:
        ex = float(ex) if ex is not None else None
        ey = float(ey) if ey is not None else None
    except Exception:
        ex = ey = None
    return ex, ey, conf

def run_one(seed: int, steps: int = 600, ai_enabled: bool = False,
            video: str | Path | None = None, base_dir: str | Path = "outputs/runs",
            sim_kwargs: dict | None = None):
    """Run one seed with structured RunLogger. Returns (run_dir, summary, check)."""
    sim_kwargs = sim_kwargs or {}
    from src.simulation.headless import HeadlessSimulation
    from src.local_terminal.models import AutonomyConfig
    from src.environment.config import EnvironmentConfig

    # Build configs for metadata
    autonomy_cfg = AutonomyConfig(ai_enabled=bool(ai_enabled))
    env_cfg = EnvironmentConfig(seed=seed)

    # Headless sim
    sim = HeadlessSimulation(seed=seed, max_steps=steps, autonomy_config=autonomy_cfg,
                             env_config=env_cfg, **sim_kwargs)
    if video:
        try:
            sim.set_video_source(str(video))
        except Exception as e:
            print(f"[WARN] set_video_source failed: {e}")
    sim.reset(seed=seed)

    # RunLogger with config dump
    configs = {
        "environment": env_cfg,
        "autonomy": autonomy_cfg,
        "seed": seed,
        "steps": steps,
        "video": str(video) if video else None,
        "ai_enabled": bool(ai_enabled),
    }
    rl = RunLogger(base_dir=base_dir, configs=configs, seed=seed,
                   extra_meta={"mode": "benchmark_video" if video else "simulation"})

    # Track previous supervisor state for event dedup (RunLogger also handles bulk)
    prev_state = None
    try:
        prev_state = sim.supervisor.state.value if hasattr(sim.supervisor, "state") else None
    except Exception:
        pass

    # Step loop with per-frame logging
    for step in range(steps):
        t0 = time.perf_counter()
        obs, _, _, _, _ = sim.step()
        dt_ms = (time.perf_counter() - t0) * 1000.0

        tel = obs.get("tracker", {}) or {}
        # State: prefer tel state else supervisor.state
        state = tel.get("state")
        if state is None:
            try:
                state = sim.supervisor.state.value  # type: ignore
            except Exception:
                state = "UNKNOWN"
        state = str(state) if state is not None else "UNKNOWN"

        # FOV geometry for GT extraction (disturbed center if available)
        fov_center = None
        fov_size = (640, 480)
        try:
            # gui path: use camera telemetry; headless: use fov size from sim.camera
            if hasattr(sim, "camera"):
                fov_size = (int(getattr(sim.camera, "fov_width", 640)), int(getattr(sim.camera, "fov_height", 480)))
                # Use disturbed center if available via session? For headless, use boresight world approx -> map to FOV centre
                # For GT extraction we pass FOV centre as boresight mapped to world; use camera.get_fov_center_world
                try:
                    # Use last disturbed center if available
                    dc = getattr(sim, "_last_disturbed_center", None)
                    if dc is not None:
                        fov_center = (float(dc[0]), float(dc[1]))
                    else:
                        fb = bool(getattr(sim.camera_config, "use_measured_feedback", False))
                        fov_center = sim.camera.get_fov_center_world(use_measured=fb)
                except Exception:
                    fov_center = None
        except Exception:
            pass

        gt_x, gt_y, vis = _extract_gt(sim, fov_center=fov_center, fov_size=fov_size)
        est_x, est_y, conf = _extract_estimate(tel, fov_size=fov_size)

        # Pan/tilt from src.camera telemetry
        pan = tilt = None
        try:
            cam_tel = obs.get("camera") or sim.camera.get_telemetry()
            if isinstance(cam_tel, dict):
                pan = cam_tel.get("pan_deg", cam_tel.get("pan"))
                tilt = cam_tel.get("tilt_deg", cam_tel.get("tilt"))
        except Exception:
            pass

        # Timestamp: use sim._sim_time_s if available else step*dt
        timestamp_s = float(getattr(sim, "_sim_time_s", step * (1/30)))
        # Fallback: use frame_index*dt
        if timestamp_s == 0 and step > 0:
            timestamp_s = step * (1/30)

        # Detection confidence fallback
        if conf is None:
            try:
                conf = float(tel.get("snr_db", 0)) / 20.0 if tel.get("snr_db") else 0.0
                conf = max(0.0, min(1.0, conf))
            except Exception:
                conf = None

        rl.log_frame(frame_index=step, timestamp_s=timestamp_s, state=state,
                     ground_truth_x=gt_x, ground_truth_y=gt_y,
                     estimate_x=est_x, estimate_y=est_y,
                     detection_confidence=conf, processing_ms=dt_ms,
                     pan=pan, tilt=tilt)

        # Log state transitions incrementally (compare to supervisor.transitions tail)
        try:
            # Check if supervisor state changed vs prev_state
            curr_st = str(sim.supervisor.state.value) if hasattr(sim.supervisor, "state") else state
            if prev_state is not None and curr_st != prev_state:
                # Find matching transition in supervisor.transitions last entry
                reason = ""
                try:
                    if getattr(sim.supervisor, "transitions", None):
                        last = sim.supervisor.transitions[-1]
                        if last[1] == prev_state and last[2] == curr_st:
                            reason = str(last[3]) if len(last) > 3 else ""
                except Exception:
                    pass
                rl.log_event(timestamp_s=timestamp_s, from_state=prev_state, to_state=curr_st, reason=reason, frame_index=step)
                prev_state = curr_st
            elif prev_state is None:
                prev_state = curr_st
        except Exception:
            pass

        # Bulk import of any missed transitions at the end (dedup handled by file append)
        # We only append incremental above; finalize() will also ensure file exists

    # Ensure any remaining transitions are logged (in case incremental missed some)
    try:
        existing = set((e["from_state"], e["to_state"], e["timestamp_s"]) for e in rl._events)
        for t in getattr(sim.supervisor, "transitions", []) or []:
            try:
                ts, src, dst, reason = (t[0], t[1], t[2], t[3] if len(t) > 3 else "")
                key = (str(src), str(dst), float(ts))
                if key not in existing:
                    rl.log_event(timestamp_s=float(ts), from_state=str(src), to_state=str(dst), reason=str(reason))
            except Exception:
                continue
    except Exception:
        pass

    run_dir = rl.finalize()
    # Load summary for printing
    import json as _json
    summary_path = run_dir / "summary.json"
    summary = {}
    check = {}
    try:
        data = _json.loads(summary_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        check = data.get("check", {})
    except Exception:
        summary = rl.metrics.summary()
        from src.evaluation.requirement_checker import check_requirements as _chk
        check = _chk(summary)

    try:
        sim.close()
    except Exception:
        pass
    return run_dir, summary, check

def main():
    ap = argparse.ArgumentParser(description="Structured benchmark with MetricsLogger -> outputs/runs/<ts>/")
    ap.add_argument("--seeds", type=int, default=2, help="Number of seeds starting at 100")
    ap.add_argument("--steps", type=int, default=600, help="Steps per run (~20s at 30Hz)")
    ap.add_argument("--seed0", type=int, default=100, help="First seed")
    ap.add_argument("--ai", action="store_true", help="Enable AI verifier")
    ap.add_argument("--ai-off", dest="ai", action="store_false", help="Disable AI (default)")
    ap.add_argument("--video", type=str, default=None, help="Optional benchmark video .mp4 (enables PTZ bypass)")
    ap.add_argument("--out", type=str, default="outputs/runs", help="Base output dir")
    ap.set_defaults(ai=False)
    args = ap.parse_args()

    print(f"Structured benchmark: seeds={args.seeds} steps={args.steps} ai={args.ai} video={args.video or '—'}")
    run_dirs = []
    for i in range(args.seeds):
        seed = int(args.seed0 + i)
        print(f"\n--- Seed {seed} ({i+1}/{args.seeds}) ---")
        run_dir, summary, check = run_one(seed=seed, steps=args.steps, ai_enabled=args.ai, video=args.video, base_dir=args.out)
        acq = summary.get("acquisition_time_s")
        acq_s = f"{acq:.2f}s" if acq is not None else "—"
        p50 = summary.get("p50_error_px"); p95 = summary.get("p95_error_px")
        loss = summary.get("lost_pct", 0)
        fps = summary.get("fps", 0)
        overall = check.get("overall", "FAIL")
        p50_s = f"{p50:.1f}" if p50 is not None else "—"
        p95_s = f"{p95:.1f}" if p95 is not None else "—"
        print(f"  acq={acq_s}  p50={p50_s}  p95={p95_s}  loss={loss:.1f}%  fps={fps:.0f}  [{overall}]")
        print(f"  -> {run_dir}  (report.html, summary.json, frames.csv, events.jsonl)")
        run_dirs.append(run_dir)

    # Global benchmark.csv-like summary (append or write new)
    try:
        import csv as _csv
        csv_path = Path(Report) if False else REPO / "Reports" / "benchmark.csv"
        # Instead write to outputs/runs/_index.csv
        idx_path = Path(args.out) / "_benchmark_index.csv"
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        with idx_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["seed","ai","run_dir","acq_s","p50","p95","rmse","lock_pct","loss_pct","fps","overall"])
            w.writeheader()
            for rd in run_dirs:
                try:
                    import json as _j
                    d = _j.loads((rd / "summary.json").read_text(encoding="utf-8"))
                    s = d.get("summary", {}); c = d.get("check", {})
                    # seed from metadata
                    meta = _j.loads((rd / "run_metadata.json").read_text(encoding="utf-8"))
                    w.writerow({
                        "seed": meta.get("seed"),
                        "ai": meta.get("config", {}).get("ai_enabled"),
                        "run_dir": str(rd),
                        "acq_s": s.get("acquisition_time_s"),
                        "p50": s.get("p50_error_px"),
                        "p95": s.get("p95_error_px"),
                        "rmse": s.get("rmse_px"),
                        "lock_pct": s.get("lock_retention_pct"),
                        "loss_pct": s.get("lost_pct"),
                        "fps": s.get("fps"),
                        "overall": c.get("overall"),
                    })
                except Exception:
                    continue
        print(f"\nIndex -> {idx_path}")
    except Exception as e:
        print(f"[WARN] index write failed: {e}")

    print("\nDone. Each run under outputs/runs/<timestamp>/ contains run_metadata.json, frames.csv, events.jsonl, summary.json, report.html")

if __name__ == "__main__":
    main()
