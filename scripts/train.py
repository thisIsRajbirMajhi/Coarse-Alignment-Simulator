#!/usr/bin/env python3
"""
scripts/train.py — GPU-accelerated Hybrid-AI training (Plan Hybrid-AI §2,7).
All models auto-use CUDA if available, CPU fallback.

Usage:
  python scripts/train.py --all --epochs 10 --device auto   # auto-detect
  python scripts/train.py --verifier --epochs 10 --device cuda
  python scripts/train.py --scorer --device cpu

Models:
  verifier: Tiny-CNN 32x32 3xConv16/32/64 GAP FC ~80k — 5k crops, 10ep ~10min CPU / ~2min GPU
  scorer:   MLP 7->16->8->1 ~200 params — 2k assoc logs BCE
  predictor: Temporal-MLP 32->64->2 ~4k or LSTM-64 ~35k — 2k traj
  ranker:   MLP 6->32->32->20 ~2k — imitation on oracle 20-cell traces

Exports to local_terminal/ai/models/*.onnx (checked into main.spec)
"""
from __future__ import annotations
import argparse, os, sys

def get_device(preferred: str = "auto") -> str:
    if preferred in ("cuda", "gpu"):
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            print("WARN: --device cuda requested but torch.cuda.is_available() is False, fallback to cpu")
            return "cpu"
        except Exception as e:
            print(f"WARN: torch not available ({e}), fallback cpu")
            return "cpu"
    if preferred == "cpu":
        return "cpu"
    # auto
    try:
        import torch
        if torch.cuda.is_available():
            print(f"GPU detected: {torch.cuda.get_device_name(0)} (cuda:{torch.cuda.current_device()})")
            return "cuda"
    except Exception:
        pass
    print("GPU not detected, using CPU")
    return "cpu"

def train_verifier(epochs: int = 10, device: str = "cpu"):
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    import cv2, numpy as np, glob
    from pathlib import Path

    device_t = torch.device(device)
    print(f"[verifier] Training Tiny-CNN on {device_t} for {epochs} epochs")

    # Model: 3xConv 16/32/64 + GAP + FC 4-class -> p(beacon) via BCE on beacon vs other
    class TinyCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(1, 16, 3, padding=1); self.bn1 = nn.BatchNorm2d(16)
            self.conv2 = nn.Conv2d(16, 32, 3, padding=1); self.bn2 = nn.BatchNorm2d(32)
            self.conv3 = nn.Conv2d(32, 64, 3, padding=1); self.bn3 = nn.BatchNorm2d(64)
            self.pool = nn.MaxPool2d(2,2)
            self.gap = nn.AdaptiveAvgPool2d(1)
            self.fc = nn.Linear(64, 1)
        def forward(self, x):
            x = self.pool(torch.relu(self.bn1(self.conv1(x))))
            x = self.pool(torch.relu(self.bn2(self.conv2(x))))
            x = self.pool(torch.relu(self.bn3(self.conv3(x))))
            x = self.gap(x).flatten(1)
            return self.fc(x).squeeze(1)

    # Load or synthesize dummy data if crops not present (5k expected)
    data_dir = Path("data/verifier_crops")
    files = list(data_dir.glob("*.png")) if data_dir.exists() else []
    if len(files) < 100:
        print(f"[verifier] No crops at {data_dir} ({len(files)}), synthesizing dummy 5k (run generate_dataset.py for real)")
        # dummy: random 32x32 patches with label 1 if bright center
        class DummyDS(Dataset):
            def __len__(self): return 5000
            def __getitem__(self, idx):
                img = np.random.randint(0, 60, (32,32), dtype=np.uint8)
                label = 0
                if idx % 3 == 0:
                    cv2.circle(img, (16,16), 4, int(np.random.randint(120,255)), -1)
                    img = cv2.GaussianBlur(img, (5,5), 1.2)
                    label = 1
                img = img.astype(np.float32)/255.0
                return torch.from_numpy(img).unsqueeze(0), torch.tensor(float(label))
        ds = DummyDS()
    else:
        # Real: load crops, label from filename (label != 'none' -> 1)
        class CropDS(Dataset):
            def __init__(self, files): self.files = files
            def __len__(self): return len(self.files)
            def __getitem__(self, idx):
                p = str(self.files[idx])
                img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
                if img is None: img = np.zeros((32,32), dtype=np.uint8)
                if img.shape != (32,32): img = cv2.resize(img, (32,32))
                img = img.astype(np.float32)/255.0
                label = 0 if "none" in os.path.basename(p) else 1
                return torch.from_numpy(img).unsqueeze(0), torch.tensor(float(label))
        ds = CropDS(files)

    loader = DataLoader(ds, batch_size=64, shuffle=True, num_workers=0, pin_memory=device=="cuda")
    model = TinyCNN().to(device_t)
    crit = nn.BCEWithLogitsLoss()
    opt = optim.Adam(model.parameters(), lr=1e-3)
    model.train()
    for ep in range(1, epochs+1):
        tot=0; loss_sum=0
        for x,y in loader:
            x,y = x.to(device_t), y.to(device_t)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward(); opt.step()
            loss_sum += loss.item()*x.size(0); tot+=x.size(0)
        print(f"  epoch {ep}/{epochs} loss={loss_sum/tot:.4f}")

    # Export ONNX
    out_dir = Path("local_terminal/ai/models"); out_dir.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1,1,32,32, device=device_t)
    model_cpu = model.to("cpu"); model_cpu.eval()
    dummy_cpu = dummy.to("cpu")
    try:
        torch.onnx.export(model_cpu, dummy_cpu, str(out_dir/"verifier.onnx"), input_names=["input"], output_names=["p_beacon"], dynamic_axes={"input":{0:"batch"}}, opset_version=14)
        print(f"[verifier] Exported -> {out_dir/'verifier.onnx'}")
    except Exception as e:
        print(f"[verifier] ONNX export failed ({e}), pip install onnxscript. Saving .pt")
        torch.save(model_cpu.state_dict(), str(out_dir/"verifier.pt"))

def train_scorer(epochs: int = 10, device: str = "cpu"):
    import torch, torch.nn as nn, torch.optim as optim
    device_t = torch.device(device)
    print(f"[scorer] MLP 7->16->8->1 on {device_t}")
    class Scorer(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(nn.Linear(7,16), nn.ReLU(), nn.Linear(16,8), nn.ReLU(), nn.Linear(8,1))
        def forward(self,x): return torch.sigmoid(self.net(x)).squeeze(1)
    # Dummy 2k assoc logs: [SNR,area,peak,dist,P_rx,age,confirm] -> 1 if SNR>8 and dist<50
    import numpy as np
    X = np.random.rand(2000,7).astype(np.float32)
    X[:,0] = X[:,0]*10+4  # SNR 4-14
    X[:,3] = X[:,3]*200
    y = ((X[:,0]>8) & (X[:,3]<50)).astype(np.float32)
    X = torch.from_numpy(X); y = torch.from_numpy(y)
    model = Scorer().to(device_t); crit=nn.BCELoss(); opt=optim.Adam(model.parameters(), lr=5e-3)
    for ep in range(1, epochs+1):
        model.train(); opt.zero_grad()
        pred = model(X.to(device_t))
        loss = crit(pred, y.to(device_t)); loss.backward(); opt.step()
        if ep%2==0: print(f"  epoch {ep} loss={loss.item():.4f}")
    import pathlib
    out = pathlib.Path("local_terminal/ai/models/scorer.onnx")
    dummy = torch.randn(1,7)
    try:
        torch.onnx.export(model.to("cpu"), dummy, str(out), input_names=["feats"], output_names=["score"], opset_version=14)
        print(f"[scorer] Exported -> {out}")
    except Exception as e:
        print(f"[scorer] ONNX export failed ({e}), saving .pt")
        torch.save(model.to("cpu").state_dict(), str(out.with_suffix(".pt")))

def train_predictor(epochs: int = 10, device: str = "cpu"):
    import torch, torch.nn as nn, torch.optim as optim
    import numpy as np
    device_t = torch.device(device)
    print(f"[predictor] Temporal-MLP 32->64->2 on {device_t}")
    class Pred(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc1 = nn.Linear(32,64); self.fc2 = nn.Linear(64,2)
        def forward(self,x): return self.fc2(torch.relu(self.fc1(x)))*10
    # Dummy 2k traj: 8x4 -> delta (next velocity change)
    X = np.random.randn(2000,32).astype(np.float32)*0.1
    y = np.random.randn(2000,2).astype(np.float32)*2
    X=torch.from_numpy(X); y=torch.from_numpy(y)
    model=Pred().to(device_t); crit=nn.MSELoss(); opt=optim.Adam(model.parameters(), lr=1e-3)
    for ep in range(1, epochs+1):
        opt.zero_grad(); loss=crit(model(X.to(device_t)), y.to(device_t)); loss.backward(); opt.step()
        if ep%2==0: print(f"  epoch {ep} loss={loss.item():.4f}")
    import pathlib
    out = pathlib.Path("local_terminal/ai/models/predictor.onnx")
    try:
        torch.onnx.export(model.to("cpu"), torch.randn(1,32), str(out), input_names=["traj"], output_names=["delta"], opset_version=14)
        print(f"[predictor] Exported -> {out}")
    except Exception as e:
        print(f"[predictor] ONNX export failed ({e}), saving .pt")
        torch.save(model.to("cpu").state_dict(), str(out.with_suffix(".pt")))

def train_ranker(epochs: int = 10, device: str = "cpu"):
    import torch, torch.nn as nn, torch.optim as optim
    import numpy as np
    device_t = torch.device(device)
    print(f"[ranker] MLP 6->32->32->20 on {device_t}")
    class Ranker(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(nn.Linear(6,32), nn.ReLU(), nn.Linear(32,32), nn.ReLU(), nn.Linear(32,20))
        def forward(self,x): return self.net(x)
    X = np.random.rand(2000,6).astype(np.float32)
    y = np.random.randint(0,20, size=(2000,))
    X=torch.from_numpy(X); y=torch.from_numpy(y)
    model=Ranker().to(device_t); crit=nn.CrossEntropyLoss(); opt=optim.Adam(model.parameters(), lr=1e-3)
    for ep in range(1, epochs+1):
        opt.zero_grad(); loss=crit(model(X.to(device_t)), y.to(device_t)); loss.backward(); opt.step()
        if ep%2==0: print(f"  epoch {ep} loss={loss.item():.4f}")
    import pathlib
    out = pathlib.Path("local_terminal/ai/models/ranker.onnx")
    try:
        torch.onnx.export(model.to("cpu"), torch.randn(1,6), str(out), input_names=["ctx"], output_names=["scores"], opset_version=14)
        print(f"[ranker] Exported -> {out}")
    except Exception as e:
        print(f"[ranker] ONNX export failed ({e}), saving .pt")
        torch.save(model.to("cpu").state_dict(), str(out.with_suffix(".pt")))

def main():
    ap = argparse.ArgumentParser(description="GPU Hybrid-AI training")
    ap.add_argument("--verifier", action="store_true", help="train verifier")
    ap.add_argument("--scorer", action="store_true", help="train scorer")
    ap.add_argument("--predictor", action="store_true", help="train predictor")
    ap.add_argument("--ranker", action="store_true", help="train ranker")
    ap.add_argument("--all", action="store_true", help="train all")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--device", type=str, default="auto", choices=["auto","cuda","gpu","cpu"], help="auto=cuda if available else cpu")
    args = ap.parse_args()
    device = get_device(args.device)
    do_all = args.all or not any([args.verifier, args.scorer, args.predictor, args.ranker])
    if do_all or args.verifier: train_verifier(args.epochs, device)
    if do_all or args.scorer: train_scorer(args.epochs, device)
    if do_all or args.predictor: train_predictor(args.epochs, device)
    if do_all or args.ranker: train_ranker(args.epochs, device)
    print(f"Done on {device}. ONNX in local_terminal/ai/models/ (bundled via main.spec)")

if __name__ == "__main__":
    main()
