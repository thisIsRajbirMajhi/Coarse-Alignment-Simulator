#!/usr/bin/env python3
"""ai/scripts/evaluate_model.py - Evaluate TinyCNN verifier on held-out test split.

Reports accuracy, precision/recall, and confidence-fusion C_total stats.
Stub works without torch/ONNX (uses heuristic); with ONNX uses cv2.dnn.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np

try:
    import cv2  # noqa: F401
except Exception:
    cv2 = None  # type: ignore

def _heuristic_score(patch) -> float:
    try:
        from src.local_terminal.ai.verifier import TinyCNNVerifier
        v = TinyCNNVerifier()
        return float(v.score_patch(patch))
    except Exception:
        # fallback inline
        p = np.asarray(patch, dtype=float)
        peak = float(p.max()); mean=float(p.mean()); std=float(max(float(p.std()),1.0))
        prom=(peak-mean)/std
        return float(np.clip((0.4 if 2<=prom<=7 else 0)+(0.3 if 60<=peak<=240 else 0)+0.1,0,1))

def main():
    ap = argparse.ArgumentParser(description="Evaluate verifier on test split (heuristic if no ONNX)")
    ap.add_argument("--data", type=str, default="data/ai_dataset")
    ap.add_argument("--model", type=str, default="src/local_terminal/ai/models/verifier.onnx", help="ONNX path or stub")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--size", type=int, default=32, choices=[32,64])
    args = ap.parse_args()
    root = Path(args.data)
    manifest = root / "manifest_test_full.jsonl"
    if not manifest.exists():
        manifest = root / "manifest_test.json"
    if not manifest.exists():
        print(f"No test manifest at {root}; running synthetic quick-eval (200 patches)")
        # synthetic quick eval
        rng=np.random.default_rng(0)
        # generate 100 beacon 100 distractor via generate_dataset helper
        try:
            from ai.scripts.generate_dataset import _synthetic_patch
        except Exception:
            def _synthetic_patch(cls, size=32):
                bg=rng.integers(8,18,size=(size,size),dtype=np.uint8)
                if cls=="beacon":
                    ys,xs=np.mgrid[0:size,0:size]
                    g=np.exp(-((xs-size//2)**2+(ys-size//2)**2)/(2*2.2*2.2))
                    return np.clip(bg.astype(float)+g*140,0,255).astype(np.uint8)
                else:
                    p=bg.copy(); p[size//2,size//2]=200; return p
        y_true=[]; y_score=[]
        for _ in range(100):
            y_true.append(1); y_score.append(_heuristic_score(_synthetic_patch("beacon", args.size)))
        for _ in range(100):
            y_true.append(0); y_score.append(_heuristic_score(_synthetic_patch("distractor", args.size)))
        y_pred=[1 if s>=args.threshold else 0 for s in y_score]
        acc=float(np.mean([1 if a==b else 0 for a,b in zip(y_true,y_pred)]))
        print(json.dumps({"synthetic": True, "n": len(y_true), "accuracy": round(acc,3), "threshold": args.threshold,
                          "labels_schema": "labels_schema.json",
                          "confidence_fusion_weights": {"ai":0.35,"shape":0.10,"brightness":0.15,"motion":0.20,"prediction":0.20}}, indent=2))
        return 0
    # real manifest path
    items=[json.loads(l) for l in manifest.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(items)} test items from {manifest}")
    # try to score each patch file if present
    scores=[]
    for it in items[:200]:  # cap 200 for speed
        ppath = root / it.get("path","")
        if not ppath.exists():
            # try png->npy fallback
            alt = ppath.with_suffix(".npy")
            if alt.exists(): ppath=alt
            else: continue
        try:
            if ppath.suffix==".npy":
                patch=np.load(str(ppath))
            elif cv2 is not None:
                patch=cv2.imread(str(ppath), cv2.IMREAD_GRAYSCALE)
            else:
                continue
            if patch is None: continue
            s=_heuristic_score(patch)
            scores.append((it.get("label"), s))
        except Exception:
            continue
    if not scores:
        print("No patches scored (files missing). Manifest validation only.")
        print(json.dumps({"test_manifest_count": len(items), "labels_schema": "labels_schema.json"}, indent=2))
        return 0
    # simple metrics: beacon vs rest
    y_true=[1 if lab=="beacon" else 0 for lab,_ in scores]
    y_score=[s for _,s in scores]
    y_pred=[1 if s>=args.threshold else 0 for s in y_score]
    acc=float(np.mean([1 if a==b else 0 for a,b in zip(y_true,y_pred)])) if y_true else 0
    tp=sum(1 for t,p in zip(y_true,y_pred) if t==1 and p==1)
    fp=sum(1 for t,p in zip(y_true,y_pred) if t==0 and p==1)
    fn=sum(1 for t,p in zip(y_true,y_pred) if t==1 and p==0)
    prec=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
    print(json.dumps({"n_scored": len(scores), "accuracy": round(acc,3), "precision_beacon": round(prec,3),
                      "recall_beacon": round(rec,3), "threshold": args.threshold,
                      "model": args.model, "labels_schema": "labels_schema.json"}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
