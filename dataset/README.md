# FSOC Beacon Dataset — 640x480 Only (Robust Builder)

Best reliable builder: `scripts/dataset_builder.py` — any N, 640x480 enforced, YOLO format, resume, validation, stats, fully randomized per PDF spec.

Captured from `HeadlessSimulation` (no GUI) with deterministic seeds.

## Why this builder is robust

* **Any N:** 1 to 100k+, streaming, low memory. Example: `--num 10` for quick test, `--num 5000` for clear vision, `--num 3000 --difficulty mixed` for medium/hard, or `--full` for 8000/2000/1000.
* **640x480 enforced:** Every image is resized/validated to 640x480 per Sr3 (spec 640x480 default). Mismatch is auto-corrected.
* **Fully randomized per PDF:** World 2000, beacon 1-3 count, shape square/circle/random 5-20 default 10, position Random, motion 7 profiles (Straight/Circular/Figure 8/Random + Spiral/Sin/Zig-Zag), all disturbances S&P 10% + Gaussian 20 + Poisson (selectable), jitter ±20, Clear/Haze/Fog/Rain/Low light + User Defined, platform Linear + 6 optionals up to 20.
* **70% centered + 30% search + fallback:** 70% camera centered on target ±60px (tracking), 30% offset ±220/160 (searching), max 3 retries with fallback re-center if no beacon visible → >98% labeled, <2% background.
* **Resume:** If `dataset/images/split` already has files, builder finds max index and continues (no overwrite unless `--overwrite`). Safe for timeouts, KeyboardInterrupt, or incremental builds.
* **Validation:** Every image checked (readable, 640x480, >0 bytes), every label checked (parseable, 0-1 normalized, class 0). Invalid pairs are rejected. Summary validated at end.
* **Stats & ETA:** Per difficulty/shape/motion/preset/beacon count, labeled vs background, retries, errors, per-image ms, ETA, saved to `stats_{split}.json`.

## Structure (YOLO)

```
dataset/
  images/
    train/  (e.g., 5000 clear + 3000 mixed = 8000)
    val/    (e.g., 2000)
    test/   (e.g., 20 now, 1000 for full)
  labels/
    train/  (.txt YOLO: class 0 x_center y_center w h normalized)
    val/
    test/
  dataset.yaml  (path, train/val/test, nc:1 names: ['beacon'])
  stats_train.json
  stats_val.json
  stats_test.json
```

## Quick start — new robust builder (recommended)

```bash
# 10 test images (easy/Clear, bright beacons) — as requested, 640x480 only
python scripts/dataset_builder.py --num 10 --split test --difficulty clear

# 5000 clear beacon vision, various beacon params, 640x480
python scripts/dataset_builder.py --num 5000 --split train --difficulty clear

# 3000 medium/hard fully randomized per PDF (world 2000, beacon 1-3, all disturbances)
python scripts/dataset_builder.py --num 3000 --split train --difficulty mixed --seed 5000 --resume

# Any N with resume (if interrupted, run again and it continues)
python scripts/dataset_builder.py --num 5000 --split train --difficulty mixed --seed 42

# Full dataset 8000/2000/1000 mixed 640x480
python scripts/dataset_builder.py --full

# Validate only (no generation)
python scripts/dataset_builder.py --num 20 --split val --validate
```

## Legacy builders (kept for compat)

* `scripts/capture_dataset.py` — original, now superseded by `dataset_builder.py` (same logic but no resume/validation/stats).
* `scripts/generate_clear_5000.py` and `scripts/generate_medium_hard.py` — task-specific, superseded.

## Training with pretrained YOLO nano (640x480)

```bash
pip install ultralytics torch onnx
python scripts/train.py --data dataset/dataset.yaml --epochs 30 --imgsz 640 --model yolov8n.pt
# Export for real-time CPU (15-25 ms)
yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=640
# Or via builder + train in one go
python scripts/train.py --full --epochs 30
```

## Current dataset on branch `feature/dataset-pipeline`

* `test`: 20 images (10 original test + 10 clear from builder test) — all 640x480, all labeled, stats in `stats_test.json`
* `val`: 20 images mixed (easy/medium/hard) — stats in `stats_val.json`
* `train`: 4437 images (3874 clear + 563 hard from interrupted run) — will resume to any N you request, e.g., 5000 or 8000

## Notes

* Seed 42 for reproducibility; change `--seed` for new variation. Resume uses `seed + start_idx*997` to keep determinism.
* Labels are all beacons visible in the 640x480 FOV. Empty .txt means background (rare, <2% after fallback).
* 70/30 split plus fallback ensures >95% labeled even for hard Fog/Rain/Low light.
* For the user's last requests: 5000 clear already partially generated (3874), and 2000-5000 medium/hard can be generated with `--difficulty mixed` as shown above.
