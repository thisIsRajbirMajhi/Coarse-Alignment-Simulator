"""Visualize YOLO labels by drawing boxes on dataset images.

Import-safe: importing this module has no side effects. Use the CLI:

    python scripts/visualize_labels.py --split train --max-images 20
    python scripts/visualize_labels.py --split val --random --seed 0
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2

# Backwards-compatible defaults (previously module-level constants).
# Prefer the CLI flags; these remain so existing imports keep working.
DATASET = Path("dataset")
SPLIT = "train"
MAX_IMAGES: int | None = 20

IMAGE_EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
CLASS_ID = 0
CLASS_NAME = "beacon"


def _collect_images(image_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in IMAGE_EXTENSIONS:
        paths.extend(image_dir.glob(pattern))
    # De-duplicate (e.g. case variants) and sort for determinism.
    return sorted({p for p in paths if p.is_file()})


def _parse_label_line(line: str, label_name: str, lineno: int) -> tuple[int, float, float, float, float] | None:
    parts = line.split()
    if len(parts) != 5:
        print(f"[WARNING] Invalid label format at {label_name}:{lineno}: expected 5 values")
        return None
    try:
        class_id = int(parts[0])
    except ValueError:
        print(f"[WARNING] Non-integer class id at {label_name}:{lineno}: {parts[0]!r}")
        return None
    try:
        xc, yc, w, h = (float(v) for v in parts[1:])
    except ValueError:
        print(f"[WARNING] Invalid numeric values at {label_name}:{lineno}")
        return None
    if class_id != CLASS_ID:
        print(f"[WARNING] Unexpected class {class_id} at {label_name}:{lineno} "
              f"(expected {CLASS_ID}={CLASS_NAME})")
        return None
    if not all(0.0 <= v <= 1.0 for v in (xc, yc, w, h)):
        print(f"[WARNING] Out-of-range box at {label_name}:{lineno}: {line.strip()!r}")
        return None
    if w <= 0.0 or h <= 0.0:
        print(f"[WARNING] Zero-size box at {label_name}:{lineno}")
        return None
    return class_id, xc, yc, w, h


def _draw_label_banner(image, text: str, org=(10, 25)) -> None:
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    x, y = org
    cv2.rectangle(image, (x - 4, y - th - 8), (x + tw + 4, y + 6), (0, 0, 0), -1)
    cv2.putText(image, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


def visualize_split(
    dataset: Path = DATASET,
    split: str = SPLIT,
    output: Path | None = None,
    max_images: int | None = MAX_IMAGES,
    use_random: bool = False,
    seed: int = 42,
) -> dict:
    image_dir = dataset / "images" / split
    label_dir = dataset / "labels" / split
    output_dir = output if output is not None else dataset / "visualized" / split
    output_dir.mkdir(parents=True, exist_ok=True)

    image_paths = _collect_images(image_dir)
    if use_random:
        rng = random.Random(seed)
        rng.shuffle(image_paths)
    if max_images is not None and max_images >= 0:
        image_paths = image_paths[:max_images]

    if not image_paths:
        raise FileNotFoundError(f"No images {IMAGE_EXTENSIONS} found in: {image_dir}")

    processed = 0
    total_boxes = 0
    background = 0
    missing_labels = 0
    invalid_lines = 0

    for index, image_path in enumerate(image_paths):
        label_path = label_dir / f"{image_path.stem}.txt"
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"[WARNING] Could not read image: {image_path}")
            continue
        height, width = image.shape[:2]

        boxes: list[tuple[float, float, float, float]] = []
        if label_path.exists():
            for lineno, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = raw.strip()
                if not line:
                    continue
                parsed = _parse_label_line(line, label_path.name, lineno)
                if parsed is None:
                    invalid_lines += 1
                    continue
                _, xc, yc, w, h = parsed
                boxes.append((xc, yc, w, h))
        else:
            print(f"[WARNING] Label file missing: {label_path}")
            missing_labels += 1

        if not boxes and label_path.exists():
            background += 1

        for object_number, (xc, yc, w, h) in enumerate(boxes, start=1):
            x1 = int(xc * width - w * width / 2)
            y1 = int(yc * height - h * height / 2)
            x2 = int(xc * width + w * width / 2)
            y2 = int(yc * height + h * height / 2)
            x1 = max(0, min(x1, width - 1))
            y1 = max(0, min(y1, height - 1))
            x2 = max(0, min(x2, width - 1))
            y2 = max(0, min(y2, height - 1))
            if x2 <= x1 or y2 <= y1:
                print(f"[WARNING] Degenerate box after clamping in {label_path.name} "
                      f"(object #{object_number})")
                invalid_lines += 1
                continue

            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label_text = f"{CLASS_NAME} #{object_number}"
            text_y = y1 - 8 if y1 - 8 >= 20 else y1 + 20
            (ltw, lth), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            cv2.rectangle(image, (x1, text_y - lth - 6), (x1 + ltw + 4, text_y + 4), (0, 0, 0), -1)
            cv2.putText(image, label_text, (x1, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.circle(image, (int(xc * width), int(yc * height)), 3, (0, 255, 255), -1)
            total_boxes += 1

        _draw_label_banner(image, f"{image_path.name} | {width}x{height} | Beacons: {len(boxes)}")

        output_path = output_dir / image_path.name
        if not cv2.imwrite(str(output_path), image):
            print(f"[WARNING] Failed to save: {output_path}")
            continue
        processed += 1
        print(f"[{processed}/{len(image_paths)}] {image_path.name} -> {len(boxes)} beacon(s)")

    print()
    print("=" * 60)
    print("Visualization complete")
    print("=" * 60)
    print(f"Images processed : {processed}")
    print(f"Total boxes      : {total_boxes}")
    print(f"Background imgs  : {background}")
    print(f"Missing labels   : {missing_labels}")
    print(f"Invalid lines    : {invalid_lines}")
    print(f"Output directory : {output_dir.resolve()}")
    print("=" * 60)

    return {
        "processed": processed,
        "total_boxes": total_boxes,
        "background": background,
        "missing_labels": missing_labels,
        "invalid_lines": invalid_lines,
        "output_dir": str(output_dir),
    }


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Draw YOLO beacon boxes for quick QA")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--split", default=SPLIT, choices=["train", "val", "test"])
    parser.add_argument("--output", type=Path, default=None,
                        help="output dir (default: <dataset>/visualized/<split>)")
    parser.add_argument("--max-images", type=int, default=20 if MAX_IMAGES is None else MAX_IMAGES,
                        help="how many images to draw; use a negative value for all images")
    parser.add_argument("--random", dest="use_random", action="store_true",
                        help="shuffle images before sampling instead of taking the first N")
    parser.add_argument("--seed", type=int, default=42, help="shuffle seed with --random")
    args = parser.parse_args(argv)

    max_images = None if args.max_images is not None and args.max_images < 0 else args.max_images
    return visualize_split(
        dataset=args.dataset,
        split=args.split,
        output=args.output,
        max_images=max_images,
        use_random=args.use_random,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
