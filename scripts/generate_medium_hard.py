"""
Generate medium/hard dataset 2000-5000 images 640x480
Fully randomized per PDF: world 2000, beacon 1-3 square/circle/random 5-20 default 10, motion 7 profiles, all disturbances S&P 10% + Gaussian 20 + Poisson, jitter ±20, Clear/Haze/Fog/Rain/Low light, platform Linear+6.
70% center camera on target, 30% random offset, fallback re-center if no beacon visible.
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from camera.config import CameraConfig
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.headless import HeadlessSimulation
from target.config import MultiBeaconConfig

def generate_medium_hard(num=3000, output="dataset", split="train", seed=5000, start_idx=0):
    out_img = Path(output) / "images" / split
    out_lbl = Path(output) / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)
    print(f"Generating {num} MEDIUM/HARD images 640x480 fully randomized per PDF -> {out_img} starting at {start_idx}")

    rng = np.random.default_rng(seed)
    difficulties = ["medium", "hard"]
    # For medium/hard, use 50/50 mix
    for i in range(num):
        idx = start_idx + i
        difficulty = str(rng.choice(difficulties))
        w, h = 2000, 2000
        env_cfg = EnvironmentConfig(world_width=w, world_height=h, seed=seed+idx).validate()
        env_cfg = env_cfg.randomize_for_training(rng, difficulty)

        cam_cfg = CameraConfig(fov_width=640, fov_height=480).validate((w,h))

        dist_cfg = DisturbanceConfig().randomize_for_training(rng, difficulty)
        # Ensure fully randomized per PDF: force enable at least one noise type for hard, and ensure all disturbance types are represented across dataset
        # For medium/hard, ensure platform and jitter are varied
        # Already handled by randomize_for_training

        # Beacon fully randomized per PDF
        count = int(rng.integers(1, 4))  # 1-3
        target = int(rng.integers(0, count))
        shape = str(rng.choice(["square", "circle", "random"]))
        size_w = int(rng.integers(5, 21))
        size_h = int(rng.integers(5, 21))
        x = float(rng.integers(200, w-200))
        y = float(rng.integers(200, h-200))
        profiles = ["linear", "curved", "figure_eight", "random", "spiral", "sinusoidal", "zigzag"]
        profile = str(rng.choice(profiles))
        speed = float(rng.uniform(20, 120))
        blinking = bool(rng.random() < 0.1)
        speed_random = bool(rng.random() < 0.2)

        beacon_cfg = MultiBeaconConfig(beacon_count=count, target_index=target, shape=shape, size_w=size_w, size_h=size_h, x=x, y=y, profile=profile, speed=speed, blinking=blinking, speed_random=speed_random).validate()

        sim_seed = seed + idx
        sim = HeadlessSimulation(seed=sim_seed, env_config=env_cfg, camera_config=cam_cfg, disturbance_config=dist_cfg, beacon_config=beacon_cfg, rng=np.random.default_rng(sim_seed))

        # 70% center on target, 30% offset
        try:
            tgt = sim.target
            if rng.random() < 0.7:
                jx = int(rng.integers(-60, 60))
                jy = int(rng.integers(-60, 60))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
            else:
                jx = int(rng.integers(-220, 220))
                jy = int(rng.integers(-160, 160))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
        except Exception:
            pass

        for _ in range(int(rng.integers(0, 4))):
            sim.step()

        obs, _, _, _, _ = sim.step()
        frame = obs["frame"]
        if frame.shape[1] != 640 or frame.shape[0] != 480:
            frame = cv2.resize(frame, (640,480))

        fov_x0, fov_y0, _, _ = sim.camera.get_fov_rect()
        labels = []
        for beacon in sim.beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            try:
                px = float(beacon.x) - float(fov_x0)
                py = float(beacon.y) - float(fov_y0)
            except:
                continue
            if px < -40 or px > 680 or py < -40 or py > 520:
                continue
            size_w_b = int(getattr(beacon, "size_w", 10))
            size_h_b = int(getattr(beacon, "size_h", 10))
            x_center = px / 640
            y_center = py / 480
            if x_center < 0 or x_center > 1 or y_center < 0 or y_center > 1:
                continue
            w_norm = size_w_b / 640
            h_norm = size_h_b / 480
            labels.append((x_center, y_center, w_norm, h_norm))

        if not labels:
            # Fallback re-center
            try:
                tgt = sim.target
                sim.camera.set_position(float(tgt.x), float(tgt.y))
                obs, _, _, _, _ = sim.step()
                frame = obs["frame"]
                if frame.shape[1] != 640 or frame.shape[0] != 480:
                    frame = cv2.resize(frame, (640,480))
                fov_x0, fov_y0, _, _ = sim.camera.get_fov_rect()
                labels = []
                for beacon in sim.beacons:
                    px = float(beacon.x) - float(fov_x0)
                    py = float(beacon.y) - float(fov_y0)
                    if px < -40 or px > 680 or py < -40 or py > 520:
                        continue
                    size_w_b = int(getattr(beacon, "size_w", 10))
                    size_h_b = int(getattr(beacon, "size_h", 10))
                    x_center = px / 640
                    y_center = py / 480
                    if 0 <= x_center <= 1 and 0 <= y_center <= 1:
                        labels.append((x_center, y_center, size_w_b/640, size_h_b/480))
            except Exception:
                pass

        img_name = f"train_{idx:06d}.jpg"
        lbl_name = f"train_{idx:06d}.txt"
        cv2.imwrite(str(out_img / img_name), frame)
        with open(out_lbl / lbl_name, "w") as f:
            for xc, yc, w_n, h_n in labels:
                f.write(f"0 {xc:.6f} {yc:.6f} {w_n:.6f} {h_n:.6f}\n")

        if (i+1) % 500 == 0 or i < 5:
            # Show disturbance summary
            preset = dist_cfg.atmospheric_preset
            jitter = dist_cfg.camera_jitter
            plat = f"{dist_cfg.platform_profile}@{dist_cfg.platform_speed:.1f}"
            noise = f"S&P{dist_cfg.enable_salt_pepper} G{dist_cfg.enable_gaussian} P{dist_cfg.enable_poisson}"
            print(f"  [{i+1}/{num}] {img_name} - {len(labels)} beacons - {shape} {size_w}x{size_h} {profile} {preset} jitter{jitter:.1f} {plat} {noise} diff {difficulty}")

    print(f"Done {num} MEDIUM/HARD images starting at {start_idx} in {split}.")
    yaml_path = Path(output) / "dataset.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(f"path: {Path(output).as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames: ['beacon']\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num", type=int, default=3000)
    parser.add_argument("--output", type=str, default="dataset")
    parser.add_argument("--split", type=str, default="train")
    parser.add_argument("--seed", type=int, default=5000)
    parser.add_argument("--start_idx", type=int, default=0)
    args = parser.parse_args()
    generate_medium_hard(num=args.num, output=args.output, split=args.split, seed=args.seed, start_idx=args.start_idx)
