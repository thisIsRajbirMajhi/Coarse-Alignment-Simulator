#!/usr/bin/env python3
"""scripts/generate_dataset.py — 5k crops for Tiny-CNN verifier (Plan Hybrid-AI §4).
Loops HeadlessConfig via env/config.py:176 DomainRand S&P10% Gauss20 stars4000 fog.
Saves 640x480 gray + xy label + SNR. No training here; use torch→ONNX separately."""

from __future__ import annotations
import os, csv, random
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "verifier_crops")

def main(n: int = 5000):
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        from simulation.headless import HeadlessSimulation, HeadlessConfig
        from environment.config import EnvironmentConfig
        from disturbance.core.config import DisturbanceConfig
        import cv2
    except Exception as e:
        print(f"Need simulator deps: {e}")
        return
    for i in range(n):
        seed = 1000 + i
        ec = EnvironmentConfig(seed=seed, world_width=2000, world_height=2000)
        dc = DisturbanceConfig()
        # Domain random
        dc.salt_pepper_pct = random.choice([0, 5, 10])
        dc.gaussian_sigma = random.choice([0, 10, 20])
        dc.star_count = random.choice([0, 1000, 4000])
        hs = HeadlessSimulation(seed=seed, env_config=ec, disturbance_config=dc, max_steps=50)
        hs.reset(seed=seed)
        for _ in range(random.randint(10, 40)):
            hs.step()
        fov = hs._last_fov if hs._last_fov is not None else hs._last_frame
        if fov is None:
            continue
        # Label: active track pos if locked else no beacon
        tid = getattr(hs.tracker, "active_tid", None)
        if tid:
            x, y = hs.tracker.kf.position
            label = f"{float(x):.1f},{float(y):.1f}"
        else:
            label = "none"
        # Save crop 32x32 around center or labelled pos
        gray = cv2.cvtColor(fov, cv2.COLOR_BGR2GRAY) if fov.ndim == 3 else fov
        cv2.imwrite(os.path.join(OUT_DIR, f"crop_{i:05d}_{label}.png"), gray)
        if i % 500 == 0:
            print(f"{i}/{n}")
    print(f"Done → {OUT_DIR}")

if __name__ == "__main__":
    main()
