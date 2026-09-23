#!/usr/bin/env python3
"""
scripts/benchmark.py — single runner for validation gates (Plan §11).
Reports acq ≤2s, err p50/p95 ≤10px, loss <5%, reacq ≤1s, FPS ≥25
both AI OFF and ON. Saves Reports/benchmark.csv + summary.
"""
from __future__ import annotations
import time, csv, os, sys, math, statistics
import numpy as np

REPO = os.path.dirname(os.path.dirname(__file__))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simulation.headless import HeadlessSimulation
from local_terminal.models import AutonomyConfig
from environment.config import EnvironmentConfig

def run_one(seed: int, ai_enabled: bool = False, max_steps: int = 600):
    cfg = AutonomyConfig(ai_enabled=ai_enabled)
    sim = HeadlessSimulation(seed=seed, max_steps=max_steps, autonomy_config=cfg)
    sim.reset(seed=seed)
    t0 = time.time()
    acq_time = None
    reacq_times = []
    errors = []
    losses = 0
    prev_state = sim.supervisor.state.value if hasattr(sim.supervisor, 'state') else ''
    was_tracking = False
    reacq_start = None
    for step in range(max_steps):
        obs, _, _, _, _ = sim.step()
        tel = obs.get('tracker', {})
        state = tel.get('state', '')
        # acq
        if acq_time is None and tel.get('acquisition_time_s') is not None:
            acq_time = float(tel['acquisition_time_s'])
        # track errors when locked
        if tel.get('locked'):
            ex = tel.get('tracking_error_x_px')
            ey = tel.get('tracking_error_y_px')
            if ex is not None and ey is not None:
                errors.append(math.hypot(float(ex), float(ey)))
        # loss count
        if tel.get('loss_count', 0) > losses:
            losses = int(tel['loss_count'])
        # reacq timing approx
        if state == 'REACQUIRE' and reacq_start is None:
            reacq_start = sim._sim_time_s
        if prev_state == 'REACQUIRE' and state == 'TRACK':
            if reacq_start is not None:
                reacq_times.append(float(sim._sim_time_s - reacq_start))
                reacq_start = None
        if state != 'REACQUIRE' and reacq_start is not None and step > 5:
            # reset if exited to SEARCH without reacq
            reacq_start = None
        prev_state = state
    elapsed = time.time() - t0
    fps = max_steps / max(elapsed, 1e-6)
    # p50/p95
    if errors:
        es = sorted(errors)
        p50 = es[len(es)//2]
        p95 = es[int(len(es)*0.95)] if len(es) > 5 else es[-1]
        rmse = float(np.sqrt(np.mean(np.square(es)))) if es else 0.0
        lock_pct = len(errors)/max_steps*100.0
    else:
        p50 = p95 = rmse = 0.0
        lock_pct = 0.0
    return {
        'seed': seed,
        'ai': ai_enabled,
        'acq_s': acq_time,
        'p50': p50,
        'p95': p95,
        'rmse': rmse,
        'lock_pct': lock_pct,
        'loss_count': losses,
        'reacq_times': reacq_times,
        'fps': fps,
    }

def main(n: int = 50):
    os.makedirs(os.path.join(REPO, 'Reports'), exist_ok=True)
    rows = []
    print(f"Benchmark {n} seeds each AI OFF/ON …")
    for ai in [False, True]:
        for i in range(n):
            seed = 100 + i
            r = run_one(seed, ai_enabled=ai)
            rows.append(r)
            acq_str = f"{r['acq_s']:.3f}" if r['acq_s'] is not None else "—"
            print(f"AI={'ON' if ai else 'OFF'} seed={seed:03d} acq={acq_str} p50={r['p50']:.1f} p95={r['p95']:.1f} lock={r['lock_pct']:.0f}% fps={r['fps']:.0f}")
    # summary
    for ai in [False, True]:
        subset = [r for r in rows if r['ai'] == ai]
        acqs = [r['acq_s'] for r in subset if r['acq_s'] is not None]
        acq_ok = sum(1 for a in acqs if a <= 2.0) / max(len(acqs),1)*100 if acqs else 0
        p50s = [r['p50'] for r in subset]
        p95s = [r['p95'] for r in subset]
        fpss = [r['fps'] for r in subset]
        reacqs = [t for r in subset for t in r['reacq_times']]
        print(f"\n=== AI {'ON' if ai else 'OFF'} SUMMARY ({len(subset)} runs) ===")
        print(f" acq <=2s: {acq_ok:.0f}% ({len(acqs)}/{len(subset)} locked)")
        if p50s: print(f" p50 {statistics.median(p50s):.1f} px, p95 {statistics.median(p95s):.1f} px")
        if fpss: print(f" FPS median {statistics.median(fpss):.0f}, min {min(fpss):.0f}")
        if reacqs: print(f" reacq median {statistics.median(reacqs):.2f}s max {max(reacqs):.2f}s ({len(reacqs)} events)")
        else: print(" reacq: no events")
        loss_ok = sum(1 for r in subset if r['loss_count']==0)/len(subset)*100 if subset else 0
        print(f" loss-free runs {loss_ok:.0f}%")
    # csv
    csv_path = os.path.join(REPO, 'Reports', 'benchmark.csv')
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['seed','ai','acq_s','p50','p95','rmse','lock_pct','loss_count','fps'])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in ['seed','ai','acq_s','p50','p95','rmse','lock_pct','loss_count','fps']})
    print(f"\nCSV -> {csv_path}")

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=50)
    args = ap.parse_args()
    main(args.seeds)
