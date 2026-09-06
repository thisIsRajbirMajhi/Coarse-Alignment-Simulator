"""Remove degenerate YOLO label lines that collapse to zero area.

A line is kept only if, after the same int()+clamp projection used by
scripts/visualize_labels.py on the 640x480 frame, it still has x2>x1
and y2>y1. Also drops malformed / out-of-range / zero-size / wrong-class
lines. If a label file ends up empty, the label + image pair is deleted
so the split keeps zero background images.

Usage:
    python scripts/clean_labels.py --dataset dataset
    python scripts/clean_labels.py --dataset dataset --dry-run
    python scripts/clean_labels.py --splits train val
"""
from __future__ import annotations

import argparse
from pathlib import Path

FOV_W, FOV_H = 640, 480
CLASS_ID = 0
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
DEFAULT_SPLITS = ("train", "val", "test")


def _keep_line(parts: list[str]) -> bool:
    if len(parts) != 5:
        return False
    try:
        cls = int(parts[0])
        xc, yc, w, h = (float(v) for v in parts[1:])
    except ValueError:
        return False
    if cls != CLASS_ID:
        return False
    if not all(0.0 <= v <= 1.0 for v in (xc, yc, w, h)):
        return False
    if w <= 0.0 or h <= 0.0:
        return False
    x1 = int(xc * FOV_W - w * FOV_W / 2)
    y1 = int(yc * FOV_H - h * FOV_H / 2)
    x2 = int(xc * FOV_W + w * FOV_W / 2)
    y2 = int(yc * FOV_H + h * FOV_H / 2)
    x1 = max(0, min(x1, FOV_W - 1))
    y1 = max(0, min(y1, FOV_H - 1))
    x2 = max(0, min(x2, FOV_W - 1))
    y2 = max(0, min(y2, FOV_H - 1))
    return x2 > x1 and y2 > y1


def _find_image(image_dir: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTS:
        cand = image_dir / f"{stem}{ext}"
        if cand.is_file():
            return cand
    # Fallback: case-insensitive / any extension match.
    for cand in image_dir.glob(f"{stem}.*"):
        if cand.is_file():
            return cand
    return None


def clean_split(dataset: Path, split: str, dry_run: bool = False) -> dict:
    label_dir = dataset / "labels" / split
    image_dir = dataset / "images" / split
    label_files = sorted(label_dir.glob("*.txt"))
    removed_lines = 0
    removed_files = 0
    kept_boxes = 0

    for label_path in label_files:
        lines = label_path.read_text(encoding="utf-8").splitlines()
        keep = [ln for ln in lines if ln.strip() and _keep_line(ln.split())]
        # Count blank lines as removed (they carry no boxes).
        removed_lines += len(lines) - len(keep)
        kept_boxes += len(keep)
        if keep:
            if len(keep) != len(lines) and not dry_run:
                label_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        else:
            removed_files += 1
            if not dry_run:
                label_path.unlink(missing_ok=True)
                img = _find_image(image_dir, label_path.stem)
                if img is not None:
                    img.unlink(missing_ok=True)

    return {
        "split": split,
        "label_files": len(label_files),
        "kept_boxes": kept_boxes,
        "removed_lines": removed_lines,
        "removed_files": removed_files,
    }


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Clean degenerate YOLO label lines")
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--splits", nargs="+", default=list(DEFAULT_SPLITS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    total_lines = 0
    total_files = 0
    results = {}
    for split in args.splits:
        res = clean_split(args.dataset, split, dry_run=args.dry_run)
        results[split] = res
        total_lines += res["removed_lines"]
        total_files += res["removed_files"]
        print(f"[{split}] files={res['label_files']} kept_boxes={res['kept_boxes']} "
              f"removed_lines={res['removed_lines']} removed_pairs={res['removed_files']}")

    tag = "DRY-RUN" if args.dry_run else "DONE"
    print(f"{tag}: removed {total_lines} lines, {total_files} empty pairs.")
    return results


if __name__ == "__main__":
    main()
