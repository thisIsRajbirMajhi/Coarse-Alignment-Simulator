"""
Generate ~5000 clear beacon images 640x480 for training — various beacon params, easy/Clear only.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import random

from camera.config import CameraConfig
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.headless import HeadlessSimulation
from target.config import MultiBeaconConfig

def generate_clear_dataset(num=5000, output="dataset", split="train", seed=1000):
    out_img = Path(output) / "images" / split
    out_lbl = Path(output) / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)
    print(f"Generating {num} CLEAR beacon images 640x480 -> {out_img}")

    rng = np.random.default_rng(seed)
    for i in range(num):
        # World 2000 fixed for clear
        w, h = 2000, 2000
        # Env Clear: minimal haze, few stars, vot
        env_cfg = EnvironmentConfig(world_width=w, world_height=h, seed=seed+i, bg_top=12, bg_bottom=22, vignetting_pct=0, haze_pct=0, star_count=int(rng.integers(30, 80)), star_brightness=1.0).validate()
        # Camera 640x480
        cam_cfg = CameraConfig(fov_width=640, fov_height=480).validate((w,h))
        # Disturbance Clear: all off, easy
        dist_cfg = DisturbanceConfig(atmospheric_preset="Clear", camera_jitter=0, platform_speed=0, enable_salt_pepper=False, enable_gaussian=False, enable_poisson=False, platform_profile="Linear").validate()
        # Beacon varied: count 1-2, shape random square/circle, size 5-20, motion varied, speed 20-120, random position
        count = int(rng.integers(1, 3))
        target = int(rng.integers(0, count))
        shape = str(rng.choice(["square", "circle", "random"]))
        size_w = int(rng.integers(5, 21))
        size_h = int(rng.integers(5, 21))
        # Random position within world
        x = float(rng.integers(300, w-300))
        y = float(rng.integers(300, h-300))
        profiles = ["linear", "curved", "figure_eight", "random", "spiral", "sinusoidal", "zigzag"]
        profile = str(rng.choice(profiles))
        speed = float(rng.uniform(20, 100))
        # Create sim
        beacon_cfg = MultiBeaconConfig(beacon_count=count, target_index=target, shape=shape, size_w=size_w, size_h=size_h, x=x, y=y, profile=profile, speed=speed, blinking=False, speed_random=False).validate()

        sim = HeadlessSimulation(seed=seed+i, env_config=env_cfg, camera_config=cam_cfg, disturbance_config=dist_cfg, beacon_config=beacon_cfg, rng=np.random.default_rng(seed+i))

        # 70% center camera on target, 30% offset for search variety
        try:
            tgt = sim.target
            if rng.random() < 0.7:
                jx = int(rng.integers(-60, 60))
                jy = int(rng.integers(-60, 60))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
            else:
                jx = int(rng.integers(-200, 200))
                jy = int(rng.integers(-150, 150))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
        except Exception:
            pass

        # Small warm up
        for _ in range(int(rng.integers(0, 3))):
            sim.step()

        # Capture
        obs, _, _, _, _ = sim.step()
        frame = obs["frame"]
        if frame.shape[1] != 640 or frame.shape[0] != 480:
            frame = cv2.resize(frame, (640,480))

        # Labels for all visible beacons
        fov_x0, fov_y0, _, _ = sim.camera.get_fov_rect()
        labels = []
        for beacon in sim.beacons:
            if not getattr(beacon, "enabled", True):
                continue
            try:
                px = float(beacon.x) - float(fov_x0)
                py = float(beacon.y) - float(fov_y0)
            except:
                continue
            if px < -40 or px > 640+40 or py < -40 or py > 480+40:
                continue
            size_w_b = int(getattr(beacon, "size_w", 10))
            size_h_b = int(getattr(beacon, "size_h", 10))
            x_center = px / 640
            y_center = py / 480
            w_norm = size_w_b / 640
            h_norm = size_h_b / 480
            if x_center < 0 or x_center > 1 or y_center < 0 or y_center > 1:
                continue
            labels.append((x_center, y_center, w_norm, h_norm))

        # If no label (rare, beacon just outside), re-center once
        if not labels:
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
                    w_norm = size_w_b / 640
                    h_norm = size_h_b / 480
                    if 0 <= x_center <= 1 and 0 <= y_center <= 1:
                        labels.append((x_center, y_center, w_norm, h_norm))
            except Exception:
                pass

        # Save
        img_name = f"train_{i:06d}.jpg"
        lbl_name = f"train_{i:06d}.txt"
        cv2.imwrite(str(out_img / img_name), frame)
        with open(out_lbl / lbl_name, "w") as f:
            for xc, yc, w_n, h_n in labels:
                f.write(f"0 {xc:.6f} {yc:.6f} {w_n:.6f} {h_n:.6f}\n")

        if (i+1) % 500 == 0 or i < 5:
            print(f"  [{i+1}/{num}] {img_name} - {len(labels)} beacons - shape {shape} {size_w}x{size_h} motion {profile} at ({x:.0f},{y:.0f})")

    print(f"Done {num} CLEAR images in {split}.")
    # Ensure dataset.yaml exists
    yaml_path = Path(output) / "dataset.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(f"path: {Path(output).as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames: ['beacon']\n")
        print(f"Created {yaml_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num", type=int, default=5000)
    parser.add_argument("--output", type=str, default="dataset")
    parser.add_argument("--split", type=str, default="train")
    parser.add_argument("--seed", type=int, default=1000)
    args = parser.parse_args()
    generate_clear_dataset(num=args.num, output=args.output, split=args.split, seed=args.seed)
