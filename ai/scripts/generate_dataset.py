#!/usr/bin/env python3
"""ai/scripts/generate_dataset.py - Synthetic patch dataset from simulator.

Generates 32x32 (or 64x64) patches for TinyCNN verifier training:
  classes: beacon / noise / distractor / clipped / lowlight / blur
Scenario-level split: all patches from same scenario (seed) go to same split
  to avoid leakage. Produces manifests + labels_schema.json references.

Stub: no torch required. Uses numpy + cv2 only. Real beacon rendering can be
swapped to simulator imports when available.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

try:
    import cv2  # noqa: F401
except Exception:
    cv2 = None  # type: ignore

LABELS_SCHEMA = {
    "classes": ["beacon", "noise", "distractor", "clipped", "lowlight", "blur"],
    "class_to_idx": {"beacon": 0, "noise": 1, "distractor": 2, "clipped": 3, "lowlight": 4, "blur": 5},
    "input_size": [32, 32],
    "alt_size": [64, 64],
    "output": {"p_beacon": "float 0..1", "p_noise_optional": "1-p_beacon", "p_distractor_optional": "1-p_beacon"},
    "notes": "Scenario-level split: scenario_id derived from seed/scenario; all patches of one scenario in single split."
}

DEFAULT_WEIGHTS = {"ai": 0.35, "shape": 0.10, "brightness": 0.15, "motion": 0.20, "prediction": 0.20}


def _synthetic_patch(cls: str, size: int = 32) -> np.ndarray:
    rng = np.random.default_rng()
    bg = rng.integers(8, 18, size=(size, size), dtype=np.uint8)
    if cls == "beacon":
        # Gaussian spot at center, sigma 2-3
        sigma = float(rng.uniform(1.8, 3.0))
        peak = int(rng.integers(90, 220))
        ys, xs = np.mgrid[0:size, 0:size]
        cx = cy = size // 2 + int(rng.integers(-2, 3))
        g = np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma * sigma))
        patch = bg.astype(float) + g * peak
        noise = rng.normal(0, 3, size=(size, size))
        patch = np.clip(patch + noise, 0, 255).astype(np.uint8)
        return patch
    elif cls == "noise":
        patch = rng.integers(0, 40, size=(size, size), dtype=np.uint8)
        # add uniform noise
        return np.clip(bg.astype(int) + rng.integers(-8, 8, size=(size, size)), 0, 255).astype(np.uint8)
    elif cls == "distractor":
        # star-like: single hot pixel or small tight peak (hot pixel discriminator)
        patch = bg.copy()
        x = int(rng.integers(4, size - 4)); y = int(rng.integers(4, size - 4))
        patch[y, x] = int(rng.integers(180, 255))
        if rng.random() < 0.5:
            patch[max(0,y-1):y+2, max(0,x-1):x+2] = np.clip(patch[max(0,y-1):y+2, max(0,x-1):x+2].astype(int) + 30, 0, 255)
        return patch
    elif cls == "clipped":
        p = _synthetic_patch("beacon", size)
        # saturate/clip
        return np.clip(p.astype(int) + 80, 0, 255).astype(np.uint8)
    elif cls == "lowlight":
        p = _synthetic_patch("beacon", size)
        # dim beacon
        return (p.astype(float) * 0.45 + rng.normal(0, 2, size=(size, size))).clip(0,255).astype(np.uint8)
    elif cls == "blur":
        p = _synthetic_patch("beacon", size)
        if cv2 is not None:
            k = int(rng.choice([5, 7]))
            p = cv2.GaussianBlur(p, (k, k), sigmaX=2.5)
        return p
    else:
        return bg


def scenario_id_for(seed: int, scenario: int) -> str:
    h = hashlib.md5(f"{seed}:{scenario}".encode()).hexdigest()[:8]
    return f"scn_{scenario:03d}_seed{seed}_{h}"


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic TinyCNN patch dataset with scenario-level split")
    ap.add_argument("--out", type=str, default="data/ai_dataset", help="output root (manifests + patches)")
    ap.add_argument("--size", type=int, default=32, choices=[32, 64], help="patch size (32 or 64 per spec)")
    ap.add_argument("--per-class", type=int, default=500, help="patches per class per split approx")
    ap.add_argument("--scenarios", type=int, default=30, help="number of scenario ids to split across")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--splits", type=str, default="0.7,0.15,0.15", help="train,val,test fractions")
    args = ap.parse_args()
    random.seed(args.seed); np.random.seed(args.seed)
    fracs = [float(x) for x in args.splits.split(",")]
    assert len(fracs)==3 and abs(sum(fracs)-1.0) < 1e-6, "splits must sum to 1"
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    # scenario-level split
    n_sc = int(args.scenarios)
    ids = list(range(n_sc))
    random.shuffle(ids)
    n_train = int(round(fracs[0]*n_sc)); n_val = int(round(fracs[1]*n_sc))
    train_ids = set(ids[:n_train]); val_ids = set(ids[n_train:n_train+n_val]); test_ids = set(ids[n_train+n_val:])
    # write labels_schema.json reference
    (out / "labels_schema.json").write_text(json.dumps(LABELS_SCHEMA, indent=2))
    # generate
    classes = LABELS_SCHEMA["classes"]
    manifests = {"train": [], "val": [], "test": []}
    for cls in classes:
        for scn in range(n_sc):
            if scn in train_ids: split="train"
            elif scn in val_ids: split="val"
            else: split="test"
            # ~ per-class / n_sc per scenario, at least 2
            cnt = max(2, int(args.per_class / max(1, len([s for s in range(n_sc) if (s in train_ids if split=="train" else s in val_ids if split=="val" else s in test_ids)]))))
            for i in range(cnt):
                patch = _synthetic_patch(cls, size=int(args.size))
                sid = scenario_id_for(args.seed, scn)
                fname = f"{cls}_{sid}_{i:04d}.png"
                split_dir = out / split / cls
                split_dir.mkdir(parents=True, exist_ok=True)
                fpath = split_dir / fname
                if cv2 is not None:
                    cv2.imwrite(str(fpath), patch)
                else:
                    # fallback npy
                    np.save(str(fpath.with_suffix(".npy")), patch)
                    fpath = fpath.with_suffix(".npy")
                rel = str(Path(split) / cls / fname)
                manifests[split].append({"path": rel, "label": cls, "label_idx": LABELS_SCHEMA["class_to_idx"][cls],
                                         "scenario_id": sid, "size": int(args.size)})
    for k in manifests:
        (out / f"manifest_{k}.json").write_text(json.dumps({"split": k, "count": len(manifests[k]), "items": manifests[k][:20],
                                                            "note": "first 20 items preview; full list in manifest_{split}_full.jsonl",
                                                            "labels_schema": "labels_schema.json",
                                                            "confidence_fusion_weights": DEFAULT_WEIGHTS}, indent=2))
        # full jsonl
        with open(out / f"manifest_{k}_full.jsonl", "w") as f:
            for it in manifests[k]:
                f.write(json.dumps(it)+"\n")
    print(f"Done. out={out} train={len(manifests['train'])} val={len(manifests['val'])} test={len(manifests['test'])}")
    print(f"labels_schema: {out/'labels_schema.json'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
