"""Train, validate, test, and export a YOLO beacon detector.

The test split is never used during training. It is evaluated only when
--test is explicitly requested, keeping final evaluation separate from tuning.

Dataset images are 640x480; YOLO trains square (imgsz x imgsz) with
letterboxing, so inference must use the same imgsz.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_MODEL = "yolo26n.pt"
FALLBACK_MODELS = ("yolo11n.pt", "yolov8n.pt")


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # YAML is simple enough for this project; avoid making PyYAML mandatory.
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            values[k.strip()] = v.strip()
        return values


def _safe_float(value, default: float = float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    # NaN / inf are not useful in JSON summaries; keep NaN as-is for
    # compatibility but never propagate exceptions.
    return result


def _resolve_device(device: str | None):
    """Map user-facing device strings to Ultralytics values.

    Ultralytics understands '', None, 'cpu', '0', '0,1', 'mps', etc.
    Older versions reject 'auto', so translate it to None (auto-select).
    Returns (ultralytics_device, display_label).
    """
    if device is None:
        return None, "auto"
    text = str(device).strip()
    if text.lower() in ("", "auto", "none"):
        return None, "auto"
    return text, text


def _find_resume_checkpoint(project: str, name: str) -> Path | None:
    """Return weights/last.pt under an existing run dir, if present."""
    run_dir = Path(project) / name / "weights" / "last.pt"
    if run_dir.is_file():
        return run_dir
    # Ultralytics increments run names (beacon, beacon2, ...); resume the
    # latest matching dir that actually has a checkpoint.
    parent = Path(project)
    if not parent.is_dir():
        return None
    candidates = sorted(
        (p for p in parent.glob(f"{name}*") if (p / "weights" / "last.pt").is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    if candidates:
        return candidates[-1] / "weights" / "last.pt"
    return None


def _warn_if_split_empty(data_path: Path, cfg: dict) -> None:
    base = data_path.parent if str(cfg.get("path", ".")).strip() in (".", "") else Path(str(cfg["path"]))
    if not base.is_absolute():
        base = (data_path.parent / base).resolve()
    for split in ("train", "val"):
        rel = str(cfg.get(split, f"images/{split}"))
        split_dir = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        if not split_dir.is_dir():
            print(f"[WARNING] {split} directory not found: {split_dir}")
            continue
        images = list(split_dir.glob("*.jpg")) + list(split_dir.glob("*.png"))
        if not images:
            print(f"[WARNING] no training images found in {split_dir}")


def train_yolo(
    data: str = "dataset/dataset.yaml",
    model_path: str = DEFAULT_MODEL,
    epochs: int = 50,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "auto",
    project: str = "runs/detect",
    name: str = "beacon",
    workers: int = 0,
    seed: int = 42,
    patience: int = 15,
    resume: bool = False,
    freeze: int | None = None,
    test: bool = False,
    export_onnx: bool = True,
    single_cls: bool = True,
    close_mosaic: int = 10,
):
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is required: pip install ultralytics torch onnx") from exc

    if epochs <= 0:
        raise ValueError("epochs must be > 0")
    if batch <= 0:
        raise ValueError("batch must be > 0")
    if imgsz < 32 or imgsz % 32 != 0:
        raise ValueError("imgsz must be a multiple of 32 and >= 32")
    if patience < 0:
        raise ValueError("patience must be >= 0")
    if freeze is not None and freeze < 0:
        raise ValueError("freeze must be >= 0 or None")
    if close_mosaic < 0:
        raise ValueError("close_mosaic must be >= 0")

    data_path = Path(data).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset YAML not found: {data_path}")

    # Resolve project to an absolute dir: Ultralytics re-resolves a relative
    # `project` against its own default output dir, which nests outputs as
    # runs/detect/runs/detect/<name> and breaks --resume lookup.
    project = str((Path(project) if Path(project).is_absolute()
                   else Path.cwd() / project).resolve())

    cfg = _load_yaml(data_path)
    if cfg.get("nc") not in (1, "1"):
        raise ValueError(f"Expected one class (beacon), found nc={cfg.get('nc')!r}")
    _warn_if_split_empty(data_path, cfg)

    if os.name == "nt" and workers > 0:
        print(f"[WARNING] workers={workers} is unreliable on Windows; "
              "use --workers 0 if the DataLoader hangs or crashes.")

    run_device, device_label = _resolve_device(device)

    try:
        model = YOLO(model_path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load model {model_path!r}: {exc}. "
            f"Try a known checkpoint such as {', '.join(FALLBACK_MODELS)} "
            "(e.g. --model yolo11n.pt) or a path to a previous best.pt."
        ) from exc

    # Ultralytics `resume=True` only works when continuing an existing run.
    # Guard against the common mistake of passing --resume on a fresh run.
    resume_ckpt = _find_resume_checkpoint(project, name) if resume else None
    if resume and resume_ckpt is None:
        print(f"[WARNING] --resume given but no checkpoint found under "
              f"{Path(project) / name}; starting a fresh run instead.")
        resume = False

    train_args = dict(
        data=str(data_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=run_device,
        workers=workers,
        seed=seed,
        patience=patience,
        project=project,
        name=name,
        plots=True,
        save=True,
        verbose=True,
        pretrained=True,
        resume=resume,
        single_cls=single_cls,
        close_mosaic=close_mosaic,
        # Beacon images can be tiny and point-like. Keep moderate geometric augmentation.
        hsv_h=0.015,
        hsv_s=0.50,
        hsv_v=0.40,
        degrees=0.0,
        translate=0.10,
        scale=0.10,
        shear=0.0,
        perspective=0.0,
        mosaic=0.30,
        mixup=0.0,
        copy_paste=0.0,
    )
    if freeze is not None:
        train_args["freeze"] = freeze

    print(f"Training model={model_path}")
    print(f"Dataset={data_path}")
    print(f"epochs={epochs}, imgsz={imgsz}, batch={batch}, device={device_label}, "
          f"workers={workers}, single_cls={single_cls}")
    results = model.train(**train_args)

    run_dir = Path(getattr(results, "save_dir", Path(project) / name) or Path(project) / name)
    best_pt = run_dir / "weights" / "best.pt"
    if not best_pt.exists():
        best_pt = run_dir / "weights" / "last.pt"
    if not best_pt.exists():
        raise FileNotFoundError(f"Could not find trained weights under {run_dir}")

    best_model = YOLO(str(best_pt))

    print("\nValidation evaluation (val split only):")
    val_metrics = best_model.val(data=str(data_path), split="val", imgsz=imgsz, device=run_device, plots=True)
    box = getattr(val_metrics, "box", None)
    summary = {
        "weights": str(best_pt),
        "run_dir": str(run_dir),
        "model": model_path,
        "dataset": str(data_path),
        "epochs": epochs,
        "imgsz": imgsz,
        "device": device_label,
        "val_precision": _safe_float(getattr(box, "mp", float("nan"))),
        "val_recall": _safe_float(getattr(box, "mr", float("nan"))),
        "val_map50": _safe_float(getattr(box, "map50", float("nan"))),
        "val_map50_95": _safe_float(getattr(box, "map", float("nan"))),
    }

    if test:
        print("\nFINAL TEST evaluation (test split):")
        test_metrics = best_model.val(data=str(data_path), split="test", imgsz=imgsz, device=run_device, plots=True)
        test_box = getattr(test_metrics, "box", None)
        summary.update({
            "test_precision": _safe_float(getattr(test_box, "mp", float("nan"))),
            "test_recall": _safe_float(getattr(test_box, "mr", float("nan"))),
            "test_map50": _safe_float(getattr(test_box, "map50", float("nan"))),
            "test_map50_95": _safe_float(getattr(test_box, "map", float("nan"))),
        })

    summary_path = run_dir / "metrics_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Metrics saved to {summary_path}")

    if export_onnx:
        print("\nExporting ONNX...")
        try:
            exported = best_model.export(format="onnx", imgsz=imgsz, device=run_device)
            print(f"ONNX export: {exported}")
            summary["onnx"] = str(exported)
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[WARNING] ONNX export failed: {exc} "
                  "(install onnx/onnxruntime or rerun with --no-export)")

    return summary


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="YOLO beacon training pipeline")
    parser.add_argument("--data", default="dataset/dataset.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"pretrained .pt or an existing checkpoint (e.g. {', '.join(FALLBACK_MODELS)})")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640,
                        help="square YOLO input; dataset frames are 640x480 and are letterboxed")
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="auto",
                        help="'auto' (default), 'cpu', 'mps', or CUDA id like '0'")
    parser.add_argument("--workers", type=int, default=0,
                        help="DataLoader workers; use 0 on Windows if loading hangs")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--project", default="runs/detect")
    parser.add_argument("--name", default="beacon")
    parser.add_argument("--freeze", type=int, default=None)
    parser.add_argument("--resume", action="store_true",
                        help="continue from the latest checkpoint under project/name")
    parser.add_argument("--test", action="store_true", help="evaluate the untouched test split after training")
    parser.add_argument("--no-export", dest="export_onnx", action="store_false")
    parser.add_argument("--close-mosaic", type=int, default=10,
                        help="epochs before the end to disable mosaic (0 keeps it on)")
    single_cls_group = parser.add_mutually_exclusive_group()
    single_cls_group.add_argument("--single-cls", dest="single_cls", action="store_true", default=True,
                                  help="treat all classes as one (default on)")
    single_cls_group.add_argument("--no-single-cls", dest="single_cls", action="store_false",
                                  help="disable single-class training")
    args = parser.parse_args(argv)

    if args.imgsz != 640:
        print(f"[WARNING] project frames are 640x480; imgsz={args.imgsz} "
              "still works via letterboxing but inference must use the same value.")
    if args.epochs <= 0 or args.batch <= 0:
        raise ValueError("epochs and batch must be > 0")

    train_yolo(
        data=args.data,
        model_path=args.model,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        workers=args.workers,
        seed=args.seed,
        patience=args.patience,
        resume=args.resume,
        freeze=args.freeze,
        test=args.test,
        export_onnx=args.export_onnx,
        single_cls=args.single_cls,
        close_mosaic=args.close_mosaic,
    )


if __name__ == "__main__":
    main()
