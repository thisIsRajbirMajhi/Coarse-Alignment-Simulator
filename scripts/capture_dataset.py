"""
Capture dataset for beacon detection — 640x480 only, YOLO format.

Generates N images by running HeadlessSimulation with randomized configs
(per PDF spec) and saves image + label for each frame.

Usage:
  python scripts/capture_dataset.py --num 10 --output dataset --split test
  python scripts/capture_dataset.py --num 8000 --train 8000 --val 2000 --test 1000

For the current request: 10 images for testing, 640x480.

Labels: YOLO format, class 0 = beacon, normalized x_center/y_center/width/height.
Multiple beacons in view are all labeled. Single beacon default target is labeled.

Directory structure:
  dataset/
    images/train/*.jpg
    images/val/*.jpg
    images/test/*.jpg
    labels/train/*.txt
    labels/val/*.txt
    labels/test/*.txt
    dataset.yaml
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path
import sys

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from camera.config import CameraConfig
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.headless import HeadlessSimulation
from target.config import MultiBeaconConfig
from common.rng import seed_global


def random_env_config(rng: np.random.Generator, difficulty: str = "mixed") -> EnvironmentConfig:
    cfg = EnvironmentConfig()
    # Use its own randomize helper
    return cfg.randomize_for_training(rng, difficulty)


def random_disturbance_config(rng: np.random.Generator, difficulty: str = "mixed") -> DisturbanceConfig:
    cfg = DisturbanceConfig()
    return cfg.randomize_for_training(rng, difficulty)


def random_beacon_config(rng: np.random.Generator, world_size: tuple[int, int], difficulty: str = "mixed") -> MultiBeaconConfig:
    # Randomize beacon count 1-3 for dataset, shape, size, motion
    w, h = world_size
    count = int(rng.integers(1, 4))  # 1-3 for variety
    target = int(rng.integers(0, count))
    shapes = ["square", "circle", "random"]
    shape = str(rng.choice(shapes))
    size_w = int(rng.integers(5, 21))
    size_h = int(rng.integers(5, 21))
    # Random position within world
    x = float(rng.integers(200, max(201, w - 200)))
    y = float(rng.integers(200, max(201, h - 200)))
    profiles = ["linear", "curved", "figure_eight", "random", "spiral", "sinusoidal", "zigzag"]
    # Weight to ensure at least 4 mandatory appear often
    profile = str(rng.choice(profiles))
    speed = float(rng.uniform(20, 120))
    blinking = bool(rng.random() < 0.15)
    speed_random = bool(rng.random() < 0.25)
    cfg = MultiBeaconConfig(
        beacon_count=count, target_index=target, shape=shape,
        size_w=size_w, size_h=size_h, x=x, y=y,
        profile=profile, speed=speed, blinking=blinking, speed_random=speed_random
    ).validate()
    return cfg


def capture_one_image(
    sim: HeadlessSimulation,
    rng: np.random.Generator,
    world_size: tuple[int, int],
    fov_size: tuple[int, int] = (640, 480),
) -> tuple[np.ndarray, list[dict]]:
    """
    Capture one frame and return (image, labels).
    Labels are list of dict with x_center, y_center, w, h normalized.
    """
    # Step simulation a few times to get motion
    obs, _, _, _, _ = sim.step()
    # Get fov frame from observation (already rendered with disturbances)
    # HeadlessSimulation.step returns obs["frame"] as fov_frame after disturbances
    # But we need to recompute from sim state to get accurate frame
    # Sim's last fov_frame is in obs["frame"]
    frame = obs["frame"]  # 640x480x3 already with disturbances and beacon drawn
    # Compute labels: for each beacon visible in current FOV, compute YOLO normalized box
    labels = []
    fov_x0, fov_y0, fov_x1, fov_y1 = sim.camera.get_fov_rect()
    fov_w, fov_h = fov_size
    for beacon in sim.beacons:
        if not getattr(beacon, "enabled", True):
            continue
        if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
            continue
        try:
            px = float(beacon.x) - float(fov_x0)
            py = float(beacon.y) - float(fov_y0)
        except Exception:
            continue
        # Check visible
        if px < -40 or px > fov_w + 40 or py < -40 or py > fov_h + 40:
            continue
        # Size
        size_w = int(getattr(beacon, "size_w", 10))
        size_h = int(getattr(beacon, "size_h", 10))
        # Normalized YOLO
        x_center = px / fov_w
        y_center = py / fov_h
        w_norm = size_w / fov_w
        h_norm = size_h / fov_h
        # Clip to 0-1
        if x_center < 0 or x_center > 1 or y_center < 0 or y_center > 1:
            continue
        # Ensure box not too tiny
        w_norm = float(np.clip(w_norm, 0.005, 1.0))
        h_norm = float(np.clip(h_norm, 0.005, 1.0))
        labels.append({
            "x_center": float(np.clip(x_center, 0, 1)),
            "y_center": float(np.clip(y_center, 0, 1)),
            "w": w_norm,
            "h": h_norm,
        })
    return frame, labels


def generate_dataset(
    num_images: int = 10,
    output: str = "dataset",
    split: str = "test",
    fov_size: tuple[int, int] = (640, 480),
    difficulties: list[str] | None = None,
    seed: int = 42,
):
    if difficulties is None:
        difficulties = ["easy", "medium", "hard"]

    out_root = Path(output)
    # For single split mode (testing 10), just output to that split
    # For full dataset, caller can specify train/val/test counts separately
    img_dir = out_root / "images" / split
    lbl_dir = out_root / "labels" / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    base_seed = seed

    print(f"Generating {num_images} images for split '{split}' at {fov_size} ...")
    print(f"Output: {img_dir}")

    sim = None
    for i in range(num_images):
        # Randomize configs per image, mixing difficulties
        difficulty = str(rng.choice(difficulties, p=[0.3, 0.4, 0.3])) if len(difficulties) > 1 else difficulties[0]
        # World size 2000 default per spec, but randomize 2000-3000 for variety
        world_w = int(rng.choice([2000, 2000, 3000]))
        world_h = world_w
        env_cfg = EnvironmentConfig(world_width=world_w, world_height=world_h).validate()
        # Randomize a bit via helper
        env_cfg = env_cfg.randomize_for_training(rng, difficulty)

        # Camera fixed 640x480 per request
        cam_cfg = CameraConfig(fov_width=fov_size[0], fov_height=fov_size[1]).validate((world_w, world_h))

        # Disturbance
        dist_cfg = DisturbanceConfig().randomize_for_training(rng, difficulty)

        # Beacon
        beacon_cfg = random_beacon_config(rng, (world_w, world_h), difficulty)

        # Seed per image for determinism
        img_seed = base_seed + i * 997

        sim = HeadlessSimulation(
            seed=img_seed,
            env_config=env_cfg,
            camera_config=cam_cfg,
            disturbance_config=dist_cfg,
            beacon_config=beacon_cfg,
            rng=np.random.default_rng(img_seed),
        )
        # Ensure beacon is in FOV with high probability for training
        # 70% center camera on target, 30% random offset for searching cases
        try:
            tgt = sim.target
            if rng.random() < 0.7:
                # Center on target with small jitter ±80px so beacon stays in view
                jx = int(rng.integers(-80, 80))
                jy = int(rng.integers(-80, 80))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
            else:
                # Random offset up to half FOV for searching cases
                jx = int(rng.integers(-fov_size[0]//2, fov_size[0]//2))
                jy = int(rng.integers(-fov_size[1]//2, fov_size[1]//2))
                sim.camera.set_position(float(tgt.x + jx), float(tgt.y + jy))
        except Exception:
            pass
        # Warm up a few steps to get motion
        for _ in range(int(rng.integers(0, 5))):
            sim.step()

        frame, labels = capture_one_image(sim, rng, (world_w, world_h), fov_size)
        # If no beacon visible and we wanted one, retry once with centered camera
        if len(labels) == 0 and rng.random() < 0.9:
            try:
                tgt = sim.target
                sim.camera.set_position(float(tgt.x), float(tgt.y))
                # Re-capture
                obs, _, _, _, _ = sim.step()
                frame = obs["frame"]
                # Recompute labels for centered view
                labels = []
                fov_x0, fov_y0, _, _ = sim.camera.get_fov_rect()
                fov_w, fov_h = fov_size
                for beacon in sim.beacons:
                    if not getattr(beacon, "enabled", True):
                        continue
                    try:
                        px = float(beacon.x) - float(fov_x0)
                        py = float(beacon.y) - float(fov_y0)
                    except Exception:
                        continue
                    if px < -40 or px > fov_w + 40 or py < -40 or py > fov_h + 40:
                        continue
                    size_w = int(getattr(beacon, "size_w", 10))
                    size_h = int(getattr(beacon, "size_h", 10))
                    x_center = px / fov_w
                    y_center = py / fov_h
                    w_norm = size_w / fov_w
                    h_norm = size_h / fov_h
                    if x_center < 0 or x_center > 1 or y_center < 0 or y_center > 1:
                        continue
                    labels.append({
                        "x_center": float(np.clip(x_center, 0, 1)),
                        "y_center": float(np.clip(y_center, 0, 1)),
                        "w": float(np.clip(w_norm, 0.005, 1.0)),
                        "h": float(np.clip(h_norm, 0.005, 1.0)),
                    })
            except Exception:
                pass

        # Save image
        img_name = f"{split}_{i:06d}.jpg"
        lbl_name = f"{split}_{i:06d}.txt"
        img_path = img_dir / img_name
        lbl_path = lbl_dir / lbl_name

        # Ensure frame is 640x480, if not resize
        if frame.shape[1] != fov_size[0] or frame.shape[0] != fov_size[1]:
            frame = cv2.resize(frame, fov_size, interpolation=cv2.INTER_LINEAR)

        cv2.imwrite(str(img_path), frame)

        # Save YOLO labels (class 0)
        with open(lbl_path, "w") as f:
            for lbl in labels:
                f.write(f"0 {lbl['x_center']:.6f} {lbl['y_center']:.6f} {lbl['w']:.6f} {lbl['h']:.6f}\n")
            # If no beacon visible (outside FOV), leave file empty (YOLO background)
            # Alternatively, we could resample until at least one visible — for now ensure at least one
            if not labels:
                # No label means background — keep empty file
                pass

        if (i + 1) % 10 == 0 or i == 0:
            print(f"  [{i+1}/{num_images}] {img_name} - {len(labels)} beacons - diff {difficulty}")

    # Create dataset.yaml
    yaml_path = out_root / "dataset.yaml"
    yaml_content = f"""# YOLO dataset for FSOC beacon — 640x480 only
path: {out_root.as_posix()}
train: images/train
val: images/val
test: images/test
nc: 1
names: ['beacon']
"""
    # Only write if not exists or for test split we keep generic
    if not yaml_path.exists():
        yaml_path.write_text(yaml_content)
        print(f"Created {yaml_path}")
    else:
        print(f"Exists {yaml_path} — not overwriting")

    # Create summary
    total_labeled = sum(1 for p in lbl_dir.glob("*.txt") if p.read_text().strip() != "")
    print(f"Done. {num_images} images in {split}, {total_labeled} with beacons visible.")


def main():
    parser = argparse.ArgumentParser(description="Capture FSOC beacon dataset 640x480 YOLO")
    parser.add_argument("--num", type=int, default=10, help="Number of images for single split (testing)")
    parser.add_argument("--output", type=str, default="dataset", help="Output root")
    parser.add_argument("--split", type=str, default="test", choices=["train", "val", "test"], help="Split name for single split mode")
    parser.add_argument("--fov_w", type=int, default=640, help="FOV width")
    parser.add_argument("--fov_h", type=int, default=480, help="FOV height")
    parser.add_argument("--seed", type=int, default=42, help="Base seed")
    parser.add_argument("--full", action="store_true", help="Generate full dataset: 8000 train 2000 val 1000 test")
    args = parser.parse_args()

    if args.full:
        print("Generating FULL dataset: 8000 train / 2000 val / 1000 test (640x480)")
        generate_dataset(num_images=8000, output=args.output, split="train", fov_size=(args.fov_w, args.fov_h), seed=args.seed)
        generate_dataset(num_images=2000, output=args.output, split="val", fov_size=(args.fov_w, args.fov_h), seed=args.seed + 100000)
        generate_dataset(num_images=1000, output=args.output, split="test", fov_size=(args.fov_w, args.fov_h), seed=args.seed + 200000)
    else:
        generate_dataset(num_images=args.num, output=args.output, split=args.split, fov_size=(args.fov_w, args.fov_h), seed=args.seed)


if __name__ == "__main__":
    main()
