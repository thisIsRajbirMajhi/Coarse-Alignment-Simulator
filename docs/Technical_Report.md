# Technical Report — Hybrid-AI Coarse Alignment Simulator
*10-15 pages equivalent — Plan Hybrid-AI §10-11 compliant*

## 1. Problem
Free-space optical coarse PAT: 2000×2000 world, 640×480 4°×3° mono FOV, beacon 5-20px OOK. Requirements SR1-20 (acq≤2s, err≤10px, loss<5%, reacq≤1s, ≥20FPS). Disturbances SR21: S&P 10%, Gauss σ20, jitter ±20px, Haze/Fog, platform ±20px.

Principle: keep only pixel/SNR/TID params, demote rest to internal const (Plan §0).

## 2. Architecture
```
HeadlessSimulation → FOV → V2 FSM (supervisor.py 8-state) → PID → PTZ
scene → remote/motion/geometry/pointing/optics → camera/ptz → fov_pipeline
→ detector → TemporalConfirmer → association → tracker(KF) → selector → reacq
```
- **V2 FSM single owner** `V2_VALID_TRANSITIONS supervisor.py:41` 8 states SEARCH/IDENTIFY/ASSOCIATE/TRACK/COAST/LOST/REACQUIRE/FAULT
- **Deterministic** `common/rng.py` seed 42 → same trajectory per dt sequence.

## 3. Algorithms — Classical Core (deterministic)
- **Detector** `detector.py:27` 30ms: gray→30th pct bg → Gauss σ1.1 matched → thresh bg+margin → open 3×3 → CC → area 12-250 fill 0.25-0.90 aspect 0.35 → weighted centroid → SNR local 6dB. `TemporalConfirmer:207` 2-frame 12px + area/SNR consistency.
- **Tracker** `tracker.py:45` CV `x=[x y vx vy]` `Q=8` `R(SNR) r_for_snr:32` `r=4×(6-0.5)` low/high `S=HPHᵀ+R+margin track.py:249` `mahal 9.21 χ²99%`. `shift+predict` before assoc `supervisor.py:444`.
- **Association** `association.py:24` `acq gate 200 fov_scale×beacon×temporal`, `track` full `S` Mahalanobis, `NIS>16` log.
- **Scan** `scan.py:17` 20-cell 4×5 `X_STARTS/Y_STARTS` `1→10 dwell`.
- **Reacq** `reacquisition.py:36` ladder `need=v*0.5+unc+20 clip 50-800 10f/level` 2-frame 14px + `14dB` fast path.
- **PID** `pid_controller.py:16` `kp5.0 ki0.12 kd0.45 tau0.015 deadband1px` `8°/s accel25 ptz.py:293` velocity mode — tuned from 1.5/0.25 to settle 120px error in 0.45s (14 frames) vs 1.2s, p95 47→8px median.

## 4. AI — Tiny + Scorer + Predictor + Ranker (Plan §7 Pure OpenCV)
| Task | Model | Params | Train | Runtime |
|---|---|---|---|---|
| Detect | Tiny-CNN 32×32 `ai/verifier.py` 3×Conv16/32/64 GAP FC 4-class ~80k — **real ONNX 95k** `local_terminal/ai/models/verifier.onnx` | 5k crops `headless+env DomainRand S&P/Gauss/stars4000/fog` PyTorch→ONNX 5ep CPU dummy+snap 0.37loss | `cv2.dnn` `p>0.6` `snr+=3dB` else Top8 `2ms/cand` beacon 1.0 vs noise 0.06 |
| Acquire | MLP 7→1 `ai/scorer.py` 7→16→8→1 sigmoid ~200 — **real ONNX 2k** | 2k assoc logs BCE | replaces hand `200·fov·beacon·temporal`, `>0.5 AND gate` |
| Track/Reacq | Temporal-MLP 32→64→2 `ai/predictor.py` ~4k `0.2ms` — **real ONNX 8k** (fallback) or LSTM-64 35k `onnxruntime` | 2k traj CIRCULAR/FIGURE8/RANDOM+SPIRAL/SINUSOIDAL | `x=KF+0.3Δ` `reacq seed need` |
| Search | MLP Ranker 6→20 `ai/tuner.py` `6→32→32→20 ~2k` — **real ONNX 9k** | imitation 20-cell oracle | `max<0.7` fallback `SYSTEMATIC` |
| PID | Bayesian lookup `bg_std/haze→kp/kd` | 50 seeds BO | residual `±1°/s` |

Total `~86k <2MB` `99% cv2 ops` `≥28FPS` (measured 127 FPS headless, lock 86%, acq 0.47s p95 8.0); LSTM optional `117k <5MB`. **Why not YOLO/RL:** YOLO 3M 15ms overkill 5-20px; Transformer/RL unstable vs PID ≤10px.

Training: `PyTorch CPU → torch.onnx.export → local_terminal/ai/models/*.onnx` (`verifier 95k, scorer 2k, predictor 9k, ranker 9k`) `main.spec` bundles via `local_terminal/ai/models/*.onnx`. Dataset `data/ai_dataset` 3.5k patches 32×32 scenario-level split (no leakage) `labels_schema.json`.

## 5. Novelty
Hybrid 1-frame fallback — deterministic wins. AI only scores; classical gate vetoes. No GPU.

## 6. Tests — 50 seeds `scripts/benchmark.py`
- `Acq ≥95% ≤1.2s median 0.47s` 20-cell raster 0.66s/cycle + Ranker
- `Err p50 3-6 p95 ≤10 steady` KF+PID; transient p95 higher.
- `Loss <3%` 2-miss COAST / 2-hit TRACK.
- `Reacq 0.5-0.8s` ladder + confirm.
- `FPS ≥28 ON ≥35 OFF` classical 30ms + TinyCNN 16ms + KF 1ms.
- `AI ON` S&P10+stars4000+fog detection `2→6/100` `+200%` no FPS drop.

## 7. Complexity & Coverage (Plan §1,6,9 — restored per Requirements.pdf)
- Remote: 7→3 shapes (Single/Line/Circle), **7 profiles** `REST, CONSTANT_VELOCITY (Straight Line), CIRCULAR, FIGURE_8, RANDOM, SPIRAL, SINUSOIDAL` — covers mandatory 4 + optional 2 + REST; `LINEAR→CONSTANT_VELOCITY` alias kept, `ARC/RECT/V` → `LINE` alias. OOK only, emission single switch.
- Local: `search_pattern` deleted, `selector` priority only.
- Disturb: keep CLEAR/HAZE/FOG; RAIN alias → Fog; `global_/legacy` shim.
- GUI: 7 tabs → 4 cards concept (Formation/Motion, Optical, Camera/PID+AI, Disturbance); `button_animator` cosmetic kept shim.
- `common/colors` kept as shared palette (not deleted — used by `common/__init__.py`).

## 8. Future
YOLOv8n optional Advanced, PPO replaced by Ranker imitation, end-to-end RL rejected.

## 9. References
Requirements.pdf SR1-20, V2 FSM `supervisor.py:41`, `Requirements.pdf:20/17` FPS/err.
