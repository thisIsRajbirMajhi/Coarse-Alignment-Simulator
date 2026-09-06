"""Train, validate, test, and export a YOLO beacon detector.

Key properties:
- Train/val/test separation; test is evaluated only with --test.
- Strong dataset/image-label validation, including malformed YOLO labels.
- Auto batch-size support (-1), cache control, AMP, cosine LR, rectangular training.
- Fast/best profiles with explicit CLI arguments taking precedence.
- Resume/checkpoint handling, reproducibility controls, run snapshots and metrics.
- Optional validation confidence sweep for F1 selection.
- Optional ONNX export plus checker/runtime/metric-parity validation.

Dataset source images are 640x480. YOLO uses square inputs by default, so the
same imgsz used for training should be used at inference/export.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_MODEL = str(ROOT / "yolo26n.pt") if (ROOT / "yolo26n.pt").is_file() else "yolo26n.pt"
DEFAULT_DATA = ROOT / "dataset" / "dataset.yaml"
FALLBACK_MODELS = ("yolo11n.pt", "yolov8n.pt")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

log = logging.getLogger("train")


def _parse_scalar(text: str) -> Any:
    """Parse a small YAML scalar for the PyYAML-free fallback parser."""
    t = text.strip()
    if not t:
        return ""
    if t in ("~", "null", "None"):
        return None
    if t.lower() in ("true", "yes", "on"):
        return True
    if t.lower() in ("false", "no", "off"):
        return False
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in inner.split(",")]
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        values: dict = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            k, v = s.split(":", 1)
            v = v.strip()
            if " #" in v and not (v.startswith("'") or v.startswith('"') or v.startswith("[")):
                v = v.split(" #", 1)[0].strip()
            values[k.strip()] = _parse_scalar(v)
        return values


def _safe_float(value, default: float = float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _safe_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_device(device: str | None):
    if device is None:
        return None, "auto"
    text = str(device).strip()
    if text.lower() in ("", "auto", "none"):
        return None, "auto"
    return text, text


def _device_warning(device_label: str) -> None:
    try:
        import torch
    except ImportError:
        return
    cuda_ok = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    if device_label == "auto" and not cuda_ok:
        log.warning("No CUDA device found; auto device will use CPU (slow).")
    elif device_label not in ("auto", "cpu", "mps") and not cuda_ok:
        log.warning("CUDA device '%s' requested but CUDA is unavailable.", device_label)


def _find_resume_checkpoint(project: str, name: str) -> Path | None:
    direct = Path(project) / name / "weights" / "last.pt"
    if direct.is_file():
        return direct
    parent = Path(project)
    if not parent.is_dir():
        return None
    candidates = sorted(
        (p for p in parent.glob(f"{name}*") if (p / "weights" / "last.pt").is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] / "weights" / "last.pt" if candidates else None


def _iter_images(split_dir: Path) -> list[Path]:
    files: list[Path] = []
    for ext in IMAGE_EXTS:
        files.extend(split_dir.glob(f"*{ext}"))
        files.extend(split_dir.glob(f"*{ext.upper()}"))
    return sorted({p.resolve(): p for p in files if p.is_file()}.values())


def _label_dir_for(split_dir: Path, split: str) -> Path | None:
    if split_dir.parts[-2:] == ("images", split):
        return split_dir.parent.parent / "labels" / split
    return None


def _validate_label_file(path: Path, nc: int = 1) -> tuple[bool, str | None, int]:
    """Validate YOLO bbox labels. Returns (valid, reason, number_of_boxes)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        return False, "label is not valid UTF-8", 0
    except OSError as exc:
        return False, f"cannot read label: {exc}", 0

    count = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 5:
            return False, f"line {lineno}: expected 5 fields, got {len(fields)}", count
        try:
            cls = int(fields[0])
            vals = [float(x) for x in fields[1:]]
        except ValueError:
            return False, f"line {lineno}: non-numeric value", count
        if cls < 0 or cls >= nc:
            return False, f"line {lineno}: class {cls} outside [0,{nc - 1}]", count
        if not all(math.isfinite(x) for x in vals):
            return False, f"line {lineno}: NaN/inf value", count
        if not all(0.0 <= x <= 1.0 for x in vals):
            return False, f"line {lineno}: bbox values must be normalized to [0,1]", count
        if vals[2] <= 0 or vals[3] <= 0:
            return False, f"line {lineno}: width/height must be > 0", count
        count += 1
    return True, None, count


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        log.warning("hash failed for %s: %s", path, exc)
        return None


def _check_splits(data_path: Path, cfg: dict, splits=("train", "val", "test"),
                  hash_leakage: bool = False, label_validation: bool = True) -> dict:
    """Inspect each split and validate image/label pairing and optional hashes."""
    base = data_path.parent if str(cfg.get("path", ".")).strip() in (".", "") else Path(str(cfg["path"]))
    if not base.is_absolute():
        base = (data_path.parent / base).resolve()

    report: dict = {}
    split_images: dict[str, list[Path]] = {}
    stem_sets: dict[str, set[str]] = {}
    hash_sets: dict[str, dict[str, Path]] = {}
    nc = _safe_int(cfg.get("nc"), 1) or 1

    for split in splits:
        rel = str(cfg.get(split, f"images/{split}"))
        split_dir = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        label_dir = _label_dir_for(split_dir, split)
        info = {
            "dir": str(split_dir),
            "labels_dir": str(label_dir) if label_dir else None,
            "images": 0,
            "labels": 0,
            "missing_labels": 0,
            "invalid_labels": 0,
            "empty_label_files": 0,
            "boxes": 0,
        }
        if not split_dir.is_dir():
            log.warning("%s directory not found: %s", split, split_dir)
            report[split] = info
            continue

        images = _iter_images(split_dir)
        split_images[split] = images
        stem_sets[split] = {p.stem for p in images}
        info["images"] = len(images)
        if not images:
            log.warning("no images found in %s", split_dir)

        if label_dir is None:
            log.warning("Cannot infer label directory for %s split: %s", split, split_dir)
        elif not label_dir.is_dir():
            log.warning("%s label directory not found: %s", split, label_dir)
            info["missing_labels"] = len(images)
        else:
            for img in images:
                lbl = label_dir / f"{img.stem}.txt"
                if not lbl.is_file():
                    info["missing_labels"] += 1
                    continue
                info["labels"] += 1
                if not label_validation:
                    continue
                valid, reason, box_count = _validate_label_file(lbl, nc=nc)
                if not valid:
                    info["invalid_labels"] += 1
                    if info["invalid_labels"] <= 5:
                        log.warning("[%s] invalid label %s: %s", split, lbl, reason)
                elif box_count == 0:
                    info["empty_label_files"] += 1
                info["boxes"] += box_count

        if info["missing_labels"]:
            log.warning("[%s] %d/%d images missing labels", split, info["missing_labels"], info["images"])
        if info["invalid_labels"]:
            log.warning("[%s] %d invalid label files", split, info["invalid_labels"])
        report[split] = info

    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = stem_sets.get(a, set()) & stem_sets.get(b, set())
        if overlap:
            log.warning("possible leakage: %d identical filenames in %s/%s (e.g. %s)",
                        len(overlap), a, b, sorted(overlap)[:3])

    if hash_leakage:
        for split, images in split_images.items():
            hashes: dict[str, Path] = {}
            for img in images:
                digest = _hash_file(img)
                if digest:
                    hashes[digest] = img
            hash_sets[split] = hashes
        for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
            overlap = set(hash_sets.get(a, {})) & set(hash_sets.get(b, {}))
            if overlap:
                examples = [f"{hash_sets[a][h].name} / {hash_sets[b][h].name}" for h in list(overlap)[:3]]
                log.warning("possible pixel-identical leakage: %d image hashes in %s/%s (%s)",
                            len(overlap), a, b, "; ".join(examples))

    return report


def _setup_determinism(seed: int, deterministic: bool) -> None:
    os.environ.setdefault("PYTHONHASHSEED", str(seed))
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed % (2 ** 32))
    except ImportError:
        pass
    if not deterministic:
        return
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception as exc:
        log.warning("deterministic setup incomplete: %s", exc)


def _load_model_with_fallback(model_path: str, resume_ckpt: Path | None = None):
    from ultralytics import YOLO
    if resume_ckpt is not None:
        return YOLO(str(resume_ckpt)), str(resume_ckpt)

    # Never silently replace a user-specified/custom checkpoint. Fallbacks are
    # only appropriate when the default YOLO checkpoint cannot be loaded.
    candidates = [model_path]
    if model_path == DEFAULT_MODEL:
        candidates.extend(m for m in FALLBACK_MODELS if m != model_path)

    last_err: Exception | None = None
    for cand in candidates:
        try:
            return YOLO(cand), cand
        except Exception as exc:
            last_err = exc
            log.warning("Could not load %r: %s", cand, exc)
    raise RuntimeError(f"Could not load model {model_path!r}: {last_err}") from last_err


def _versions() -> dict:
    info: dict = {}
    for mod in ("ultralytics", "torch", "onnx", "onnxruntime", "cv2", "numpy"):
        try:
            m = __import__(mod)
            info[mod] = getattr(m, "__version__", "installed")
        except ImportError:
            info[mod] = "missing"
    try:
        import torch
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
            try:
                props = torch.cuda.get_device_properties(0)
                info["vram_total_gb"] = round(props.total_memory / (1024 ** 3), 2)
                info["cuda_capability"] = f"{props.major}.{props.minor}"
            except Exception:
                pass
    except Exception:
        pass
    return info


def _parse_results_csv(run_dir: Path) -> dict:
    csv_path = run_dir / "results.csv"
    if not csv_path.is_file():
        return {}
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return {}
    if not rows:
        return {}
    score_key = next((k for k in (
        "fitness", "metrics/mAP50-95(B)", "metrics/mAP50(B)",
        "metrics/mAP50-95", "metrics/mAP50"
    ) if k in rows[0]), None)
    best_epoch = None
    best_score = float("nan")
    if score_key:
        best_val = -float("inf")
        for row in rows:
            try:
                value = float(row.get(score_key, "nan"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > best_val:
                best_val = value
                best_epoch = _safe_int(row.get("epoch"), len(rows))
        if math.isfinite(best_val):
            best_score = best_val
    last_epoch = _safe_int(rows[-1].get("epoch"), len(rows)) or len(rows)
    out = {"epochs_trained": last_epoch}
    if best_epoch is not None:
        out.update({"best_epoch": best_epoch, "best_score_key": score_key, "best_score": best_score})
    return out


def _extract_results_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract best/last epoch metrics, losses, and learning rates from results.csv."""
    csv_path = run_dir / "results.csv"
    if not csv_path.is_file():
        return {}
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as exc:
        log.warning("could not read %s: %s", csv_path, exc)
        return {}
    if not rows:
        return {}

    def num(row: dict, key: str):
        value = row.get(key)
        if value in (None, ""):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    metric_aliases = {
        "precision": ("metrics/precision(B)", "metrics/precision"),
        "recall": ("metrics/recall(B)", "metrics/recall"),
        "map50": ("metrics/mAP50(B)", "metrics/mAP50"),
        "map50_95": ("metrics/mAP50-95(B)", "metrics/mAP50-95"),
        "fitness": ("fitness",),
        "train_box_loss": ("train/box_loss",),
        "train_cls_loss": ("train/cls_loss",),
        "train_dfl_loss": ("train/dfl_loss",),
        "val_box_loss": ("val/box_loss",),
        "val_cls_loss": ("val/cls_loss",),
        "val_dfl_loss": ("val/dfl_loss",),
        "lr_pg0": ("lr/pg0",),
        "lr_pg1": ("lr/pg1",),
        "lr_pg2": ("lr/pg2",),
    }

    def row_score(row: dict) -> float:
        for key in ("fitness", "metrics/mAP50-95(B)", "metrics/mAP50(B)", "metrics/mAP50-95", "metrics/mAP50"):
            value = num(row, key)
            if value is not None:
                return value
        return float("-inf")

    best_row = max(rows, key=row_score)
    last_row = rows[-1]
    out: dict[str, Any] = {}
    best_epoch = _safe_int(best_row.get("epoch"), len(rows))
    last_epoch = _safe_int(last_row.get("epoch"), len(rows))
    if best_epoch is not None:
        out["best_epoch"] = best_epoch
    if last_epoch is not None:
        out["last_epoch"] = last_epoch
        out["epochs_trained"] = last_epoch

    for name, aliases in metric_aliases.items():
        for alias in aliases:
            value = num(best_row, alias)
            if value is not None:
                out[f"best_{name}"] = value
                break
        for alias in aliases:
            value = num(last_row, alias)
            if value is not None:
                out[f"last_{name}"] = value
                break

    return out


def _read_run_config(run_dir: Path) -> dict[str, Any]:
    """Read Ultralytics' generated args.yaml when available."""
    path = run_dir / "args.yaml"
    if not path.is_file():
        return {}
    try:
        return _load_yaml(path)
    except Exception:
        return {}


def _model_summary(model) -> dict[str, Any]:
    """Best-effort model size information without making training depend on profiling APIs."""
    out: dict[str, Any] = {}
    try:
        net = getattr(model, "model", None)
        params = sum(p.numel() for p in net.parameters()) if net is not None else None
        trainable = sum(p.numel() for p in net.parameters() if p.requires_grad) if net is not None else None
        if params is not None:
            out["parameters"] = int(params)
        if trainable is not None:
            out["trainable_parameters"] = int(trainable)
    except Exception:
        pass
    return out


def _git_hash() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10, cwd=str(ROOT))
        return out.stdout.strip() or None
    except Exception:
        return None


def _extract_metrics(prefix: str, metrics) -> dict[str, Any]:
    """Extract aggregate, per-class, loss, speed, and per-image metrics."""
    box = getattr(metrics, "box", None)
    p = _safe_float(getattr(box, "mp", 0.0))
    r = _safe_float(getattr(box, "mr", 0.0))
    out: dict[str, Any] = {
        f"{prefix}_precision": p,
        f"{prefix}_recall": r,
        f"{prefix}_f1": (2 * p * r / (p + r)) if p + r > 0 else 0.0,
        f"{prefix}_map50": _safe_float(getattr(box, "map50", float("nan"))),
        f"{prefix}_map75": _safe_float(getattr(box, "map75", float("nan"))),
        f"{prefix}_map50_95": _safe_float(getattr(box, "map", float("nan"))),
        f"{prefix}_fitness": _safe_float(getattr(metrics, "fitness", float("nan"))),
    }

    # Per-class metrics. This is especially useful even for a one-class beacon dataset,
    # because it gives an explicit beacon AP/P/R/F1 record.
    try:
        class_count = len(getattr(box, "p", []))
        class_names = getattr(metrics, "names", None) or {}
        if class_count:
            per_class = []
            for i in range(class_count):
                cp = _safe_float(box.p[i])
                cr = _safe_float(box.r[i])
                cap50 = _safe_float(box.ap50[i])
                cmap = _safe_float(box.ap[i]) if hasattr(box.ap, "__len__") else float("nan")
                cf1 = 2 * cp * cr / (cp + cr) if cp + cr > 0 else 0.0
                cls_id = int(box.ap_class_index[i]) if len(getattr(box, "ap_class_index", [])) > i else i
                cname = class_names.get(cls_id, str(cls_id)) if isinstance(class_names, dict) else str(cls_id)
                per_class.append({
                    "class_id": cls_id, "class_name": cname,
                    "precision": cp, "recall": cr, "f1": cf1,
                    "ap50": cap50, "map50_95": cmap,
                })
            out[f"{prefix}_per_class"] = per_class
    except Exception as exc:
        log.debug("per-class metric extraction failed for %s: %s", prefix, exc)

    speed = getattr(metrics, "speed", None)
    if isinstance(speed, dict):
        for key in ("preprocess", "inference", "loss", "postprocess"):
            if key in speed:
                out[f"{prefix}_speed_{key}"] = _safe_float(speed.get(key))
        parts = [out.get(f"{prefix}_speed_{k}") for k in ("preprocess", "inference", "postprocess")]
        if all(v is not None and math.isfinite(v) for v in parts):
            out[f"{prefix}_speed_total_ms_per_image"] = round(sum(parts), 4)
            out[f"{prefix}_speed_fps"] = round(1000.0 / sum(parts), 3) if sum(parts) > 0 else float("nan")

    # Final validation losses, when exposed by the metrics object.
    for key in ("box_loss", "cls_loss", "dfl_loss"):
        sources = (getattr(metrics, "results_dict", None), getattr(metrics, "__dict__", None))
        for src in sources:
            if isinstance(src, dict) and src.get(f"val/{key}") is not None:
                out[f"{prefix}_{key}"] = _safe_float(src[f"val/{key}"])
                break

    # Newer Ultralytics detection validation exposes per-image TP/FP/FN/F1.
    try:
        image_metrics = getattr(box, "image_metrics", None)
        if isinstance(image_metrics, dict) and image_metrics:
            tp = fp = fn = 0
            image_f1 = []
            for item in image_metrics.values():
                if not isinstance(item, dict):
                    continue
                tp += int(item.get("tp", 0) or 0)
                fp += int(item.get("fp", 0) or 0)
                fn += int(item.get("fn", 0) or 0)
                iv = item.get("f1")
                if iv is not None:
                    try:
                        image_f1.append(float(iv))
                    except (TypeError, ValueError):
                        pass
            out[f"{prefix}_tp"] = tp
            out[f"{prefix}_fp"] = fp
            out[f"{prefix}_fn"] = fn
            out[f"{prefix}_evaluated_images"] = len(image_metrics)
            if image_f1:
                out[f"{prefix}_mean_image_f1"] = sum(image_f1) / len(image_f1)
    except Exception as exc:
        log.debug("per-image metric extraction failed for %s: %s", prefix, exc)

    return out


def _sweep_conf(model, data: str, imgsz: int, device,
                thresholds=(0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80)) -> dict:
    """Choose the validation confidence threshold maximizing F1."""
    best = {"conf": None, "f1": float("nan"), "precision": float("nan"), "recall": float("nan")}
    rows = []
    for conf in thresholds:
        try:
            metrics = model.val(data=data, split="val", imgsz=imgsz, device=device,
                                conf=conf, verbose=False, plots=False)
        except TypeError:
            return {"enabled": False, "reason": "installed ultralytics val() has no conf kwarg"}
        except Exception as exc:
            log.warning("confidence sweep @ %.2f failed: %s", conf, exc)
            continue
        box = getattr(metrics, "box", None)
        p = _safe_float(getattr(box, "mp", float("nan")))
        r = _safe_float(getattr(box, "mr", float("nan")))
        f1 = 2 * p * r / (p + r) if math.isfinite(p) and math.isfinite(r) and p + r > 0 else float("nan")
        rows.append({"conf": conf, "precision": p, "recall": r, "f1": f1})
        if math.isfinite(f1) and (not math.isfinite(best["f1"]) or f1 > best["f1"]):
            best = {"conf": conf, "f1": f1, "precision": p, "recall": r}
    return {"enabled": True, "best": best, "all": rows}


def _validate_onnx(onnx_path: Path, check_parity: bool, data: str, imgsz: int) -> dict:
    info: dict = {
        "path": str(onnx_path),
        "exists": onnx_path.is_file(),
        "size_bytes": onnx_path.stat().st_size if onnx_path.is_file() else 0,
    }
    if not onnx_path.is_file():
        return info
    try:
        import onnx
        onnx.checker.check_model(str(onnx_path))
        info["checker"] = "ok"
    except ImportError:
        info["checker"] = "onnx not installed"
    except Exception as exc:
        info["checker"] = f"failed: {exc}"
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        info["runtime"] = "ok"
        info["inputs"] = [{"name": i.name, "shape": list(i.shape)} for i in sess.get_inputs()]
    except ImportError:
        info["runtime"] = "onnxruntime not installed"
    except Exception as exc:
        info["runtime"] = f"failed: {exc}"
    if check_parity:
        try:
            from ultralytics import YOLO
            onnx_model = YOLO(str(onnx_path))
            m = onnx_model.val(data=data, split="val", imgsz=imgsz, device="cpu", verbose=False, plots=False)
            box = getattr(m, "box", None)
            info["parity_val_map50"] = _safe_float(getattr(box, "map50", float("nan")))
            info["parity_val_map50_95"] = _safe_float(getattr(box, "map", float("nan")))
        except Exception as exc:
            info["parity_error"] = str(exc)
    return info


def _parse_cache(value: str | bool) -> str | bool:
    if isinstance(value, bool):
        return value
    low = str(value).strip().lower()
    if low in ("false", "no", "0", "none", "off", ""):
        return False
    if low in ("true", "yes", "1", "on"):
        return True
    if low in ("ram", "disk"):
        return low
    raise ValueError("cache must be one of: false, true, ram, disk")


def _explicit_dests(argv: list[str]) -> set[str]:
    """Return argparse destinations explicitly supplied by the user.

    This prevents profile presets from overwriting an intentional value equal to
    the parser default (e.g. `--cache false`).
    """
    mapping = {
        "--data": "data", "--model": "model", "--profile": "profile", "--epochs": "epochs",
        "--imgsz": "imgsz", "--batch": "batch", "--device": "device", "--workers": "workers",
        "--seed": "seed", "--patience": "patience", "--save-dir": "save_dir", "--time": "time_hours", "--boxloss-patience": "boxloss_patience",
        "--boxloss-min-delta": "boxloss_min_delta", "--project": "project", "--name": "name",
        "--freeze": "freeze", "--close-mosaic": "close_mosaic", "--lr0": "lr0", "--lrf": "lrf",
        "--momentum": "momentum", "--weight-decay": "weight_decay", "--warmup-epochs": "warmup_epochs",
        "--optimizer": "optimizer", "--box-gain": "box_gain", "--cls-gain": "cls_gain", "--dfl-gain": "dfl_gain",
        "--mosaic": "mosaic", "--mixup": "mixup",
        "--fliplr": "fliplr", "--flipud": "flipud", "--cache": "cache", "--dropout": "dropout",
        "--save-period": "save_period", "--onnx-opset": "onnx_opset", "--save": "save", "--no-save": "save",
        "--single-cls": "single_cls", "--no-single-cls": "single_cls", "--cos-lr": "cos_lr",
        "--no-amp": "amp", "--amp": "amp", "--rect": "rect", "--multi-scale": "multi_scale",
        "--deterministic": "deterministic", "--exist-ok": "exist_ok", "--overwrite": "overwrite",
        "--no-val": "val_during_train", "--plots": "plots", "--no-plots": "plots",
        "--reval": "reval", "--no-reval": "reval", "--sweep-conf": "sweep_conf",
        "--onnx-simplify": "onnx_simplify", "--no-simplify": "onnx_simplify", "--onnx-dynamic": "onnx_dynamic",
        "--onnx-parity": "onnx_parity", "--dry-run": "dry_run", "--test": "test", "--no-export": "export_onnx",
        "--half": "half", "--augment-val": "augment_val",
        "--hash-leakage": "hash_leakage",
        "--compile": "compile_mode", "--no-compile": "compile_mode", "--fraction": "fraction",
        "--classes": "classes", "--pretrained": "pretrained", "--no-pretrained": "pretrained",
        "--no-cls-remap": "cls_remap", "--nbs": "nbs", "--warmup-momentum": "warmup_momentum",
        "--warmup-bias-lr": "warmup_bias_lr", "--label-smoothing": "label_smoothing",
        "--bgr": "bgr", "--cutmix": "cutmix", "--val-conf": "val_conf", "--val-iou": "val_iou",
        "--max-det": "max_det", "--agnostic-nms": "agnostic_nms", "--save-json": "save_json",
    }
    return {mapping[token.split("=", 1)[0]] for token in argv if token.split("=", 1)[0] in mapping}


def _evaluation_artifacts(run_dir: Path, prefix: str) -> dict[str, str]:
    """Report useful Ultralytics evaluation files when they exist."""
    candidates = {
        "confusion_matrix": "confusion_matrix.png",
        "pr_curve": "PR_curve.png",
        "f1_curve": "F1_curve.png",
        "precision_curve": "P_curve.png",
        "recall_curve": "R_curve.png",
    }
    out = {}
    for key, filename in candidates.items():
        path = run_dir / filename
        if path.is_file():
            out[f"{prefix}_{key}"] = str(path)
    return out


def _log_metric_block(prefix: str, metrics_dict: dict[str, Any]) -> None:
    """Log the core detection metrics for a validation/test run."""
    p = metrics_dict.get(f"{prefix}_precision")
    r = metrics_dict.get(f"{prefix}_recall")
    f1 = metrics_dict.get(f"{prefix}_f1")
    m50 = metrics_dict.get(f"{prefix}_map50")
    m75 = metrics_dict.get(f"{prefix}_map75")
    m5095 = metrics_dict.get(f"{prefix}_map50_95")
    log.info("%s: precision=%.4f recall=%.4f F1=%.4f mAP50=%.4f mAP75=%.4f mAP50-95=%.4f",
             prefix.upper(), p or float("nan"), r or float("nan"), f1 or float("nan"),
             m50 or float("nan"), m75 or float("nan"), m5095 or float("nan"))


def train_yolo(
    data: str = "dataset/dataset.yaml",
    model_path: str = DEFAULT_MODEL,
    epochs: int = 100,
    imgsz: int = 640,
    batch: int | float = -1,
    device: str = "auto",
    project: str = "runs/detect",
    name: str = "beacon",
    save_dir: str | None = None,
    time_hours: float | None = None,
    workers: int = 4,
    seed: int = 42,
    patience: int = 15,
    resume: bool = False,
    freeze: int | None = None,
    test: bool = False,
    export_onnx: bool = False,
    single_cls: bool = True,
    close_mosaic: int = 10,
    boxloss_patience: int | None = 0,
    boxloss_min_delta: float = 0.01,
    plots: bool = True,
    lr0: float = 0.01,
    lrf: float = 0.01,
    momentum: float = 0.937,
    weight_decay: float = 0.0005,
    warmup_epochs: float = 3.0,
    optimizer: str = "auto",
    cos_lr: bool = True,
    box_gain: float = 7.5,
    cls_gain: float = 0.5,
    dfl_gain: float = 1.5,
    hsv_h: float = 0.015,
    hsv_s: float = 0.50,
    hsv_v: float = 0.40,
    degrees: float = 0.0,
    translate: float = 0.10,
    scale: float = 0.10,
    shear: float = 0.0,
    perspective: float = 0.0,
    mosaic: float = 0.30,
    mixup: float = 0.0,
    fliplr: float = 0.5,
    flipud: float = 0.0,
    amp: bool | str = True,
    cache: bool | str = "disk",
    rect: bool = False,
    multi_scale: float = 0.0,
    deterministic: bool = False,
    compile_mode: bool | str = False,
    dropout: float = 0.0,
    fraction: float = 1.0,
    classes: list[int] | None = None,
    pretrained: bool | str = True,
    cls_remap: bool = True,
    save: bool = True,
    nbs: int = 64,
    warmup_momentum: float = 0.8,
    warmup_bias_lr: float = 0.1,
    label_smoothing: float = 0.0,
    bgr: float = 0.0,
    cutmix: float = 0.0,
    exist_ok: bool = False,
    overwrite: bool = False,
    val_during_train: bool = True,
    save_period: int = -1,
    reval: bool = True,
    sweep_conf: bool = False,
    val_conf: float = 0.001,
    val_iou: float = 0.7,
    max_det: int = 300,
    agnostic_nms: bool = False,
    save_json: bool = False,
    half: bool = False,
    augment_val: bool = False,
    onnx_opset: int | None = None,
    onnx_simplify: bool = True,
    onnx_dynamic: bool = False,
    onnx_parity: bool = False,
    dry_run: bool = False,
    hash_leakage: bool = False,
):
    if epochs <= 0:
        raise ValueError("epochs must be > 0")
    if batch == 0 or batch < -1:
        raise ValueError("batch must be > 0, -1 (auto), or a positive fraction below 1 (auto VRAM fraction)")
    if 0 < batch < 1 and batch < 0.01:
        raise ValueError("fractional batch auto mode should be a reasonable fraction such as 0.50-0.90")

    if imgsz < 32 or imgsz % 32 != 0:
        raise ValueError("imgsz must be a multiple of 32 and >= 32")
    if workers < 0:
        raise ValueError("workers must be >= 0")
    if patience < 0:
        raise ValueError("patience must be >= 0")
    if freeze is not None and freeze < 0:
        raise ValueError("freeze must be >= 0 or None")
    if close_mosaic < 0:
        raise ValueError("close_mosaic must be >= 0")
    if boxloss_patience is not None and boxloss_patience < 0:
        raise ValueError("boxloss_patience must be >= 0 or None")
    if boxloss_min_delta < 0:
        raise ValueError("boxloss_min_delta must be >= 0")
    if lr0 <= 0 or lrf <= 0:
        raise ValueError("lr0 and lrf must be > 0")
    if weight_decay < 0 or warmup_epochs < 0 or dropout < 0:
        raise ValueError("weight_decay, warmup_epochs and dropout must be >= 0")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")
    if nbs <= 0:
        raise ValueError("nbs must be > 0")
    if not 0.0 <= label_smoothing <= 1.0:
        raise ValueError("label_smoothing must be between 0 and 1")
    if not 0.0 <= bgr <= 1.0 or not 0.0 <= cutmix <= 1.0:
        raise ValueError("bgr and cutmix must be between 0 and 1")
    if not 0.0 <= val_conf <= 1.0:
        raise ValueError("val_conf must be between 0 and 1")
    if not 0.0 < val_iou < 1.0:
        raise ValueError("val_iou must be between 0 and 1")
    if max_det <= 0:
        raise ValueError("max_det must be > 0")
    if time_hours is not None and time_hours <= 0:
        raise ValueError("time_hours must be > 0 or None")
    if multi_scale < 0 or multi_scale > 1:
        raise ValueError("multi_scale must be between 0 and 1")
    cache = _parse_cache(cache)
    if not save and (resume or reval or test or export_onnx):
        raise ValueError("save=False cannot be combined with resume, validation, test evaluation, or ONNX export in this pipeline")

    data_path = Path(data).resolve()
    if not data_path.is_file():
        raise FileNotFoundError(f"Dataset YAML not found: {data_path}")

    project = str((Path(project) if Path(project).is_absolute() else Path.cwd() / project).resolve())
    if save_dir is not None:
        save_dir = str((Path(save_dir) if Path(save_dir).is_absolute() else Path.cwd() / save_dir).resolve())
    cfg = _load_yaml(data_path)
    if cfg.get("nc") not in (1, "1"):
        raise ValueError(f"Expected one class (beacon), found nc={cfg.get('nc')!r}")
    names = cfg.get("names")
    if isinstance(names, list) and names != ["beacon"]:
        log.warning("dataset names=%r (expected ['beacon'])", names)

    split_report = _check_splits(data_path, cfg, hash_leakage=hash_leakage, label_validation=True)
    for split in ("train", "val"):
        if split_report.get(split, {}).get("images", 0) == 0:
            raise ValueError(f"'{split}' split has 0 images")
        if split_report.get(split, {}).get("missing_labels", 0) > 0:
            raise ValueError(f"'{split}' split contains images with missing labels")
        if split_report.get(split, {}).get("invalid_labels", 0) > 0:
            raise ValueError(f"'{split}' split contains invalid YOLO label files")

    if os.name == "nt" and workers > 0:
        log.info("Windows detected: workers=%d. Use --workers 0 if DataLoader hangs/crashes.", workers)

    run_device, device_label = _resolve_device(device)
    _device_warning(device_label)
    _setup_determinism(seed, deterministic)

    resume_ckpt = _find_resume_checkpoint(project, name) if resume else None
    if resume and resume_ckpt is None:
        log.warning("--resume requested but no checkpoint found under %s; starting fresh.", Path(project) / name)
        resume = False

    from ultralytics import YOLO
    model, resolved_model = _load_model_with_fallback(model_path, resume_ckpt if resume else None)

    if overwrite and not resume:
        import shutil
        run_dir_guess = Path(project) / name
        if run_dir_guess.is_dir():
            log.info("Removing existing run directory: %s", run_dir_guess)
            shutil.rmtree(run_dir_guess)

    train_args: dict[str, Any] = dict(
        data=str(data_path), epochs=epochs, imgsz=imgsz, batch=batch,
        device=run_device, workers=workers, seed=seed, patience=patience,
        project=project, name=name, plots=plots, save=save, verbose=True,
        save_dir=save_dir, time=time_hours,
        resume=resume, single_cls=single_cls,
        close_mosaic=close_mosaic, exist_ok=exist_ok or overwrite,
        val=val_during_train, save_period=save_period, deterministic=deterministic,
        amp=amp, cache=cache, rect=rect, multi_scale=multi_scale, dropout=dropout,
        compile=compile_mode, fraction=fraction, classes=classes, pretrained=pretrained,
        cls_remap=cls_remap, nbs=nbs, warmup_momentum=warmup_momentum,
        warmup_bias_lr=warmup_bias_lr, label_smoothing=label_smoothing,
        bgr=bgr, cutmix=cutmix,
        lr0=lr0, lrf=lrf, momentum=momentum, weight_decay=weight_decay,
        warmup_epochs=warmup_epochs, cos_lr=cos_lr,
        box=box_gain, cls=cls_gain, dfl=dfl_gain,
        hsv_h=hsv_h, hsv_s=hsv_s, hsv_v=hsv_v,
        degrees=degrees, translate=translate, scale=scale,
        shear=shear, perspective=perspective, mosaic=mosaic,
        mixup=mixup,
        fliplr=fliplr, flipud=flipud,
    )
    if freeze is not None:
        train_args["freeze"] = freeze
    if optimizer != "auto":
        train_args["optimizer"] = optimizer

    # Do not register the legacy box-loss stopper by default; mAP fitness is safer.
    if boxloss_patience:
        log.warning("Custom box-loss stopper enabled. For normal runs, keep it at 0.")
        _register_boxloss_stopping(model, boxloss_patience, boxloss_min_delta)

    log.info("Training model=%s (resolved=%s)", model_path, resolved_model)
    log.info("Dataset=%s", data_path)
    log.info("epochs=%d imgsz=%d batch=%s device=%s workers=%d amp=%s cache=%s rect=%s cos_lr=%s",
             epochs, imgsz, batch, device_label, workers, amp, cache, rect, cos_lr)
    if optimizer == "auto" and (lr0 != 0.01 or momentum != 0.937):
        log.warning("optimizer=auto may ignore manually supplied lr0/momentum; use an explicit optimizer to control them.")

    if dry_run:
        return {"dry_run": True, "train_args": train_args, "splits": split_report}

    t_train_start = time.perf_counter()
    try:
        results = model.train(**train_args)
    except KeyboardInterrupt:
        log.warning("Interrupted by user; attempting to evaluate last checkpoint.")
        results = None
    train_duration_sec = round(time.perf_counter() - t_train_start, 1)

    if results is None:
        run_dir = Path(project) / name
        cands = sorted([p for p in Path(project).glob(f"{name}*") if p.is_dir()],
                       key=lambda p: p.stat().st_mtime) if Path(project).is_dir() else []
        if cands:
            run_dir = cands[-1]
    else:
        run_dir = Path(getattr(results, "save_dir", Path(project) / name) or Path(project) / name)

    best_pt = run_dir / "weights" / "best.pt"
    if not best_pt.exists():
        best_pt = run_dir / "weights" / "last.pt"
    if not best_pt.exists():
        raise FileNotFoundError(f"Could not find trained weights under {run_dir}")

    csv_info = _extract_results_metrics(run_dir)
    legacy_csv_info = _parse_results_csv(run_dir)
    if "epochs_trained" not in csv_info:
        csv_info.update(legacy_csv_info)
    train_images = split_report.get("train", {}).get("images", 0)
    epochs_trained = csv_info.get("epochs_trained", epochs)
    throughput = None
    if train_duration_sec > 0 and train_images and epochs_trained:
        throughput = round(train_images * epochs_trained / train_duration_sec, 2)

    snapshot = {
        "train_args": {k: (str(v) if isinstance(v, Path) else v) for k, v in train_args.items()},
        "dataset": str(data_path), "splits": split_report,
        "save_dir": save_dir, "time_hours": time_hours,
        "resolved_model": str(resolved_model), "versions": _versions(), "git": _git_hash(),
    }
    (run_dir / "train_args.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    best_model = YOLO(str(best_pt))
    summary: dict[str, Any] = {
        "weights": str(best_pt), "run_dir": str(run_dir), "model": model_path,
        "resolved_model": str(resolved_model), "dataset": str(data_path),
        "epochs": epochs, "epochs_trained": epochs_trained, "imgsz": imgsz,
        "batch_requested": batch, "device": device_label, "seed": seed,
        "git": _git_hash(), "versions": _versions(),
        "train_images": train_images,
        "val_images": split_report.get("val", {}).get("images", 0),
        "test_images": split_report.get("test", {}).get("images", 0),
        "train_duration_sec": train_duration_sec,
        "throughput_img_per_sec": throughput,
        "model_file_size_mb": round(best_pt.stat().st_size / (1024 ** 2), 2),
        "dataset_train_boxes": split_report.get("train", {}).get("boxes", 0),
        "dataset_val_boxes": split_report.get("val", {}).get("boxes", 0),
        "dataset_test_boxes": split_report.get("test", {}).get("boxes", 0),
        "dataset_train_empty_label_images": split_report.get("train", {}).get("empty_label_files", 0),
        "dataset_val_empty_label_images": split_report.get("val", {}).get("empty_label_files", 0),
        "dataset_test_empty_label_images": split_report.get("test", {}).get("empty_label_files", 0),
        "config": {
            "optimizer": optimizer, "lr0": lr0, "lrf": lrf, "momentum": momentum,
            "weight_decay": weight_decay, "warmup_epochs": warmup_epochs,
            "warmup_momentum": warmup_momentum, "warmup_bias_lr": warmup_bias_lr,
            "cos_lr": cos_lr, "box_gain": box_gain, "cls_gain": cls_gain, "dfl_gain": dfl_gain,
            "amp": amp, "cache": cache, "rect": rect, "multi_scale": multi_scale,
            "compile": compile_mode, "fraction": fraction, "save": save, "nbs": nbs,
            "label_smoothing": label_smoothing, "bgr": bgr, "cutmix": cutmix,
            "mosaic": mosaic, "mixup": mixup, "fliplr": fliplr, "flipud": flipud,
            "classes": classes, "pretrained": pretrained, "cls_remap": cls_remap,
            "degrees": degrees, "translate": translate, "scale": scale, "shear": shear,
            "perspective": perspective, "close_mosaic": close_mosaic,
            "val_conf": val_conf, "val_iou": val_iou, "max_det": max_det,
            "agnostic_nms": agnostic_nms, "save_json": save_json, "half": half,
            "augment_val": augment_val, "save_dir": save_dir, "time_hours": time_hours,
        },
    }
    summary.update(csv_info)
    if "best_precision" in summary and "best_recall" in summary:
        bp, br = summary["best_precision"], summary["best_recall"]
        summary["best_f1"] = (2 * bp * br / (bp + br)) if bp + br > 0 else float("nan")
    summary.update(_model_summary(best_model))
    runtime_args = _read_run_config(run_dir)
    for key in ("batch", "workers", "imgsz", "optimizer", "lr0", "lrf", "device", "amp", "cache", "rect", "cos_lr"):
        if key in runtime_args:
            summary[f"actual_{key}"] = runtime_args[key]

    t_eval_start = time.perf_counter()
    if reval:
        log.info("Validation evaluation (val split only)...")
        val_metrics = best_model.val(data=str(data_path), split="val", imgsz=imgsz, device=run_device,
                                     conf=val_conf, iou=val_iou, max_det=max_det, classes=classes,
                                     agnostic_nms=agnostic_nms, save_json=save_json,
                                     half=half, augment=augment_val, plots=plots)
        val_extracted = _extract_metrics("val", val_metrics)
        summary.update(val_extracted)
        _log_metric_block("val", val_extracted)
        summary["validation_artifacts"] = _evaluation_artifacts(run_dir, "val")
        if sweep_conf:
            summary["conf_sweep"] = _sweep_conf(best_model, str(data_path), imgsz, run_device)
    else:
        log.info("Skipping re-validation (--no-reval).")

    if test:
        log.info("FINAL TEST evaluation (test split)...")
        test_metrics = best_model.val(data=str(data_path), split="test", imgsz=imgsz, device=run_device,
                                      conf=val_conf, iou=val_iou, max_det=max_det,
                                      agnostic_nms=agnostic_nms, save_json=save_json,
                                     half=half, augment=augment_val, plots=plots)
        test_extracted = _extract_metrics("test", test_metrics)
        summary.update(test_extracted)
        _log_metric_block("test", test_extracted)
        summary["test_artifacts"] = _evaluation_artifacts(run_dir, "test")

    summary["eval_duration_sec"] = round(time.perf_counter() - t_eval_start, 1)
    summary["total_duration_sec"] = round(summary["train_duration_sec"] + summary["eval_duration_sec"], 1)
    summary["recommended_confidence"] = (
        summary.get("conf_sweep", {}).get("best", {}).get("conf")
        if summary.get("conf_sweep", {}).get("enabled") else None
    )

    summary_path = run_dir / "metrics_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Metrics saved to %s", summary_path)

    if export_onnx:
        log.info("Exporting ONNX (opset=%s simplify=%s dynamic=%s)...",
                 onnx_opset or "default", onnx_simplify, onnx_dynamic)
        try:
            export_kwargs: dict[str, Any] = dict(format="onnx", imgsz=imgsz, device="cpu",
                                                  simplify=onnx_simplify, dynamic=onnx_dynamic)
            if onnx_opset is not None:
                export_kwargs["opset"] = onnx_opset
            exported = best_model.export(**export_kwargs)
            summary["onnx"] = str(exported)
            summary["onnx_info"] = _validate_onnx(Path(str(exported)), onnx_parity, str(data_path), imgsz)
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("ONNX export failed: %s", exc)

    if throughput is not None:
        log.info("Training throughput: %.2f images/sec", throughput)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YOLO beacon training pipeline")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="Path to dataset.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--profile", choices=["fast", "best"], default=None,
                        help="fast=quick experiment; best=accuracy-oriented run")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=float, default=-1, help="batch size; -1=auto at ~60%% VRAM; 0.70=auto at 70%% VRAM")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--boxloss-patience", type=int, default=0)
    parser.add_argument("--boxloss-min-delta", type=float, default=0.01)
    parser.add_argument("--project", default="runs/detect")
    parser.add_argument("--name", default="beacon")
    parser.add_argument("--save-dir", default=None, help="exact output directory; overrides project/name")
    parser.add_argument("--time", dest="time_hours", type=float, default=None, help="maximum training time in hours; overrides epochs")
    parser.add_argument("--freeze", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--save", dest="save", action="store_true", default=True)
    parser.add_argument("--no-save", dest="save", action="store_false", help="disable checkpoint saving (not recommended)" )
    parser.add_argument("--export", dest="export_onnx", action="store_true", default=False,
                        help="export ONNX after training")
    parser.add_argument("--no-export", dest="export_onnx", action="store_false")
    parser.add_argument("--close-mosaic", type=int, default=10)

    parser.add_argument("--lr0", type=float, default=0.01)
    parser.add_argument("--lrf", type=float, default=0.01)
    parser.add_argument("--momentum", type=float, default=0.937)
    parser.add_argument("--weight-decay", type=float, default=0.0005)
    parser.add_argument("--warmup-epochs", type=float, default=3.0)
    parser.add_argument("--optimizer", default="auto")
    parser.add_argument("--cos-lr", action="store_true", default=True)
    parser.add_argument("--no-cos-lr", dest="cos_lr", action="store_false")
    parser.add_argument("--box-gain", type=float, default=7.5)
    parser.add_argument("--cls-gain", type=float, default=0.5)
    parser.add_argument("--dfl-gain", type=float, default=1.5)

    parser.add_argument("--mosaic", type=float, default=0.30)
    parser.add_argument("--mixup", type=float, default=0.0)
    parser.add_argument("--fliplr", type=float, default=0.5)
    parser.add_argument("--flipud", type=float, default=0.0)

    parser.add_argument("--amp", dest="amp", action="store_true", default=True)
    parser.add_argument("--no-amp", dest="amp", action="store_false")
    parser.add_argument("--cache", default="disk", help="false, true, ram, or disk")
    parser.add_argument("--rect", action="store_true")
    parser.add_argument("--multi-scale", type=float, default=0.0, help="randomly vary image size by +/- this fraction, e.g. 0.25")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--compile", dest="compile_mode", action="store_true", default=False)
    parser.add_argument("--no-compile", dest="compile_mode", action="store_false")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--classes", default=None, help="comma-separated class IDs, e.g. 0,2")
    parser.add_argument("--no-pretrained", dest="pretrained", action="store_false", default=True)
    parser.add_argument("--pretrained", dest="pretrained", action="store_true")
    parser.add_argument("--no-cls-remap", dest="cls_remap", action="store_false", default=True)
    parser.add_argument("--nbs", type=int, default=64)
    parser.add_argument("--warmup-momentum", type=float, default=0.8)
    parser.add_argument("--warmup-bias-lr", type=float, default=0.1)
    parser.add_argument("--label-smoothing", type=float, default=0.0)
    parser.add_argument("--bgr", type=float, default=0.0)
    parser.add_argument("--cutmix", type=float, default=0.0)
    parser.add_argument("--exist-ok", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-val", dest="val_during_train", action="store_false")
    parser.add_argument("--save-period", type=int, default=-1)

    plots_group = parser.add_mutually_exclusive_group()
    plots_group.add_argument("--plots", dest="plots", action="store_true", default=True)
    plots_group.add_argument("--no-plots", dest="plots", action="store_false")
    reval_group = parser.add_mutually_exclusive_group()
    reval_group.add_argument("--reval", dest="reval", action="store_true", default=True)
    reval_group.add_argument("--no-reval", dest="reval", action="store_false")
    parser.add_argument("--sweep-conf", action="store_true")
    parser.add_argument("--val-conf", type=float, default=0.001)
    parser.add_argument("--val-iou", type=float, default=0.7)
    parser.add_argument("--max-det", type=int, default=300)
    parser.add_argument("--agnostic-nms", action="store_true")
    parser.add_argument("--save-json", action="store_true")
    parser.add_argument("--half", action="store_true", help="FP16 validation/inference where supported")
    parser.add_argument("--augment-val", action="store_true", help="test-time augmentation during validation")

    parser.add_argument("--onnx-opset", type=int, default=None)
    parser.add_argument("--no-simplify", dest="onnx_simplify", action="store_false", default=True)
    parser.add_argument("--onnx-dynamic", action="store_true")
    parser.add_argument("--onnx-parity", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hash-leakage", action="store_true",
                        help="hash all images to detect pixel-identical cross-split leakage")

    single_cls_group = parser.add_mutually_exclusive_group()
    single_cls_group.add_argument("--single-cls", dest="single_cls", action="store_true", default=True)
    single_cls_group.add_argument("--no-single-cls", dest="single_cls", action="store_false")
    return parser


def main(argv: list[str] | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    explicit = _explicit_dests(argv)

    presets = {
        "fast": {
            "epochs": 30, "patience": 10, "cache": "ram", "imgsz": 640,
            "mosaic": 0.30, "close_mosaic": 10, "plots": False, "reval": False,
            "sweep_conf": False, "export_onnx": False, "cos_lr": False,
        },
        "best": {
            "epochs": 100, "patience": 20, "cache": "disk", "imgsz": 768,
            "mosaic": 0.30, "close_mosaic": 10, "plots": True, "reval": True,
            "sweep_conf": True, "export_onnx": False, "cos_lr": True,
        },
    }
    if args.profile:
        for key, value in presets[args.profile].items():
            if key not in explicit:
                setattr(args, key, value)
        log.info("Using '%s' profile; explicit CLI arguments take precedence.", args.profile)

    if args.imgsz != 640:
        log.warning("Source frames are 640x480; imgsz=%d will be letterboxed/resized. Use the same imgsz at inference.", args.imgsz)
    if args.batch == 0 or args.batch < -1:
        raise ValueError("batch must be > 0, -1, or a positive fraction between 0 and 1 for auto-batch")
    if 0 < args.batch < 1 and args.batch < 0.01:
        raise ValueError("fractional batch auto mode should be a reasonable fraction such as 0.50-0.90")
    class_ids = None
    if args.classes is not None:
        class_ids = [int(x.strip()) for x in str(args.classes).split(",") if x.strip()]

    return train_yolo(
        data=args.data, model_path=args.model, epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=args.device, project=args.project, name=args.name,
        save_dir=args.save_dir, time_hours=args.time_hours,
        workers=args.workers, seed=args.seed, patience=args.patience,
        resume=args.resume, freeze=args.freeze, test=args.test,
        export_onnx=args.export_onnx, save=args.save, single_cls=args.single_cls,
        close_mosaic=args.close_mosaic, boxloss_patience=args.boxloss_patience,
        boxloss_min_delta=args.boxloss_min_delta, plots=args.plots,
        lr0=args.lr0, lrf=args.lrf, momentum=args.momentum,
        weight_decay=args.weight_decay, warmup_epochs=args.warmup_epochs,
        optimizer=args.optimizer, cos_lr=args.cos_lr,
        box_gain=args.box_gain, cls_gain=args.cls_gain, dfl_gain=args.dfl_gain,
        mosaic=args.mosaic, mixup=args.mixup,
        fliplr=args.fliplr, flipud=args.flipud,
        amp=args.amp, cache=_parse_cache(args.cache), rect=args.rect,
        multi_scale=args.multi_scale, deterministic=args.deterministic, compile_mode=args.compile_mode,
        dropout=args.dropout, fraction=args.fraction, classes=class_ids, pretrained=args.pretrained,
        cls_remap=args.cls_remap, nbs=args.nbs, warmup_momentum=args.warmup_momentum,
        warmup_bias_lr=args.warmup_bias_lr, label_smoothing=args.label_smoothing,
        bgr=args.bgr, cutmix=args.cutmix, exist_ok=args.exist_ok, overwrite=args.overwrite,
        val_during_train=args.val_during_train, save_period=args.save_period,
        reval=args.reval, sweep_conf=args.sweep_conf, val_conf=args.val_conf,
        val_iou=args.val_iou, max_det=args.max_det, agnostic_nms=args.agnostic_nms,
        save_json=args.save_json, half=args.half, augment_val=args.augment_val,
        onnx_opset=args.onnx_opset, onnx_simplify=args.onnx_simplify,
        onnx_dynamic=args.onnx_dynamic, onnx_parity=args.onnx_parity,
        dry_run=args.dry_run, hash_leakage=args.hash_leakage,
    )


def _register_boxloss_stopping(model, patience: int, min_delta: float) -> None:
    state = {"best": float("inf"), "wait": 0}

    def _on_fit_epoch_end(trainer) -> None:
        metrics = getattr(trainer, "metrics", None)
        current = metrics.get("val/box_loss") if isinstance(metrics, dict) else None
        try:
            current = float(current)
        except (TypeError, ValueError):
            return
        if not math.isfinite(current):
            return
        if current < state["best"] - min_delta:
            state["best"] = current
            state["wait"] = 0
        else:
            state["wait"] += 1
            if state["wait"] >= patience:
                log.warning("Early stopping on val/box_loss: no improvement for %d epochs.", patience)
                trainer.stop = True

    model.add_callback("on_fit_epoch_end", _on_fit_epoch_end)


if __name__ == "__main__":
    main()
