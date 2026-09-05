# FSOC Beacon Dataset — 640x480 only

Captured from `HeadlessSimulation` with randomized configs per PDF spec.

## Structure (YOLO)
```
dataset/
  images/
    train/  (8000) — for --full
    val/    (2000)
    test/   (10 for quick test, 1000 for full)
  labels/
    train/  (.txt YOLO: class 0 x_center y_center w h normalized)
    val/
    test/
  dataset.yaml  (path, train/val/test, nc:1 names: ['beacon'])
```

## Spec coverage
* FOV 640x480 monochrome (copied to 3ch for YOLO) — Sr3 default
* World 2000 (min) — Sr1
* Beacon 1-3 count, shape square/circle/random, size 5-20 default 10, position Random, motion 7 profiles — Sr8-12
* Disturbances per Sr21: S&P 10% + Gaussian 20 + Poisson, jitter ±20, Clear/Haze/Fog/Rain/Low light, platform Linear + 6 optionals

## Quick test (10 images)
```bash
python scripts/capture_dataset.py --num 10 --output dataset --split test --fov_w 640 --fov_h 480
```

## Full dataset
```bash
python scripts/capture_dataset.py --full  # 8000/2000/1000
# or
python scripts/train.py --full --epochs 30
```

## Training (pretrained YOLO nano)
```bash
pip install ultralytics torch onnx
python scripts/train.py --data dataset/dataset.yaml --epochs 30 --imgsz 640 --model yolov8n.pt
# Export
yolo export model=runs/detect/train/weights/best.pt format=onnx
```

## Notes
* 70% images have beacon centered (for tracking), 30% offset (for searching) — plus fallback re-center if no beacon visible ensures >95% labeled.
* Labels are all beacons visible in the 640x480 FOV. Empty .txt means background (rare after fix).
* Seed 42 for reproducibility; change --seed for new variation.
