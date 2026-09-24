#!/usr/bin/env python3
"""ai/scripts/clean_dataset.py - Clean / deduplicate / validate dataset manifests."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from collections import Counter

def main():
    ap = argparse.ArgumentParser(description="Validate and clean manifests (dedup, check labels_schema)")
    ap.add_argument("--data", type=str, default="data/ai_dataset", help="dataset root with manifest_*.json")
    ap.add_argument("--fix", action="store_true", help="rewrite manifests deduped")
    args = ap.parse_args()
    root = Path(args.data)
    schema = root / "labels_schema.json"
    if schema.exists():
        print(f"labels_schema: {schema} -> {json.loads(schema.read_text()).get('classes')}")
    else:
        print(f"WARN: missing {schema}")
    for split in ("train","val","test"):
        p = root / f"manifest_{split}_full.jsonl"
        if not p.exists():
            p = root / f"manifest_{split}.json"
            if not p.exists():
                print(f"skip {split}: no manifest")
                continue
            data = json.loads(p.read_text()).get("items", [])
        else:
            data = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        print(f"{split}: {len(data)} items, labels={Counter(d.get('label') for d in data)}")
        # scenario-level leakage check
        scenario_counts = Counter(d.get("scenario_id") for d in data)
        print(f"  scenarios: {len(scenario_counts)} unique")
        # dedup by path
        seen=set(); deduped=[]
        for d in data:
            k=d.get("path")
            if k not in seen:
                seen.add(k); deduped.append(d)
        if len(deduped)!=len(data):
            print(f"  dedup removed {len(data)-len(deduped)}")
            if args.fix:
                out = root / f"manifest_{split}_full.jsonl"
                with open(out,"w") as f:
                    for it in deduped:
                        f.write(json.dumps(it)+"\n")
                print(f"  rewrote {out}")
    # cross-split leakage: same scenario_id should not appear in multiple splits
    all_by_scenario={}
    for split in ("train","val","test"):
        p = root / f"manifest_{split}_full.jsonl"
        if not p.exists(): continue
        for line in p.read_text().splitlines():
            if not line.strip(): continue
            d=json.loads(line)
            sid=d.get("scenario_id")
            all_by_scenario.setdefault(sid,set()).add(split)
    leaking=[sid for sid,ss in all_by_scenario.items() if len(ss)>1]
    if leaking:
        print(f"ERROR: scenario-level leakage {leaking[:10]} (total {len(leaking)})")
        return 2
    else:
        print("OK: no scenario-level leakage (scenario_id isolated per split)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
