from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import torch
import yaml
from ultralytics import YOLO
import ultralytics


# ============================================================
# PROJECT PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

DATASET_DIR = PROJECT_DIR / "dataset"

MODEL_PATH = (
    SCRIPT_DIR
    / "runs"
    / "detect"
    / "beacon"
    / "weights"
    / "best.pt"
)

TEST_IMAGES_DIR = DATASET_DIR / "images" / "test"
TEST_LABELS_DIR = DATASET_DIR / "labels" / "test"

DATA_YAML = DATASET_DIR / "dataset.yaml"

OUTPUT_ROOT = (
    SCRIPT_DIR
    / "runs"
    / "detect"
    / "beacon_test"
)

INFERENCE_OUTPUT_DIR = OUTPUT_ROOT / "inference"
EVALUATION_OUTPUT_DIR = OUTPUT_ROOT / "evaluation"

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "FSOC Beacon/Target YOLO test utility. "
            "Implements Phase 1 inference diagnostics "
            "and Phase 2 labeled test evaluation."
        )
    )

    parser.add_argument(
        "--mode",
        choices={"all", "inference", "evaluate"},
        default="all",
        help="What to run. Default: all",
    )

    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold for inference. Default: 0.25",
    )

    parser.add_argument(
        "--iou",
        type=float,
        default=0.70,
        help=(
            "NMS IoU threshold for inference. "
            "Evaluation uses the Ultralytics validation configuration. "
            "Default: 0.70"
        ),
    )

    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Inference/evaluation image size. Default: 640",
    )

    parser.add_argument(
        "--batch",
        type=int,
        default=12,
        help="Validation batch size. Default: 12",
    )

    parser.add_argument(
        "--device",
        default="0",
        help="CUDA device such as 0, or 'cpu'. Default: 0",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Dataloader workers for evaluation. Default: 4",
    )

    parser.add_argument(
        "--half",
        action="store_true",
        help="Use FP16 inference on CUDA.",
    )

    parser.add_argument(
        "--benchmark-images",
        type=int,
        default=100,
        help=(
            "Maximum number of test images used for the "
            "wall-clock benchmark. Default: 100"
        ),
    )

    parser.add_argument(
        "--benchmark-warmup",
        type=int,
        default=10,
        help="Number of warm-up inferences. Default: 10",
    )

    return parser.parse_args()


# ============================================================
# GENERAL HELPERS
# ============================================================

def ensure_exists(path: Path, description: str) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"{description} does not exist:\n{path}"
        )


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return None

        return result
    except (TypeError, ValueError):
        return None


def json_safe(value: Any) -> Any:
    """
    Convert common NumPy / Torch / Path values into JSON-safe values.
    """
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(k): json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            json_safe(v)
            for v in value
        ]

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass

    return value


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(data),
            file,
            indent=4,
        )


def load_dataset_yaml() -> dict[str, Any]:
    ensure_exists(
        DATA_YAML,
        "Dataset YAML",
    )

    with DATA_YAML.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file) or {}

    return data


def get_class_names(
    dataset_config: dict[str, Any],
) -> dict[int, str]:
    names = dataset_config.get("names")

    if isinstance(names, list):
        return {
            index: str(name)
            for index, name in enumerate(names)
        }

    if isinstance(names, dict):
        result = {}

        for key, value in names.items():
            try:
                class_id = int(key)
            except (TypeError, ValueError):
                continue

            result[class_id] = str(value)

        return result

    return {}


def find_images(directory: Path) -> list[Path]:
    if not directory.exists():
        return []

    images = [
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]

    return sorted(images)


# ============================================================
# DATASET AUDIT
# ============================================================

def validate_label_file(
    label_path: Path,
    num_classes: int | None,
) -> list[str]:
    """
    Validate YOLO detection labels.

    Expected format per line:

        class_id x_center y_center width height

    Coordinates must be normalized to [0, 1].
    """

    errors: list[str] = []

    try:
        lines = label_path.read_text(
            encoding="utf-8"
        ).splitlines()
    except Exception as exc:
        return [
            f"{label_path}: cannot read label file: {exc}"
        ]

    # Empty label file = background image.
    if not lines:
        return errors

    for line_number, raw_line in enumerate(
        lines,
        start=1,
    ):
        line = raw_line.strip()

        if not line:
            continue

        parts = line.split()

        if len(parts) != 5:
            errors.append(
                f"{label_path.name}: line {line_number}: "
                f"expected 5 values, found {len(parts)}"
            )
            continue

        try:
            class_id = int(float(parts[0]))

            x_center = float(parts[1])
            y_center = float(parts[2])
            width = float(parts[3])
            height = float(parts[4])

        except ValueError:
            errors.append(
                f"{label_path.name}: line {line_number}: "
                "non-numeric YOLO label values"
            )
            continue

        if num_classes is not None:
            if class_id < 0 or class_id >= num_classes:
                errors.append(
                    f"{label_path.name}: line {line_number}: "
                    f"class_id={class_id} is outside "
                    f"[0, {num_classes - 1}]"
                )

        for name, value in (
            ("x_center", x_center),
            ("y_center", y_center),
            ("width", width),
            ("height", height),
        ):
            if not 0.0 <= value <= 1.0:
                errors.append(
                    f"{label_path.name}: line {line_number}: "
                    f"{name}={value} is outside [0, 1]"
                )

        if width <= 0:
            errors.append(
                f"{label_path.name}: line {line_number}: "
                f"width={width} must be > 0"
            )

        if height <= 0:
            errors.append(
                f"{label_path.name}: line {line_number}: "
                f"height={height} must be > 0"
            )

    return errors


def audit_test_dataset(
    class_names: dict[int, str],
) -> dict[str, Any]:

    images = find_images(TEST_IMAGES_DIR)

    image_relative_stems = {
        path.relative_to(TEST_IMAGES_DIR).with_suffix("")
        for path in images
    }

    label_files = sorted(
        TEST_LABELS_DIR.rglob("*.txt")
    ) if TEST_LABELS_DIR.exists() else []

    label_relative_stems = {
        path.relative_to(TEST_LABELS_DIR).with_suffix("")
        for path in label_files
    }

    missing_labels = sorted(
        str(stem)
        for stem in image_relative_stems
        if stem not in label_relative_stems
    )

    orphan_labels = sorted(
        str(stem)
        for stem in label_relative_stems
        if stem not in image_relative_stems
    )

    empty_labels: list[str] = []
    invalid_labels: list[str] = []
    total_annotation_objects = 0

    num_classes = (
        len(class_names)
        if class_names
        else None
    )

    for label_path in label_files:

        try:
            text = label_path.read_text(
                encoding="utf-8"
            )
        except Exception as exc:
            invalid_labels.append(
                f"{label_path}: {exc}"
            )
            continue

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            empty_labels.append(
                str(label_path)
            )
            continue

        total_annotation_objects += len(lines)

        errors = validate_label_file(
            label_path,
            num_classes,
        )

        invalid_labels.extend(errors)

    audit = {
        "test_images_directory": str(TEST_IMAGES_DIR),
        "test_labels_directory": str(TEST_LABELS_DIR),
        "image_count": len(images),
        "label_file_count": len(label_files),
        "total_annotation_objects": total_annotation_objects,
        "background_images_with_empty_labels": len(empty_labels),
        "images_without_labels": len(missing_labels),
        "labels_without_images": len(orphan_labels),
        "invalid_label_error_count": len(invalid_labels),
        "missing_labels": missing_labels[:100],
        "orphan_labels": orphan_labels[:100],
        "empty_label_files": empty_labels[:100],
        "invalid_label_errors": invalid_labels[:200],
        "dataset_integrity_pass": (
            len(missing_labels) == 0
            and len(orphan_labels) == 0
            and len(invalid_labels) == 0
        ),
    }

    return audit


# ============================================================
# SYSTEM / MODEL INFORMATION
# ============================================================

def collect_environment_info(
    model: YOLO,
    args: argparse.Namespace,
) -> dict[str, Any]:

    gpu_name = None

    if torch.cuda.is_available():
        try:
            gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            gpu_name = "CUDA device"

    try:
        model_names = {
            int(k): str(v)
            for k, v in model.names.items()
        }
    except Exception:
        model_names = {}

    return {
        "timestamp": datetime.now().isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "ultralytics": getattr(
            ultralytics,
            "__version__",
            "unknown",
        ),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "gpu": gpu_name,
        "model": str(MODEL_PATH),
        "model_names": model_names,
        "device": args.device,
        "half": bool(
            args.half
            and args.device != "cpu"
        ),
        "image_size": args.imgsz,
        "confidence": args.conf,
        "nms_iou": args.iou,
    }


# ============================================================
# PHASE 1 — INFERENCE
# ============================================================

def run_phase1_inference(
    model: YOLO,
    test_images: list[Path],
    class_names: dict[int, str],
    args: argparse.Namespace,
) -> dict[str, Any]:

    print("\n")
    print("=" * 80)
    print("PHASE 1 — INFERENCE / DIAGNOSTICS")
    print("=" * 80)

    INFERENCE_OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    prediction_csv_path = (
        INFERENCE_OUTPUT_DIR
        / "predictions.csv"
    )

    no_detection_path = (
        INFERENCE_OUTPUT_DIR
        / "no_detection.txt"
    )

    detection_counts = Counter()

    class_confidences: dict[str, list[float]] = {}

    no_detection_images: list[str] = []

    prediction_rows: list[dict[str, Any]] = []

    successful_images = 0
    failed_images = 0

    total_speed_preprocess = 0.0
    total_speed_inference = 0.0
    total_speed_postprocess = 0.0

    total_wall_start = time.perf_counter()

    results = model.predict(
        source=str(TEST_IMAGES_DIR),
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        half=(
            args.half
            and args.device != "cpu"
        ),
        save=True,
        save_txt=True,
        save_conf=True,
        project=str(OUTPUT_ROOT),
        name="inference",
        exist_ok=True,
        verbose=False,
        stream=True,
    )

    print(
        f"Testing {len(test_images)} image(s)..."
    )

    for index, result in enumerate(
        results,
        start=1,
    ):

        image_path = Path(result.path)

        try:
            speed = result.speed or {}

            preprocess_ms = float(
                speed.get(
                    "preprocess",
                    0.0,
                )
            )

            inference_ms = float(
                speed.get(
                    "inference",
                    0.0,
                )
            )

            postprocess_ms = float(
                speed.get(
                    "postprocess",
                    0.0,
                )
            )

            total_speed_preprocess += preprocess_ms
            total_speed_inference += inference_ms
            total_speed_postprocess += postprocess_ms

            boxes = result.boxes

            image_detection_count = 0

            if boxes is not None and len(boxes) > 0:

                xyxy = boxes.xyxy.detach().cpu().tolist()
                confidences = boxes.conf.detach().cpu().tolist()
                classes = boxes.cls.detach().cpu().tolist()

                for coords, confidence, class_id_float in zip(
                    xyxy,
                    confidences,
                    classes,
                ):

                    class_id = int(class_id_float)

                    class_name = (
                        class_names.get(
                            class_id,
                            str(
                                model.names.get(
                                    class_id,
                                    f"class_{class_id}",
                                )
                            ),
                        )
                    )

                    confidence = float(confidence)

                    x1, y1, x2, y2 = map(
                        float,
                        coords,
                    )

                    width = x2 - x1
                    height = y2 - y1

                    center_x = (
                        x1 + x2
                    ) / 2.0

                    center_y = (
                        y1 + y2
                    ) / 2.0

                    detection_counts[
                        class_name
                    ] += 1

                    class_confidences.setdefault(
                        class_name,
                        [],
                    ).append(
                        confidence
                    )

                    prediction_rows.append(
                        {
                            "image": str(
                                image_path.relative_to(
                                    TEST_IMAGES_DIR
                                )
                            ),
                            "class_id": class_id,
                            "class_name": class_name,
                            "confidence": round(
                                confidence,
                                6,
                            ),
                            "x1": round(x1, 3),
                            "y1": round(y1, 3),
                            "x2": round(x2, 3),
                            "y2": round(y2, 3),
                            "width": round(width, 3),
                            "height": round(height, 3),
                            "center_x": round(center_x, 3),
                            "center_y": round(center_y, 3),
                            "preprocess_ms": round(
                                preprocess_ms,
                                4,
                            ),
                            "inference_ms": round(
                                inference_ms,
                                4,
                            ),
                            "postprocess_ms": round(
                                postprocess_ms,
                                4,
                            ),
                        }
                    )

                    image_detection_count += 1

            else:

                relative_image = str(
                    image_path.relative_to(
                        TEST_IMAGES_DIR
                    )
                )

                no_detection_images.append(
                    relative_image
                )

            successful_images += 1

            print(
                f"[{index:>5}/{len(test_images)}] "
                f"{image_path.name:<35} "
                f"detections={image_detection_count:<3} "
                f"inference={inference_ms:>6.2f} ms"
            )

        except Exception as exc:

            failed_images += 1

            print(
                f"[{index:>5}/{len(test_images)}] "
                f"FAILED: {image_path}"
            )
            print(
                f"             {exc}"
            )

    total_wall_time = (
        time.perf_counter()
        - total_wall_start
    )

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    with prediction_csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        fieldnames = [
            "image",
            "class_id",
            "class_name",
            "confidence",
            "x1",
            "y1",
            "x2",
            "y2",
            "width",
            "height",
            "center_x",
            "center_y",
            "preprocess_ms",
            "inference_ms",
            "postprocess_ms",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(prediction_rows)

    # --------------------------------------------------------
    # No-detection file
    # --------------------------------------------------------

    with no_detection_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        for image_name in no_detection_images:
            file.write(
                f"{image_name}\n"
            )

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    if successful_images > 0:

        avg_preprocess = (
            total_speed_preprocess
            / successful_images
        )

        avg_inference = (
            total_speed_inference
            / successful_images
        )

        avg_postprocess = (
            total_speed_postprocess
            / successful_images
        )

    else:

        avg_preprocess = 0.0
        avg_inference = 0.0
        avg_postprocess = 0.0

    inference_only_fps = (
        1000.0 / avg_inference
        if avg_inference > 0
        else 0.0
    )

    wall_clock_fps = (
        successful_images / total_wall_time
        if total_wall_time > 0
        else 0.0
    )

    total_detections = sum(
        detection_counts.values()
    )

    class_confidence_summary = {}

    all_confidences: list[float] = []

    for class_name, values in class_confidences.items():

        if not values:
            continue

        all_confidences.extend(values)

        class_confidence_summary[class_name] = {
            "count": len(values),
            "average": round(
                sum(values) / len(values),
                6,
            ),
            "minimum": round(
                min(values),
                6,
            ),
            "maximum": round(
                max(values),
                6,
            ),
        }

    overall_confidence = {
        "count": len(all_confidences),
        "average": (
            round(
                sum(all_confidences)
                / len(all_confidences),
                6,
            )
            if all_confidences
            else 0.0
        ),
        "minimum": (
            round(
                min(all_confidences),
                6,
            )
            if all_confidences
            else 0.0
        ),
        "maximum": (
            round(
                max(all_confidences),
                6,
            )
            if all_confidences
            else 0.0
        ),
    }

    summary = {
        "phase": "phase_1_inference",
        "model": str(MODEL_PATH),
        "test_images_directory": str(
            TEST_IMAGES_DIR
        ),
        "configuration": {
            "confidence": args.conf,
            "iou": args.iou,
            "image_size": args.imgsz,
            "device": args.device,
            "half": bool(
                args.half
                and args.device != "cpu"
            ),
        },
        "dataset": {
            "images_found": len(test_images),
            "images_successfully_processed": successful_images,
            "images_failed": failed_images,
            "images_with_no_detection": len(
                no_detection_images
            ),
            "total_detections": total_detections,
        },
        "detections_by_class": dict(
            detection_counts
        ),
        "confidence": {
            "overall": overall_confidence,
            "by_class": class_confidence_summary,
        },
        "speed_ms_per_image": {
            "preprocess": round(
                avg_preprocess,
                4,
            ),
            "inference": round(
                avg_inference,
                4,
            ),
            "postprocess": round(
                avg_postprocess,
                4,
            ),
        },
        "fps": {
            "inference_only": round(
                inference_only_fps,
                2,
            ),
            "wall_clock_test": round(
                wall_clock_fps,
                2,
            ),
        },
        "total_wall_time_seconds": round(
            total_wall_time,
            3,
        ),
        "outputs": {
            "prediction_images": str(
                INFERENCE_OUTPUT_DIR
            ),
            "predictions_csv": str(
                prediction_csv_path
            ),
            "no_detection_txt": str(
                no_detection_path
            ),
        },
    }

    summary_path = (
        INFERENCE_OUTPUT_DIR
        / "inference_summary.json"
    )

    save_json(
        summary_path,
        summary,
    )

    # --------------------------------------------------------
    # Print result
    # --------------------------------------------------------

    print("\n" + "-" * 80)
    print("PHASE 1 SUMMARY")
    print("-" * 80)

    print(
        f"Images processed       : {successful_images}"
    )
    print(
        f"Failed images          : {failed_images}"
    )
    print(
        f"No detections          : "
        f"{len(no_detection_images)}"
    )
    print(
        f"Total detections       : {total_detections}"
    )

    print("\nDetections by class:")

    if detection_counts:

        for class_name, count in sorted(
            detection_counts.items()
        ):
            print(
                f"  {class_name:<20} {count}"
            )
    else:
        print("  No detections.")

    print("\nConfidence:")

    print(
        f"  Average              : "
        f"{overall_confidence['average']:.4f}"
    )

    print(
        f"  Minimum              : "
        f"{overall_confidence['minimum']:.4f}"
    )

    print(
        f"  Maximum              : "
        f"{overall_confidence['maximum']:.4f}"
    )

    print("\nSpeed:")

    print(
        f"  Preprocess           : "
        f"{avg_preprocess:.2f} ms"
    )

    print(
        f"  Inference            : "
        f"{avg_inference:.2f} ms"
    )

    print(
        f"  Postprocess          : "
        f"{avg_postprocess:.2f} ms"
    )

    print(
        f"  Inference FPS        : "
        f"{inference_only_fps:.2f}"
    )

    print(
        f"  Wall-clock FPS       : "
        f"{wall_clock_fps:.2f}"
    )

    print("\nOutputs:")

    print(
        f"  Predictions          : "
        f"{INFERENCE_OUTPUT_DIR}"
    )

    print(
        f"  CSV                  : "
        f"{prediction_csv_path}"
    )

    print(
        f"  No-detection list    : "
        f"{no_detection_path}"
    )

    print(
        f"  JSON                 : "
        f"{summary_path}"
    )

    return summary


# ============================================================
# PHASE 1 — SPEED BENCHMARK
# ============================================================

def run_speed_benchmark(
    model: YOLO,
    test_images: list[Path],
    args: argparse.Namespace,
) -> dict[str, Any]:

    print("\n")
    print("=" * 80)
    print("PHASE 1 — SPEED BENCHMARK")
    print("=" * 80)

    if not test_images:
        print("No images available for benchmark.")
        return {}

    benchmark_count = min(
        args.benchmark_images,
        len(test_images),
    )

    benchmark_images = test_images[
        :benchmark_count
    ]

    half = (
        args.half
        and args.device != "cpu"
    )

    print(
        f"Benchmark images : {benchmark_count}"
    )

    print(
        f"Warm-up passes   : {args.benchmark_warmup}"
    )

    print(
        f"Device           : {args.device}"
    )

    # --------------------------------------------------------
    # Warm-up
    # --------------------------------------------------------

    warmup_image = str(
        benchmark_images[0]
    )

    print("\nWarming up GPU/model...")

    for _ in range(
        max(0, args.benchmark_warmup)
    ):
        model.predict(
            source=warmup_image,
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            device=args.device,
            half=half,
            verbose=False,
        )

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    # --------------------------------------------------------
    # Benchmark
    # --------------------------------------------------------

    start = time.perf_counter()

    inference_times: list[float] = []

    for image_path in benchmark_images:

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        image_start = time.perf_counter()

        result = model.predict(
            source=str(image_path),
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            device=args.device,
            half=half,
            verbose=False,
        )

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        elapsed_ms = (
            time.perf_counter()
            - image_start
        ) * 1000.0

        inference_times.append(
            elapsed_ms
        )

        # Keep result reference alive until timing is done.
        _ = result

    total_time = (
        time.perf_counter()
        - start
    )

    avg_wall_ms = (
        sum(inference_times)
        / len(inference_times)
        if inference_times
        else 0.0
    )

    min_wall_ms = (
        min(inference_times)
        if inference_times
        else 0.0
    )

    max_wall_ms = (
        max(inference_times)
        if inference_times
        else 0.0
    )

    fps = (
        1000.0 / avg_wall_ms
        if avg_wall_ms > 0
        else 0.0
    )

    total_fps = (
        benchmark_count / total_time
        if total_time > 0
        else 0.0
    )

    peak_vram_mb = None

    if torch.cuda.is_available():

        peak_vram_mb = (
            torch.cuda.max_memory_allocated()
            / (1024 * 1024)
        )

    benchmark = {
        "benchmark_images": benchmark_count,
        "warmup_passes": args.benchmark_warmup,
        "device": args.device,
        "half": half,
        "image_size": args.imgsz,
        "confidence": args.conf,
        "iou": args.iou,
        "average_wall_time_ms": round(
            avg_wall_ms,
            4,
        ),
        "minimum_wall_time_ms": round(
            min_wall_ms,
            4,
        ),
        "maximum_wall_time_ms": round(
            max_wall_ms,
            4,
        ),
        "single_image_fps": round(
            fps,
            2,
        ),
        "overall_benchmark_fps": round(
            total_fps,
            2,
        ),
        "total_benchmark_time_seconds": round(
            total_time,
            3,
        ),
        "peak_gpu_memory_mb": (
            round(
                peak_vram_mb,
                2,
            )
            if peak_vram_mb is not None
            else None
        ),
    }

    path = (
        OUTPUT_ROOT
        / "benchmark_summary.json"
    )

    save_json(
        path,
        benchmark,
    )

    print("\nBenchmark results:")
    print(
        f"  Average latency     : "
        f"{avg_wall_ms:.2f} ms/image"
    )

    print(
        f"  Minimum latency     : "
        f"{min_wall_ms:.2f} ms/image"
    )

    print(
        f"  Maximum latency     : "
        f"{max_wall_ms:.2f} ms/image"
    )

    print(
        f"  Single-image FPS    : "
        f"{fps:.2f}"
    )

    print(
        f"  Overall benchmark   : "
        f"{total_fps:.2f} FPS"
    )

    if peak_vram_mb is not None:
        print(
            f"  Peak GPU memory     : "
            f"{peak_vram_mb:.2f} MB"
        )

    print(
        f"\nSaved to: {path}"
    )

    return benchmark


# ============================================================
# PHASE 2 — TRUE TEST-SET EVALUATION
# ============================================================

def extract_per_class_metrics(
    metrics: Any,
    class_names: dict[int, str],
) -> dict[str, Any]:

    per_class: dict[str, Any] = {}

    box_metrics = getattr(
        metrics,
        "box",
        None,
    )

    if box_metrics is None:
        return per_class

    precision = getattr(
        box_metrics,
        "p",
        None,
    )

    recall = getattr(
        box_metrics,
        "r",
        None,
    )

    f1 = getattr(
        box_metrics,
        "f1",
        None,
    )

    maps = getattr(
        box_metrics,
        "maps",
        None,
    )

    ap_class_index = getattr(
        box_metrics,
        "ap_class_index",
        None,
    )

    # Convert arrays where possible.
    try:
        precision_list = (
            precision.tolist()
            if precision is not None
            else []
        )
    except Exception:
        precision_list = []

    try:
        recall_list = (
            recall.tolist()
            if recall is not None
            else []
        )
    except Exception:
        recall_list = []

    try:
        f1_list = (
            f1.tolist()
            if f1 is not None
            else []
        )
    except Exception:
        f1_list = []

    try:
        maps_list = (
            maps.tolist()
            if maps is not None
            else []
        )
    except Exception:
        maps_list = []

    try:
        class_index_list = (
            ap_class_index.tolist()
            if ap_class_index is not None
            else []
        )
    except Exception:
        class_index_list = []

    # --------------------------------------------------------
    # In many Ultralytics versions, p/r/f1 are indexed by
    # class ID. Handle that first.
    # --------------------------------------------------------

    if class_index_list:

        for metric_index, class_id_value in enumerate(
            class_index_list
        ):

            class_id = int(
                class_id_value
            )

            class_name = class_names.get(
                class_id,
                f"class_{class_id}",
            )

            row = {}

            if metric_index < len(
                precision_list
            ):
                row["precision"] = round(
                    float(
                        precision_list[
                            metric_index
                        ]
                    ),
                    6,
                )

            if metric_index < len(
                recall_list
            ):
                row["recall"] = round(
                    float(
                        recall_list[
                            metric_index
                        ]
                    ),
                    6,
                )

            if metric_index < len(
                f1_list
            ):
                row["f1"] = round(
                    float(
                        f1_list[
                            metric_index
                        ]
                    ),
                    6,
                )

            if class_id < len(
                maps_list
            ):
                row["mAP50_95"] = round(
                    float(
                        maps_list[
                            class_id
                        ]
                    ),
                    6,
                )

            per_class[class_name] = row

        return per_class

    # --------------------------------------------------------
    # Fallback: assume arrays are indexed by class ID.
    # --------------------------------------------------------

    max_classes = max(
        len(precision_list),
        len(recall_list),
        len(f1_list),
        len(maps_list),
        len(class_names),
    )

    for class_id in range(
        max_classes
    ):

        class_name = class_names.get(
            class_id,
            f"class_{class_id}",
        )

        row = {}

        if class_id < len(
            precision_list
        ):
            row["precision"] = round(
                float(
                    precision_list[
                        class_id
                    ]
                ),
                6,
            )

        if class_id < len(
            recall_list
        ):
            row["recall"] = round(
                float(
                    recall_list[
                        class_id
                    ]
                ),
                6,
            )

        if class_id < len(
            f1_list
        ):
            row["f1"] = round(
                float(
                    f1_list[
                        class_id
                    ]
                ),
                6,
            )

        if class_id < len(
            maps_list
        ):
            row["mAP50_95"] = round(
                float(
                    maps_list[
                        class_id
                    ]
                ),
                6,
            )

        per_class[class_name] = row

    return per_class


def run_phase2_evaluation(
    model: YOLO,
    class_names: dict[int, str],
    dataset_config: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:

    print("\n")
    print("=" * 80)
    print("PHASE 2 — LABELED TEST-SET EVALUATION")
    print("=" * 80)

    EVALUATION_OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        f"Dataset YAML : {DATA_YAML}"
    )

    print(
        "Evaluation split: TEST"
    )

    print(
        "This uses ground-truth labels and calculates "
        "P / R / mAP metrics."
    )

    # --------------------------------------------------------
    # Run true evaluation against TEST split
    # --------------------------------------------------------

    start = time.perf_counter()

    metrics = model.val(
        data=str(DATA_YAML),
        split="test",
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        plots=True,
        project=str(OUTPUT_ROOT),
        name="evaluation",
        exist_ok=True,
        verbose=True,
    )

    evaluation_time = (
        time.perf_counter()
        - start
    )

    # --------------------------------------------------------
    # Overall metrics
    # --------------------------------------------------------

    box_metrics = getattr(
        metrics,
        "box",
        None,
    )

    overall = {}

    if box_metrics is not None:

        overall = {
            "precision": round(
                float(
                    getattr(
                        box_metrics,
                        "mp",
                        0.0,
                    )
                ),
                6,
            ),
            "recall": round(
                float(
                    getattr(
                        box_metrics,
                        "mr",
                        0.0,
                    )
                ),
                6,
            ),
            "mAP50": round(
                float(
                    getattr(
                        box_metrics,
                        "map50",
                        0.0,
                    )
                ),
                6,
            ),
            "mAP50_95": round(
                float(
                    getattr(
                        box_metrics,
                        "map",
                        0.0,
                    )
                ),
                6,
            ),
        }

    # --------------------------------------------------------
    # Results dictionary where available
    # --------------------------------------------------------

    result_dict = {}

    try:
        result_dict = dict(
            metrics.results_dict
        )
    except Exception:
        result_dict = {}

    # --------------------------------------------------------
    # Per-class
    # --------------------------------------------------------

    per_class = extract_per_class_metrics(
        metrics,
        class_names,
    )

    # --------------------------------------------------------
    # Evaluation speed
    # --------------------------------------------------------

    speed = getattr(
        metrics,
        "speed",
        {},
    )

    evaluation_speed = {
        "preprocess_ms_per_image": safe_float(
            speed.get(
                "preprocess",
                0.0,
            )
        ),
        "inference_ms_per_image": safe_float(
            speed.get(
                "inference",
                0.0,
            )
        ),
        "loss_ms_per_image": safe_float(
            speed.get(
                "loss",
                0.0,
            )
        ),
        "postprocess_ms_per_image": safe_float(
            speed.get(
                "postprocess",
                0.0,
            )
        ),
    }

    # --------------------------------------------------------
    # Confusion matrix / plots
    # --------------------------------------------------------

    likely_outputs = [
        "confusion_matrix.png",
        "confusion_matrix_normalized.png",
        "BoxPR_curve.png",
        "BoxP_curve.png",
        "BoxR_curve.png",
        "BoxF1_curve.png",
    ]

    existing_outputs = []

    for filename in likely_outputs:

        path = (
            EVALUATION_OUTPUT_DIR
            / filename
        )

        if path.exists():
            existing_outputs.append(
                str(path)
            )

    # --------------------------------------------------------
    # Final evaluation object
    # --------------------------------------------------------

    evaluation = {
        "phase": "phase_2_test_evaluation",
        "model": str(MODEL_PATH),
        "dataset_yaml": str(DATA_YAML),
        "test_images_directory": str(
            TEST_IMAGES_DIR
        ),
        "test_labels_directory": str(
            TEST_LABELS_DIR
        ),
        "configuration": {
            "image_size": args.imgsz,
            "batch": args.batch,
            "device": args.device,
            "workers": args.workers,
        },
        "overall_metrics": overall,
        "per_class_metrics": per_class,
        "ultralytics_results_dict": result_dict,
        "speed": evaluation_speed,
        "evaluation_time_seconds": round(
            evaluation_time,
            3,
        ),
        "plots_found": existing_outputs,
        "dataset_config": dataset_config,
    }

    summary_path = (
        EVALUATION_OUTPUT_DIR
        / "evaluation_summary.json"
    )

    save_json(
        summary_path,
        evaluation,
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    print("\n" + "-" * 80)
    print("PHASE 2 RESULTS")
    print("-" * 80)

    print(
        f"Precision      : "
        f"{overall.get('precision', 0.0) * 100:.2f}%"
    )

    print(
        f"Recall         : "
        f"{overall.get('recall', 0.0) * 100:.2f}%"
    )

    print(
        f"mAP50          : "
        f"{overall.get('mAP50', 0.0) * 100:.2f}%"
    )

    print(
        f"mAP50-95       : "
        f"{overall.get('mAP50_95', 0.0) * 100:.2f}%"
    )

    if per_class:

        print("\nPer-class metrics:")

        print(
            f"{'Class':<20}"
            f"{'Precision':>12}"
            f"{'Recall':>12}"
            f"{'F1':>12}"
            f"{'mAP50-95':>14}"
        )

        print("-" * 70)

        for class_name, values in (
            per_class.items()
        ):

            p = values.get(
                "precision"
            )

            r = values.get(
                "recall"
            )

            f1_value = values.get(
                "f1"
            )

            map_value = values.get(
                "mAP50_95"
            )

            print(
                f"{class_name:<20}"
                f"{(p * 100 if p is not None else 0):>11.2f}%"
                f"{(r * 100 if r is not None else 0):>11.2f}%"
                f"{(f1_value * 100 if f1_value is not None else 0):>11.2f}%"
                f"{(map_value * 100 if map_value is not None else 0):>13.2f}%"
            )

    print("\nEvaluation speed:")

    for key, value in evaluation_speed.items():

        if value is not None:
            print(
                f"  {key:<32}: "
                f"{value:.3f} ms"
            )

    print(
        f"\nEvaluation outputs:"
    )

    print(
        f"  Directory       : "
        f"{EVALUATION_OUTPUT_DIR}"
    )

    print(
        f"  Summary         : "
        f"{summary_path}"
    )

    print("=" * 80)

    return evaluation


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    args = parse_args()

    print("=" * 80)
    print("FSOC SIMULATOR — BEACON / TARGET MODEL TEST")
    print("=" * 80)

    # --------------------------------------------------------
    # Argument validation
    # --------------------------------------------------------

    if not 0.0 < args.conf <= 1.0:
        raise ValueError(
            "--conf must be > 0 and <= 1"
        )

    if not 0.0 < args.iou <= 1.0:
        raise ValueError(
            "--iou must be > 0 and <= 1"
        )

    if args.imgsz <= 0:
        raise ValueError(
            "--imgsz must be > 0"
        )

    # --------------------------------------------------------
    # Paths
    # --------------------------------------------------------

    print("\nProject:")
    print(
        f"  Project directory : {PROJECT_DIR}"
    )

    print(
        f"  Model             : {MODEL_PATH}"
    )

    print(
        f"  Test images       : {TEST_IMAGES_DIR}"
    )

    print(
        f"  Test labels       : {TEST_LABELS_DIR}"
    )

    print(
        f"  Dataset YAML       : {DATA_YAML}"
    )

    # --------------------------------------------------------
    # Check required files
    # --------------------------------------------------------

    ensure_exists(
        MODEL_PATH,
        "Trained best.pt model",
    )

    ensure_exists(
        TEST_IMAGES_DIR,
        "Test images directory",
    )

    ensure_exists(
        DATA_YAML,
        "Dataset YAML",
    )

    # --------------------------------------------------------
    # Load YAML/class information
    # --------------------------------------------------------

    dataset_config = (
        load_dataset_yaml()
    )

    yaml_class_names = get_class_names(
        dataset_config
    )

    # --------------------------------------------------------
    # Load model
    # --------------------------------------------------------

    print("\nLoading model...")

    model = YOLO(
        str(MODEL_PATH)
    )

    try:
        model_class_names = {
            int(k): str(v)
            for k, v in model.names.items()
        }
    except Exception:
        model_class_names = {}

    # Prefer model class names if available.
    class_names = (
        model_class_names
        if model_class_names
        else yaml_class_names
    )

    print(
        "Model loaded successfully."
    )

    print("\nClasses:")

    for class_id, class_name in sorted(
        class_names.items()
    ):
        print(
            f"  {class_id}: {class_name}"
        )

    # --------------------------------------------------------
    # Environment
    # --------------------------------------------------------

    environment = (
        collect_environment_info(
            model,
            args,
        )
    )

    save_json(
        OUTPUT_ROOT
        / "environment.json",
        environment,
    )

    # --------------------------------------------------------
    # Find images
    # --------------------------------------------------------

    test_images = find_images(
        TEST_IMAGES_DIR
    )

    print(
        f"\nTest images found: "
        f"{len(test_images)}"
    )

    if not test_images:
        raise RuntimeError(
            "No supported test images were found."
        )

    # --------------------------------------------------------
    # Dataset audit
    # --------------------------------------------------------

    print("\nChecking test dataset...")

    audit = audit_test_dataset(
        class_names
    )

    audit_path = (
        OUTPUT_ROOT
        / "dataset_audit.json"
    )

    save_json(
        audit_path,
        audit,
    )

    print(
        f"  Images                 : "
        f"{audit['image_count']}"
    )

    print(
        f"  Label files            : "
        f"{audit['label_file_count']}"
    )

    print(
        f"  Ground-truth instances : "
        f"{audit['total_annotation_objects']}"
    )

    print(
        f"  Empty labels           : "
        f"{audit['background_images_with_empty_labels']}"
    )

    print(
        f"  Images without labels  : "
        f"{audit['images_without_labels']}"
    )

    print(
        f"  Orphan labels          : "
        f"{audit['labels_without_images']}"
    )

    print(
        f"  Invalid label errors   : "
        f"{audit['invalid_label_error_count']}"
    )

    if audit["dataset_integrity_pass"]:
        print(
            "  Dataset integrity      : PASS"
        )
    else:
        print(
            "  Dataset integrity      : WARNING"
        )

        print(
            "\nSee:"
        )

        print(
            f"  {audit_path}"
        )

    # --------------------------------------------------------
    # Outputs
    # --------------------------------------------------------

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Phase 1
    # --------------------------------------------------------

    phase1_summary = None

    if args.mode in {
        "all",
        "inference",
    }:

        phase1_summary = (
            run_phase1_inference(
                model=model,
                test_images=test_images,
                class_names=class_names,
                args=args,
            )
        )

        run_speed_benchmark(
            model=model,
            test_images=test_images,
            args=args,
        )

    # --------------------------------------------------------
    # Phase 2
    # --------------------------------------------------------

    phase2_summary = None

    if args.mode in {
        "all",
        "evaluate",
    }:

        phase2_summary = (
            run_phase2_evaluation(
                model=model,
                class_names=class_names,
                dataset_config=dataset_config,
                args=args,
            )
        )

    # --------------------------------------------------------
    # Final combined summary
    # --------------------------------------------------------

    combined = {
        "timestamp": datetime.now().isoformat(),
        "model": str(MODEL_PATH),
        "mode": args.mode,
        "environment": environment,
        "dataset_audit": audit,
        "phase_1_inference": phase1_summary,
        "phase_2_test_evaluation": phase2_summary,
    }

    combined_path = (
        OUTPUT_ROOT
        / "test_summary.json"
    )

    save_json(
        combined_path,
        combined,
    )

    # --------------------------------------------------------
    # Final message
    # --------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("TESTING COMPLETED")
    print("=" * 80)

    print(
        f"\nMain report:"
    )

    print(
        f"  {combined_path}"
    )

    print(
        "\nOutput directory:"
    )

    print(
        f"  {OUTPUT_ROOT}"
    )

    if args.mode in {
        "all",
        "inference",
    }:
        print(
            "\nPhase 1:"
        )
        print(
            f"  {INFERENCE_OUTPUT_DIR}"
        )

    if args.mode in {
        "all",
        "evaluate",
    }:
        print(
            "\nPhase 2:"
        )
        print(
            f"  {EVALUATION_OUTPUT_DIR}"
        )

    print(
        "\nNext step: compare the final test metrics "
        "with the Fast-profile validation metrics "
        "and inspect the Beacon/Target predictions."
    )


if __name__ == "__main__":
    main()