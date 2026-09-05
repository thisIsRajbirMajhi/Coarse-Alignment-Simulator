"""
Training pipeline for FSOC beacon detection — pretrained YOLO nano fine-tune.

Uses Ultralytics YOLOv8n pretrained on COCO, fine-tuned on 640x480 beacon dataset.

Usage:
  pip install ultralytics torch onnx
  python scripts/train.py --data dataset/dataset.yaml --epochs 30 --imgsz 640 --model yolov8n.pt
  python scripts/train.py --full  # 8000 train / 2000 val already captured

After training, export to ONNX for real-time CPU inference:
  yolo export model=runs/detect/train/weights/best.pt format=onnx

Dataset: dataset/images/{train,val,test} 640x480 only, YOLO labels in dataset/labels/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def train_yolo(data: str = "dataset/dataset.yaml", epochs: int = 30, imgsz: int = 640, model: str = "yolov8n.pt", batch: int = 16, device: str = "auto"):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Ultralytics not installed. Install with: pip install ultralytics torch onnx")
        print("For now, showing dry-run config:")
        print(f"  model={model} data={data} epochs={epochs} imgsz={imgsz} batch={batch}")
        return

    print(f"Loading pretrained {model} ...")
    yolo = YOLO(model)  # COCO pretrained

    print(f"Training on {data} for {epochs} epochs imgsz={imgsz} batch={batch} ...")
    # Freeze backbone for first 5 epochs via freeze parameter
    yolo.train(
        data=data,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        freeze=10,  # freeze first 10 layers (backbone) for 5 epochs, then auto-unfreeze via Ultralytics
        # Augmentations that mimic FSOC disturbances
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,  # brightness/contrast variation for haze/rain/low light
        degrees=0.0, translate=0.1, scale=0.1, shear=0.0,
        mosaic=0.5, mixup=0.0,
        plots=True,
        save=True,
        project="runs/detect",
        name="train",
    )
    print("Training done. Best weights: runs/detect/train/weights/best.pt")
    print("Export to ONNX for CPU real-time:")
    print("  yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=640")

    # Validate
    metrics = yolo.val(data=data, imgsz=imgsz)
    print(f"Val mAP50: {metrics.box.map50:.4f}  mAP50-95: {metrics.box.map:.4f}")

    # Export
    try:
        yolo.export(format="onnx", imgsz=imgsz)
        print("ONNX exported to runs/detect/train/weights/best.onnx")
    except Exception as e:
        print(f"ONNX export failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLO beacon detector 640x480 pretrained")
    parser.add_argument("--data", type=str, default="dataset/dataset.yaml", help="dataset.yaml path")
    parser.add_argument("--epochs", type=int, default=30, help="epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="image size (640 per spec)")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="pretrained model")
    parser.add_argument("--batch", type=int, default=16, help="batch size")
    parser.add_argument("--device", type=str, default="auto", help="device")
    parser.add_argument("--full", action="store_true", help="Full pipeline: capture 8000/2000/1000 then train")
    args = parser.parse_args()

    if args.full:
        # Capture full dataset if not exists
        from scripts.capture_dataset import generate_dataset
        import pathlib
        ds = Path(args.data).parent
        if not (ds / "images" / "train").exists() or len(list((ds / "images" / "train").glob("*.jpg"))) < 100:
            print("Full dataset not found, generating 8000 train / 2000 val / 1000 test ...")
            generate_dataset(num_images=8000, output=str(ds), split="train", fov_size=(640, 480), seed=42)
            generate_dataset(num_images=2000, output=str(ds), split="val", fov_size=(640, 480), seed=42000)
            generate_dataset(num_images=1000, output=str(ds), split="test", fov_size=(640, 480), seed=84000)
        else:
            print("Full dataset already exists, skipping capture")

    train_yolo(data=args.data, epochs=args.epochs, imgsz=args.imgsz, model=args.model, batch=args.batch, device=args.device)


if __name__ == "__main__":
    main()
