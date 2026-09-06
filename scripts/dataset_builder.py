"""FSOC beacon YOLO dataset builder.

Generates independent train/val/test splits in Ultralytics YOLO format.
The generator is deterministic per split seed, resumable, validates image/label
pairs, clips boxes to the image boundary, writes accurate statistics, and never
uses the test split during dataset generation for the other splits.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from camera.config import CameraConfig
from disturbance.config import DisturbanceConfig
from environment.config import EnvironmentConfig
from simulation.headless import HeadlessSimulation
from target.config import MultiBeaconConfig

FOV = (640, 480)
WORLD = (2000, 2000)
CLASS_ID = 0
CLASS_NAME = "beacon"
# Minimum clipped box size in pixels. int()+clamp projection (as in
# scripts/visualize_labels.py) can lose up to ~1px per edge, so a 2px
# threshold guarantees the surviving box still has x2>x1 and y2>y1.
MIN_BOX_PX = 2.0
SHAPES = ("square", "circle", "random")
MOTIONS = ("linear", "curved", "figure_eight", "random", "spiral", "sinusoidal", "zigzag")
DIFFICULTIES = ("easy", "medium", "hard")
MIXED_WEIGHTS = (0.30, 0.40, 0.30)

_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    print("\nInterrupt received. Finishing the current file and saving stats...")


try:
    signal.signal(signal.SIGINT, _handle_sigint)
except Exception:
    pass


def write_dataset_yaml(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "dataset.yaml"
    content = """# FSOC beacon detection dataset - YOLO format\npath: .\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames: ['beacon']\n"""
    path.write_text(content, encoding="utf-8")
    return path


def _extract_index(path: Path) -> int | None:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        return None


def _next_index(image_dir: Path, split: str) -> int:
    if not image_dir.exists():
        return 0
    values = [i for p in image_dir.glob(f"{split}_*.jpg") if (i := _extract_index(p)) is not None]
    return max(values, default=-1) + 1


def _pair_state(img_path: Path, lbl_path: Path, fov_size: tuple[int, int]) -> tuple[bool, str, int]:
    if not img_path.exists() or img_path.stat().st_size <= 0:
        return False, "missing/empty image", 0
    img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if img is None:
        return False, "unreadable image", 0
    if (img.shape[1], img.shape[0]) != fov_size:
        return False, f"wrong image size {img.shape[1]}x{img.shape[0]}", 0
    if not lbl_path.exists():
        return False, "missing label", 0
    text = lbl_path.read_text(encoding="utf-8").strip()
    if not text:
        return True, "background", 0
    count = 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 5:
            return False, f"bad label: {line}", 0
        try:
            cls = int(parts[0])
            vals = [float(x) for x in parts[1:]]
        except ValueError:
            return False, f"non-numeric label: {line}", 0
        if cls != CLASS_ID:
            return False, f"unexpected class {cls}", 0
        if not all(0.0 <= v <= 1.0 for v in vals):
            return False, f"out-of-range label: {line}", 0
        if vals[2] <= 0.0 or vals[3] <= 0.0:
            return False, f"zero-size box: {line}", 0
        count += 1
    return True, "labeled", count


def validate_split(root: Path, split: str, fov_size: tuple[int, int] = FOV) -> dict:
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    images = sorted(image_dir.glob(f"{split}_*.jpg"))
    bad = 0
    labeled = 0
    background = 0
    boxes = 0
    for image in images:
        label = label_dir / f"{image.stem}.txt"
        ok, reason, count = _pair_state(image, label, fov_size)
        if not ok:
            bad += 1
        elif count:
            labeled += 1
            boxes += count
        else:
            background += 1
    return {
        "split": split,
        "images": len(images),
        "labeled_images": labeled,
        "background_images": background,
        "boxes": boxes,
        "invalid_pairs": bad,
        "image_size": f"{fov_size[0]}x{fov_size[1]}",
    }


def _random_beacon_config(rng: np.random.Generator, difficulty: str) -> MultiBeaconConfig:
    w, h = WORLD
    count = int(rng.integers(1, 4))
    target = int(rng.integers(0, count))
    shape = str(rng.choice(SHAPES))
    size_w = int(rng.integers(5, 21))
    size_h = int(rng.integers(5, 21))
    x = float(rng.integers(200, w - 199))
    y = float(rng.integers(200, h - 199))
    profile = str(rng.choice(MOTIONS))
    if difficulty == "easy":
        speed = float(rng.uniform(20, 60))
    elif difficulty == "hard":
        speed = float(rng.uniform(60, 140))
    else:
        speed = float(rng.uniform(20, 120))
    return MultiBeaconConfig(
        beacon_count=count,
        target_index=target,
        shape=shape,
        size_w=size_w,
        size_h=size_h,
        x=x,
        y=y,
        profile=profile,
        speed=speed,
        blinking=bool(rng.random() < 0.05),
        speed_random=bool(rng.random() < 0.20),
    ).validate()


def _difficulty_for(rng: np.random.Generator, requested: str) -> str:
    if requested == "mixed":
        return str(rng.choice(DIFFICULTIES, p=MIXED_WEIGHTS))
    if requested == "clear":
        return "easy"
    return requested


def _build_configs(rng: np.random.Generator, difficulty: str, seed: int, idx: int, attempt: int):
    env_cfg = EnvironmentConfig(world_width=WORLD[0], world_height=WORLD[1], seed=seed + idx + attempt).validate()
    if difficulty == "clear":
        env_cfg = EnvironmentConfig(
            world_width=WORLD[0], world_height=WORLD[1], seed=seed + idx + attempt,
            bg_top=12, bg_bottom=22, vignetting_pct=0, haze_pct=0,
            star_count=int(rng.integers(30, 80)), star_brightness=1.0,
        ).validate()
    else:
        env_cfg = env_cfg.randomize_for_training(rng, difficulty)

    cam_cfg = CameraConfig(fov_width=FOV[0], fov_height=FOV[1]).validate(WORLD)

    if difficulty == "clear":
        dist_cfg = DisturbanceConfig(
            atmospheric_preset="Clear",
            camera_jitter=0,
            platform_speed=0,
            enable_salt_pepper=False,
            enable_gaussian=False,
            enable_poisson=False,
            platform_profile="Linear",
        ).validate()
    else:
        dist_cfg = DisturbanceConfig().randomize_for_training(rng, difficulty)

    beacon_cfg = _random_beacon_config(rng, difficulty)
    sim_seed = seed + idx * 997 + attempt * 101
    sim = HeadlessSimulation(
        seed=sim_seed,
        env_config=env_cfg,
        camera_config=cam_cfg,
        disturbance_config=dist_cfg,
        beacon_config=beacon_cfg,
        rng=np.random.default_rng(sim_seed),
    )
    return sim, beacon_cfg, dist_cfg


def _bbox_from_beacon(beacon, fov_x0: float, fov_y0: float, fov_w: int, fov_h: int):
    try:
        cx = float(beacon.x) - float(fov_x0)
        cy = float(beacon.y) - float(fov_y0)
        bw = max(1.0, float(getattr(beacon, "size_w", 10)))
        bh = max(1.0, float(getattr(beacon, "size_h", 10)))
    except (TypeError, ValueError, AttributeError):
        return None

    x1 = max(0.0, cx - bw / 2.0)
    y1 = max(0.0, cy - bh / 2.0)
    x2 = min(float(fov_w), cx + bw / 2.0)
    y2 = min(float(fov_h), cy + bh / 2.0)
    if x2 <= x1 or y2 <= y1:
        return None
    # Drop sub-pixel edge slivers that would collapse to zero area after
    # the int()+clamp projection used at visualization / training time.
    if (x2 - x1) < MIN_BOX_PX or (y2 - y1) < MIN_BOX_PX:
        return None

    xc = ((x1 + x2) / 2.0) / fov_w
    yc = ((y1 + y2) / 2.0) / fov_h
    w = (x2 - x1) / fov_w
    h = (y2 - y1) / fov_h
    return float(xc), float(yc), float(w), float(h)


def _capture(sim: HeadlessSimulation, rng: np.random.Generator, max_attempts: int = 3):
    last = None
    for attempt in range(max_attempts):
        try:
            target = sim.target
            if rng.random() < 0.70:
                jx = int(rng.integers(-60, 61))
                jy = int(rng.integers(-60, 61))
            else:
                # Search-mode camera displacement is approximately one image FOV.
                jx = int(rng.integers(-FOV[0] // 2, FOV[0] // 2 + 1))
                jy = int(rng.integers(-FOV[1] // 2, FOV[1] // 2 + 1))
            sim.camera.set_position(float(target.x + jx), float(target.y + jy))
        except Exception:
            pass

        for _ in range(int(rng.integers(0, 4))):
            sim.step()
        obs, *_ = sim.step()
        frame = obs.get("frame")
        if frame is None or frame.size == 0:
            continue
        if (frame.shape[1], frame.shape[0]) != FOV:
            frame = cv2.resize(frame, FOV, interpolation=cv2.INTER_LINEAR)

        fov_x0, fov_y0, _, _ = sim.camera.get_fov_rect()
        labels = []
        for beacon in sim.beacons:
            if not getattr(beacon, "enabled", True):
                continue
            if getattr(beacon, "blinking", False) and not getattr(beacon, "_blink_visible", True):
                continue
            box = _bbox_from_beacon(beacon, fov_x0, fov_y0, FOV[0], FOV[1])
            if box is not None:
                labels.append(box)

        last = (frame, labels, {"attempt": attempt})
        if labels:
            return last

        # Center fallback makes the generator robust to an unlucky search position.
        if attempt < max_attempts - 1:
            try:
                target = sim.target
                sim.camera.set_position(float(target.x), float(target.y))
            except Exception:
                pass
    return last


def _safe_remove_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)


def build_dataset(
    num: int,
    output: str = "dataset",
    split: str = "train",
    difficulty: str = "mixed",
    seed: int = 42,
    resume: bool = True,
    overwrite: bool = False,
    validate: bool = True,
) -> dict:
    if split not in {"train", "val", "test"}:
        raise ValueError("split must be train, val, or test")
    if num < 0:
        raise ValueError("num must be >= 0")

    root = Path(output)
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    write_dataset_yaml(root)

    if overwrite:
        _safe_remove_dir(image_dir)
        _safe_remove_dir(label_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        start_idx = 0
    elif resume:
        start_idx = _next_index(image_dir, split)
    else:
        start_idx = 0

    existing = start_idx
    remaining = max(0, num - existing) if resume else num
    rng = np.random.default_rng(seed + start_idx * 9973)
    py_rng = random.Random(seed + start_idx * 13331)

    stats = {
        "split": split,
        "fov": f"{FOV[0]}x{FOV[1]}",
        "requested_total": num,
        "starting_images": existing,
        "requested_new": remaining,
        "saved_new": 0,
        "labeled_new": 0,
        "background_new": 0,
        "failed_images": 0,
        "retries": 0,
        "errors": 0,
        "seed": seed,
        "difficulty_requested": difficulty,
        "counts_by_difficulty": Counter(),
        "shapes": Counter(),
        "motions": Counter(),
        "presets": Counter(),
        "beacon_counts": Counter(),
        "elapsed_sec": 0.0,
    }

    t0 = time.perf_counter()
    for i in range(remaining):
        if _interrupted:
            break
        idx = start_idx + i
        success = False
        for attempt in range(3):
            try:
                actual_diff = _difficulty_for(rng, difficulty)
                sim, beacon_cfg, dist_cfg = _build_configs(rng, actual_diff, seed, idx, attempt)
                result = _capture(sim, rng, max_attempts=3)
                if result is None:
                    raise RuntimeError("capture returned no frame")
                frame, labels, meta = result
                stats["retries"] += int(meta.get("attempt", 0))

                # Training/validation/test are intended to contain visible targets.
                # A background image is allowed only if explicitly requested via --allow-background.
                if not labels:
                    if attempt < 2:
                        continue
                    raise RuntimeError("no visible beacon after retries")

                img_path = image_dir / f"{split}_{idx:06d}.jpg"
                lbl_path = label_dir / f"{split}_{idx:06d}.txt"
                if img_path.exists() or lbl_path.exists():
                    if resume and not overwrite:
                        idx = _next_index(image_dir, split)
                        img_path = image_dir / f"{split}_{idx:06d}.jpg"
                        lbl_path = label_dir / f"{split}_{idx:06d}.txt"
                    else:
                        raise FileExistsError(f"output exists: {img_path}")

                if not cv2.imwrite(str(img_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    raise IOError(f"failed to write {img_path}")
                lbl_path.write_text(
                    "".join(f"{CLASS_ID} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n" for xc, yc, w, h in labels),
                    encoding="utf-8",
                )

                ok, reason, box_count = _pair_state(img_path, lbl_path, FOV)
                if not ok or box_count <= 0:
                    img_path.unlink(missing_ok=True)
                    lbl_path.unlink(missing_ok=True)
                    raise RuntimeError(f"post-write validation failed: {reason}")

                stats["saved_new"] += 1
                stats["labeled_new"] += 1
                stats["counts_by_difficulty"][actual_diff] += 1
                stats["shapes"][str(beacon_cfg.shape)] += 1
                stats["motions"][str(beacon_cfg.profile)] += 1
                stats["presets"][str(dist_cfg.atmospheric_preset)] += 1
                stats["beacon_counts"][int(beacon_cfg.beacon_count)] += 1
                success = True
                break
            except Exception as exc:
                stats["errors"] += 1
                if attempt == 2:
                    print(f"[{idx:06d}] failed after 3 attempts: {exc}")
        if not success:
            stats["failed_images"] += 1

        if i == 0 or (i + 1) % 100 == 0 or i == remaining - 1:
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / max(elapsed, 1e-9)
            eta = (remaining - (i + 1)) / max(rate, 1e-9)
            print(f"[{i+1}/{remaining}] saved={stats['saved_new']} failed={stats['failed_images']} rate={rate:.2f} img/s ETA={eta/60:.1f}m")

    stats["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    stats["total_images"] = len(list(image_dir.glob(f"{split}_*.jpg")))
    stats["validation"] = validate_split(root, split) if validate else None
    for key in ("counts_by_difficulty", "shapes", "motions", "presets", "beacon_counts"):
        stats[key] = {str(k): int(v) for k, v in stats[key].items()}

    stats_path = root / f"stats_{split}.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"Done {split}: {stats['total_images']} total images; stats -> {stats_path}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="FSOC beacon YOLO dataset builder")
    parser.add_argument("--output", default="dataset")
    parser.add_argument("--split", choices=["train", "val", "test"])
    parser.add_argument("--num", type=int, help="target total images for the selected split")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard", "mixed", "clear"], default="mixed")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--overwrite", action="store_true", help="delete the selected split before generation")
    parser.add_argument("--no-validate", dest="validate", action="store_false")
    parser.add_argument("--full", action="store_true", help="generate all three splits")
    parser.add_argument("--train", type=int, default=80000)
    parser.add_argument("--val", type=int, default=10000)
    parser.add_argument("--test", type=int, default=10000)
    args = parser.parse_args()

    global _interrupted
    _interrupted = False

    root = Path(args.output)
    if args.full:
        # Independent seeds reduce accidental correlation between splits.
        build_dataset(args.train, str(root), "train", args.difficulty, args.seed, True, args.overwrite, args.validate)
        build_dataset(args.val, str(root), "val", args.difficulty, args.seed + 100_000, True, args.overwrite, args.validate)
        build_dataset(args.test, str(root), "test", args.difficulty, args.seed + 200_000, True, args.overwrite, args.validate)
    else:
        if args.split is None or args.num is None:
            parser.error("either use --full or provide both --split and --num")
        build_dataset(args.num, str(root), args.split, args.difficulty, args.seed, args.resume, args.overwrite, args.validate)


if __name__ == "__main__":
    main()
