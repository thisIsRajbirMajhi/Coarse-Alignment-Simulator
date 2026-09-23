# Implementation Plan — Simple, Reliable, Best Hybrid-AI Coarse Alignment

> Goal: Keep deterministic V2 FSM as sole owner of STATE. AI only SCORES. One-frame fallback to pure classical. Meets Requirements.pdf SR16-20 (acq≤2s, err≤10px, loss<5%, reacq≤1s, ≥20FPS) + AI-Based Technical 20%.

## 0. Principle: Drop Everything Not Pixel/SNR/Identity
World = 2000x2000 px, FOV 640x480 4°x3°, beacon 5-20px. Any param that doesn't change `pixel projection` or `SNR` or `TID` is deleted or demoted to internal const.

---

## 1. Remote Terminal — Prune 60% (`remote_terminal/`)

### Keep (user-visible)
- `config.py:122 RemoteFormationConfig` → `terminal_count 1..8`, `start_offset_x/y_m`, `terminal_spacing_m` (only if count>1), `speed_mps`, `heading_deg`, `motion_profile`
- `config.py:197 RemoteTerminalConfig` → `terminal_id`, `optical_power_w`, `wavelength_nm [800-1700]`, `spot_size_mrad`, `pointing_jitter_sigma_deg`, `operational_state BEACONING/OFF` (single master switch)
- `models.py:46 Vector2, Runtime` → `position_m/velocity_mps/range_m/los_angle_deg/pointing_error_deg/beam_width_rad`
- `motion.py:29 MotionModel` → profiles `REST, CONSTANT_VELOCITY, CIRCULAR, FIGURE_8, RANDOM` (4 mandatory Requirements.pdf:12). `speed/heading` derived velocity.
- `geometry.py:26`, `optics.py:13 is_emitting`, `pointing.py:24 PointingModel`, `terminal.py:19 RemoteTerminal.step`

### Demote to internal (not GUI, not editable)
- `CIRCULAR_RADIUS_M 500, FIGURE8 100/0.25, RANDOM_MAX_TURN 20, LINEAR_RAMP 5s` `motion.py:19`
- `beam_width_rad=spot*1e-3, beam_diameter=R*width` `optics.py:29` → derived telemetry only
- `ARC_ANGLE_DEG, RECTANGLE_ASPECT, V_HALF_ANGLE_DEG` `formation.py:15` → internal
- `POINTING_BIAS 0.005` `pointing.py:12` → internal bias inside `PointingModel`
- `beacon_sequence, beam_diameter_m, pointing_coupling, instantaneous_power_w` `models.py:60` → runtime telemetry only

### Delete / Merge
- **Formation shapes:** Delete `GRID, RECTANGLE, V_FORMATION, ARC` `config.py:13/formation.py:58`. Keep `SINGLE, LINE, CIRCLE` only. Rationale: PDF `1 mandatory, multiple optional` — 7 shapes inflate test matrix, `LINE` covers multi-target demo.
- **Motion:** Merge `LINEAR → CONSTANT_VELOCITY` (ramp adds 5s transient no PAT value). Delete `SINUSOIDAL` `config.py:28` (duplicate of FIGURE_8 perpendicular oscillation).
- **Modulation:** Lock to `OOK` only `config.py:42`. Delete `CW/PPM` dropdown — Fixes.md 4.9: only OOK has end-to-end frames, CW/PPM still emit OOK.
- **Power gating:** Merge `power_enabled + beacon_enabled + operational_state(5)` `config.py:202` → single `emission_enabled bool` + `operational_state {BEACONING, FAULT}`. Triple switch causes invalid combos.
- **Beacon payload extras:** Hide `token, network_id, enable_nav` `config.py:212` behind `Advanced` collapsed group; show only if `count>1`. Single-target mission doesn't need them.
- **Field:** Delete GUI edits for `range_m, los_angle, beam_angle, beam_diameter` — derived.

**File edits:**
- `remote_terminal/config.py` — shrink `FormationShape` enum to 3, `MotionProfile` to 5, `ModulationType` to 1, `FIELD_METADATA:352` drop ~15 entries, add `emission_enabled` alias.
- `remote_terminal/formation.py` — delete `_grid, _rectangle, _vee, _arc, _perimeter_point` keep `_line, _circle`
- `remote_terminal/motion.py` — delete `_sinusoidal_at, _linear` branch, keep `_constant_velocity` as LINEAR.
- `remote_terminal/pointing.py` — keep class, remove GUI exposure of `bias_deg` (internal 0.005).
- `remote_terminal/optics.py` — keep `is_emitting, beam_width_rad`, remove `CW` branch `optics.py:65`.

## 2. Local Terminal — AI Drop-in (`local_terminal/`)

### Keep core deterministic
- `supervisor.py:27 V2State 8-state + V2_VALID_TRANSITIONS:41` — single source of truth
- `detector.py:27 detect_spots` classical 30ms chain + `TemporalConfirmer:207 2-frame 12px`
- `tracker.py:45 KalmanFilter2D CV Q=8 R(SNR) r_for_snr:32 + shift+predict before assoc sup:444 S=HPHᵀ+R+margin:249`
- `association.py:24 associate_acquisition/tracking` Mahalanobis full `S`
- `scan.py:17 20-cell 4x5 X_STARTS/Y_STARTS 1→10 dwell`
- `reacquisition.py:36 ladder need=v*0.5+unc+20 clip50-800 10f/level 2-frame14px`

### Delete / Simplify
- `models.py:184 AutonomyConfig` — delete `search_pattern systematic/last_known/predicted` string (replaced by AI ranker), keep `candidate_* , association_*, kalman_*, lost_*, reacq_*`. Add `ai_enabled bool, ai_verifier_threshold 0.6`
- `identity.py / comm_receiver.py` — keep but hide advanced `p_rx_threshold` behind Advanced; no deletion.
- `selector.py` — keep `priority` only, delete `strongest_prx/highest_snr` policies (duplicate of identity).

### Add `local_terminal/ai/` (new, <300 LOC) — What AI to Use (Final Best)
| Task | **AI Model (final)** | Arch / I/O / Params | Training | Runtime |
|---|---|---|---|---|
| **Detect** `detector.py:27` | **Tiny-CNN Verifier 32x32** `ai/verifier.py` | `3xConv 3x3 16/32/64 + GAP + FC 4-class beacon/star/hot-pixel/haze ~80k` `in 32x32 gray patch → p(beacon) 0..1` `~2ms/cand` | `5k` crops auto `headless.py:229 + env:176 DomainRand S&P10% Gauss20 stars4000 fog` `PyTorch → ONNX` `10ep CPU` | `cv2.dnn.readNetFromONNX` or `onnxruntime` `p>0.6` keeps `snr+=3dB`, else fallback classical Top8 `~30ms+16ms → >28FPS` |
| **Acquire** `supervisor.py:367` | **MLP Scorer 7→1** `ai/scorer.py` | `7→16→8→1 sigmoid ~200 params` `in=[SNR,area,peak,dist_pred,P_rx,age,confirm] → score` | `2k` assoc logs `headless.py` `BCE` | Replaces hand `200*fov*beacon*temporal` scaling, `score>0.5 AND classical_gate` |
| **Track/Reacq** `tracker.py:45 reacq:36` | **LSTM-64 Residual** `ai/predictor.py` **→ Pure OpenCV: Temporal-MLP 32→64→2 `~4k` fallback** | `8×[x y vx vy]=32 → LSTM 1x64 → FC2 Δpred ~35k` or `Pure: 32→64→2 FC ~4k 0.2ms` `KF CV Q8 R(SNR) r_for_snr:32 S=HPHᵀ+R` `tracker.py:249` stays master `x=KF+0.3*Δ` | `2k` traj `motion.py:19 CIRCULAR/FIGURE8/RANDOM` | Seeds `need=v*0.5+unc+20` ladder `reacq:60` `NIS>16 sup:503` ignore — `LSTM` needs `onnxruntime`, `Temporal-MLP` pure `cv2.dnn` |
| **Search** `scan.py:144` | **MLP Ranker 6→20** `ai/tuner.py` | `6→32→32→20 ~2k` `in=[last_known,vel,unc,misses,bg_std] → cell scores` | Imitation on oracle `20-cell X_STARTS/Y_STARTS` traces | If `max<0.7` fallback `SYSTEMATIC scan.py:195` |
| **PID** `pid_controller.py:74` | **Bayesian Tuner (no NN)** | `bg_std/haze → kp/kd` lookup `kp1.5 ki0.1 kd0.25 tau0.02 deadband1px` | `Headless 50 seeds` BO | `PID 5°/s accel25 ptz.py:293` always drives, AI `±1°/s` residual only |
```
ai/
  verifier.py   # Tiny-CNN 32x32 3xConv16/32/64 GAP FC 80k ONNX — p(beacon)>0.6
  scorer.py     # MLP 7→1 Scorer — replaces hand gate scaling
  predictor.py  # LSTM-64 Residual — 8x4→2 Δ for KF + reacq seed
  tuner.py      # MLP Ranker 6→20 + Bayesian PID lookup
  __init__.py   # lazy load_verifier()/load_predictor() — no torch at import
```
- `verifier.py` implements `SpotDetector:256` → `AISpotDetector` wraps `detect_spots` proposals, `cv2.dnn.readNetFromONNX` fallback to classical if `p<0.6`. **Why not YOLOv8n 3M 15ms:** overkill for 5-20px, verifier 2ms/cand keeps >28FPS `Requirements.pdf:20`. YOLO kept as optional `Advanced` only.
- `scorer.py` replaces hand `beacon*temporal*fov` scaling `supervisor.py:367` — 7 features, no Transformer needed.
- `predictor.py` wraps `tracker.py:45` residual `0.3*Δ` and `reacquisition.py:60` seed — `KF + S=HPHᵀ+R+margin tracker.py:249 mahal9.21` stays veto, `NIS>16` ignore AI. Default `Temporal-MLP 32→64→2` pure `cv2.dnn`; `LSTM-64` via `onnxruntime` if installed (auto-detect).
- `tuner.py` holds both `Ranker 6→20` for `scan.py:144 ai_ranked_schedule()` and `Bayesian kp/kd` — no RL PPO (unstable vs `PID`).
- Training only `PyTorch→ONNX` CPU, runtime `onnxruntime>=1.16` or `cv2.dnn`, no GPU. `AISpotDetector:263` after `ClassicalSpotDetector`.

**File edits:**
- `local_terminal/detector.py` — add `class AISpotDetector(SpotDetector):263` after `ClassicalSpotDetector`, keep both.
- `local_terminal/supervisor.py` — inject `ai_verifier, ai_scorer, ai_predictor` optional in `__init__:78`, gate with `cfg.ai_enabled`. Fusion: `if ai_score>0.5 and classical_gate` then lock else classical.
- `local_terminal/tracker.py` — add `predict_with_ai()` wrapper, keep KF untouched.
- `local_terminal/scan.py` — add `ai_ranked_schedule()` wraps `plan_schedule:144` MLP 6→20 2x32.

## 3. Camera / Disturbance / Environment — Thin

### Keep
- `camera/ptz.py:18 PTZCamera` accel25, 5°/s, lag, backlash, encoder — needed for PID realism
- `camera/pid_controller.py:16 PID 1.5/0.1/0.25 tau0.02 deadband1px` + `camera/config.py:17 CameraConfig`
- `disturbance/core/ DisturbancePipeline` S&P10%, Gaussian σ20, Poisson, jitter ±20px, turbulence, `environment/haze.py, stars.py` hard negatives 6%

### Delete / Hide
- `disturbance/optical/channel.py RAIN, global_/ legacy.py` duplicate haze/rain — keep `CLEAR/HAZE/FOG` only per Requirements.pdf:3
- `disturbance/environment/atmospheric.py` complex depth gain — keep flat fog factor only
- GUI panels `gui/panels/environment_panel.py` extra sliders for `turbulence, vignetting_pct` — move to `Advanced` collapsed

## 4. Simulation — Headless remains AI data factory

- Keep `simulation/headless.py:34 HeadlessSimulation`, `simulation/env.py:37 FSOCEnv` Gym wrapper, `simulation/fov_pipeline.py` single post-noise chain
- Delete `simulation/__init__.py` re-exports duplicate `FSOCEnv` alias, keep one.
- Add `scripts/generate_dataset.py` (new, 80 LOC) → loops `HeadlessConfig` `env/config.py:176 generate_randomized_configs(n=5000)` → saves `640x480 gray + xy label + SNR` for verifier/CNN training.

## 5. GUI — Collapse to 4 cards

- Keep `gui/app.py, main_window.py, views/* fov_world`, `panels/controller_panel.py` gains, `panels/environment_panel.py` world/disturb
- **Delete** `gui/presentation/*` slideshow, `gui/windows/*` duplicate dialogs, `gui/core/button_animator` cosmetic
- New layout:
  - Card 1 Formation/Motion (count, shape 3, speed, heading, profile 5, start offset)
  - Card 2 Optical (power, wavelength, spot_size, jitter, emission ON/OFF)
  - Card 3 Camera/PID (pan/tilt speed, PID kp/kd, AI OFF/ON toggle)
  - Card 4 Disturbance (S&P, Gauss, jitter, Haze/Fog) collapsed Advanced

## 6. Common / Docs

- Keep `common/rng.py` deterministic seeding, `common/coordinates.py`, `common/protocol/beacon/*` (TID/CRC/NAV 12B)
- Delete `common/colors.py` searching/tracking aliases duplicate of `V2State`
- Move legacy `Performance Reports/*.py` deep_headless_test parallel scripts to `scripts/` single runner
- Delete `Plan/` empty, keep this file as `Plan/IMPLEMENTATION_PLAN_HYBRID_AI.md`

## 7. Dependencies — What AI Runtime to Use (Pure OpenCV Default)

```
requirements.txt:
numpy>=1.26,<2.6
opencv-python>=4.8,<5.1   # cv2.dnn for ONNX — ALL inference via OpenCV, no onnxruntime required
PyQt5==5.15.11
# onnxruntime>=1.16 — OPTIONAL only if LSTM-64 kept; pure-OpenCV uses Temporal-MLP instead (see below)
# Training only (dev, not shipped):
# torch>=2.1 --extra-index-url CPU + onnx (export) — 5k crops 10ep ~10min CPU
# ultralytics optional — YOLOv8n 3M 15ms alternative verifier (Advanced, not default)
```
- **Pure OpenCV inference (default):** `cv2.dnn.readNetFromONNX` (already in `opencv-python`) runs `Tiny-CNN 80k + MLP 200 + Ranker 2k + Temporal-MLP 4k` = `~86k params <2MB` `99% cv2 ops`. `Temporal-MLP 32→64→2` `predictor.py` replaces `LSTM-64 35k` — `8×[x y vx vy]=32→64→2 FC` `~0.2ms` `~5%` less maneuver gain but `cv2.dnn` fully supported vs `LSTM` `cv2.dnn` incomplete.
- **With onnxruntime (optional):** Keep `LSTM-64 35k` `ai/predictor.py` `8×4→LSTM→FC2` `~0.5ms` via `onnxruntime` for `+5%` `Fig8/Random` — `117k <5MB`. Toggle `ai/use_onnxruntime = auto` (fallback to Temporal-MLP if not installed).
- **Training:** `PyTorch` CPU → `torch.onnx.export` → `ai/*.onnx` checked into `main.spec` includes. No GPU, no `gymnasium` hard dep — `simulation/env.py` already soft `FSOCEnv` for `Ranker` imitation (not PPO).
- **Why this AI:** `Tiny-CNN 2ms/cand` + `KF+PID` deterministic beats `YOLO 15ms` / `Transformer` / `End-to-end RL` on `≥20FPS` and `≤10px` `Requirements.pdf:20/17`. Pure OpenCV keeps `one dependency` `opencv-python` for `Benchmark-2 .mp4` `SR20`.

## 8. Implementation Phases (1 week)

**Phase 0 (0.5d):** Backup, branch `hybrid-ai`, run `pytest + deep_headless_test.py` baseline SR17-19 snapshot.
**Phase 1 (1d):** Prune `remote_terminal` enums/fields + `formation.py` + `motion.py` + `optics.py CW`. Update `FIELD_METADATA` + `validate()` + GUI cards. Test `make_default_scenario()` still passes.
**Phase 2 (1.5d):** Add `local_terminal/ai/verifier.py` + `AISpotDetector` + `scripts/generate_dataset.py` 5k crops. Train Tiny-CNN 10 epochs CPU, export ONNX, wire `supervisor.py` toggle `ai_enabled`. Bench `FPS>28`.
**Phase 3 (1d):** Add `ai/scorer.py + predictor.py` + inject in `supervisor/tracker/reacquisition`. Keep classical gate as veto.
**Phase 4 (0.5d):** Add `ai/tuner.py` + `scan ai_ranked_schedule` MLP. GUI `AI OFF/ON`.
**Phase 5 (1d):** GUI collapse 8→4 cards, delete `presentation/windows` + disturbance duplicates. Headless validation `acq, err, loss, reacq` vs baseline must not regress.
**Phase 6 (0.5d):** Update `main.spec` include `ai/*.onnx`, regenerate `Technical Report` §AI methods, `User Manual` AI toggle.

## 9. Deletion Checklist (verify no import remains)

- [ ] `FormationShape.GRID/RECTANGLE/V_FORMATION/ARC` + `formation.py _grid/_rectangle/_vee/_arc/_perimeter_point`
- [ ] `MotionProfile.SINUSOIDAL` + `motion.py _sinusoidal_at` + `LINEAR` duplicate
- [ ] `ModulationType.CW/PPM` + `optics.py:65 CW branch`
- [ ] `FIELD_METADATA` 15 entries (token/net/nav extra, beam_diameter, range, los) + `power_enabled+beacon_enabled` duplicate
- [ ] `disturbance/global_, legacy.py, optical/channel RAIN`, `environment/gradient.py` if unused
- [ ] `gui/presentation, gui/windows, gui/core/button_animator`, `common/colors.py` aliases
- [ ] `Performance Reports/ deep_headless_test copy, fix_report` → single `scripts/benchmark.py`

## 10. Requirement Compliance Matrix — All `Requirements.pdf` Sr 1-20 Must Pass

### 10.1 Camera Parameters Sr 1-6
| Sr | Requirement | Plan Satisfies | File |
|---|---|---|---|
| 1 | Screen Size min 2000x2000, user-defined | `EnvironmentConfig world_width/height default 2000` `environment/config.py:126` + GUI Card 1 allows 1000-4000, kept | `environment/config.py` `gui/panels/environment_panel.py` |
| 2 | Camera Type Monochrome Focal Plane Array, optional Colour | `PTZCamera.extract_fov_at:439` → `GRAY2BGR` monochrome output `raw_monochrome (480,640) uint8` `ptz.py:508`, colour overlay only for reticle. Keeps mono per spec, colour optional via flag | `camera/ptz.py:426` |
| 3 | Camera Resolution 640x480 user-defined | `CameraConfig resolution_w 640 resolution_h 480` `camera/config.py:23` validated, `PTZCamera fov_width/height:122` | `camera/config.py:17` |
| 4 | Camera FOV user-defined default 4°x3° | `fov_deg_h 4.0 fov_deg_v 3.0` `camera/config.py:23` `deg_per_px_h =4/640` `px_per_deg_h 160` `camera/config.py:65` | `camera/config.py` `camera/ptz.py:527` |
| 5 | Camera update Rate 30Hz min | `HeadlessSimulation dt 1/30` `headless.py:30` `PID 30Hz` `controller.py:107 dt clip 1e-4..0.1` + `sim_speed` | `simulation/headless.py:27` |
| 6 | Initial Camera Position Centre | `CameraConfig get_initial_pose home (0°,0°) → world (1000,1000)` `camera/config.py:106` `ptz.py:129 get_home`, custom `start_pan/tilt + scan_start_index 0..19` for user-defined but defaults centre | `camera/ptz.py:37` |

### 10.2 Target Parameters Sr 7-12
| Sr | Requirement | Plan Satisfies | File |
|---|---|---|---|
| 7 | Target Type Beacon Spot | `RemoteTerminalConfig` `optical_power_w + spot_size_mrad` `config.py:205` → `BeamModel emission` `optics.py:39` + `BeaconGenerator OOK` `terminal.py:28` | `remote_terminal/terminal.py` |
| 8 | Number of Targets 1 mandatory multiple optional | `terminal_count 1..8 MAX_TERMINALS:87` `config.py:122 SINGLE/LINE/CIRCLE` pruned keeps 1..N demo | `remote_terminal/config.py:87` |
| 9 | Target Shape user-defined default Square | `Beacon spot rendered via environment/scene.py Gaussian σ` covers square 10x10 via `spot_size_mrad` → pixel size `haze.py/stars.py` square path kept | `remote_terminal/optics.py:33` |
| 10 | Target Size 5-20 default 10x10 | `spot_size_mrad 0.01-50 default 1.0` `config.py:431` maps to `beam_diameter_m = R*width` `optics.py:33` → `5-20px` at range, validated `detector area 12-250` `detector.py:99` | `remote_terminal/config.py` `local_terminal/detector.py:99` |
| 11 | Initial Target Location user-defined Random | `start_offset_x/y_m -5000..5000` `config.py:383` + `Random` default `make_default_scenario:334` centre | `remote_terminal/config.py:383` |
| 12 | Motion ≥4: Straight, Circular, Figure8, Random (+ Spiral, Sinusoidal, User) | Keep `REST, CONSTANT_VELOCITY (=Straight/Linear), CIRCULAR, FIGURE_8, RANDOM` `motion.py:29` — covers 4 mandatory; `Spiral` = `CIRCULAR` variant, `Sinusoidal` deleted as dup but `FIGURE8` already is sinusoidal. User-defined via `MotionProfile` extensible `motion.py:45` | `remote_terminal/motion.py` |

### 10.3 Camera Motion Constraints Sr 13-15
| Sr | Requirement | Plan Satisfies | File |
|---|---|---|---|
| 13 | Max Pan Speed 5-10°/s user-defined default 5 | `max_pan_speed_deg_s 5.0` `camera/config.py:30` limit `CAMERA_LIMITS` 5-10, clamped `ptz.py:235` `max_pan_accel 25` | `camera/config.py:30` `camera/constants.py` |
| 14 | Max Tilt Speed 5-10°/s | Same `max_tilt_speed_deg_s 5.0` `camera/config.py:31` | Same |
| 15 | Update Interval ≥20Hz | `PID deadband+tau filter` `pid_controller.py:16` supports `≥20Hz`, `Headless dt 1/30` + `sim_speed` ensures `20-60FPS` bench `>25` | `camera/pid_controller.py` `simulation/headless.py` |

### 10.4 Performance Specifications Sr 16-20
| Sr | Spec | Plan Target | How |
|---|---|---|---|
| 16 | Acquisition ≤2s | `≥95% ≤1.2s` | `20-cell raster 0.66s/cycle + AI Ranker 6→20` `scan.py:17` + `MLP scorer gate 200 + 2-frame 25px confirm sup:379 + 14dB fast` |
| 17 | Tracking Error ≤10px | `p50 3-6px p95 ≤10px steady` | `KF CV Q8 R(SNR) r_for_snr:32 + shift-predict S=HPHᵀ+Rmargin:249 + PID kp1.5 kd0.25 tau0.02 deadband1px pid:130 + AI LSTM 0.3Δ` |
| 18 | Target Loss <5% | `<3%` | `2-miss COAST pid_on / 2-hit TRACK sup:547 + unc>30+0.5s→LOST sup:566 + NIS>16 ignore` |
| 19 | Re-acquisition ≤1s | `0.5-0.8s` | `ladder need=v*0.5+unc+20 reacq:60 50-800 10f/level + LSTM seed + 2-frame14px reacq:151` |
| 20 | Processing ≥20FPS | `≥28FPS AI ON, ≥35 AI OFF` | `Classical 30ms + TinyCNN 2ms/cand 16ms + KF 1ms → 47ms cap 640x480` `fov_pipeline.py` single post-noise chain `disturbance:665` keep S&P Gauss Poisson only |

### 10.5 Disturbances and Noise Sr 21 (1-5)
| Req | Spec | Plan |
|---|---|---|
| 21.1 | Image Noise S&P ~10%, Gaussian, Poisson selectable | `DisturbancePipeline sensor/image_noise.py:87 S&P 10% 65% transient` + `Gaussian σ 20` + `Poisson` kept `disturbance/core/config.py` one-or-more selectable GUI Card 4 |
| 21.2 | Max Std Deviation 20px | `Gaussian σ20` cap `image_noise` `20` `candidate_peak_margin bg+margin:56` adaptive `bg>35 +2` `detector.py:57` handles |
| 21.3 | Max Camera Jitter ±20px/frame | `jitter.py:44 OU correlated shake ±20px` + `platform motion ±20` `DisturbanceContext dt` kept, `KF predict dt` handles |
| 21.4 | Atmospheric Clear, Haze, Fog, Rain, Low light contrast/brightness reduction | Keep `CLEAR/HAZE/FOG` `disturbance/environment/atmospheric.py` flat factor + `haze.py FBM` + `vignetting.py` `environment/vignetting.py`. Delete `RAIN` duplicate `optical/channel.py` (Rain= Fog+noise subset). Low light = `vignetting_pct` kept |
| 21.5 | Platform Motion ±20px/frame Linear mandatory Circular/Random/Spiral/Fig8 optional | `MotionModel` `speed_mps` → `±20px` via `px_per_deg 160` `camera/config.py:73`, default `LINEAR` `motion.py:106 CONSTANT_VELOCITY`, optional 4 profiles kept. `FOV jitter` via `headless.py:257 disturb_camera_pose` |

### 10.6 Expected Solution — 8 Capabilities (§ Expected Solution)
| Capability | Plan Module |
|---|---|
| Generate configurable virtual environment | `environment/scene.py + config.py:126 stars/haze/gradient` Card 1 |
| Generate one or more moving targets | `remote_terminal/formation.py LINE/CIRCLE + motion.py 5 profiles` |
| Movable virtual camera | `camera/ptz.py:18 2-axis gimbal + fov_pipeline.py` |
| Detect beacon automatically | `local_terminal/detector.py:27 classical + ai/verifier.py Tiny-CNN 80k` |
| Track continuously with CV | `tracker.py:45 KF + ai/predictor.py LSTM + association.py` |
| Control/reposition camera | `pid_controller.py:16 filtered-D + ptz.py:293 velocity mode sup:244 → headless.py:244` |
| Generate disturbances | `disturbance/ DisturbancePipeline S&P/Gauss/Poisson/jitter/fog + fov_pipeline:27 optical+sensor` |
| Display real-time stats | `gui/views/*` + `supervisor.py:639 telemetry` `track_err/loss/reacq/FPS` + `gui/app.py` |

### 10.7 Deliverables (5) — Checked
- **Standalone App:** `main.py:6 + main.spec` PyInstaller exe, `gui/app.py` single window 4 cards + `Plan:7` `onnxruntime` bundle `ai/*.onnx` `main.spec` include
- **Source Code:** `Plan:1-6` modular `camera/local_terminal/remote_terminal/simulation` commented `validate()` strict, `ai/` <300LOC
- **Technical Report 10-15p:** § Problem + Arch `supervisor FSM 8-state valid graph:41` + `detector/KF/PID` + `AI TinyCNN 80k MLP LSTM` + test 50 seeds + `SR16-20` analysis + future `YOLO/RL`
- **User Manual + 3-5min Video:** `GUI Card 1-4` install `requirements.txt` `pip install -r` + `python main.py` + `AI OFF/ON` toggle demo + video `benchmark Performance-2 .mp4 bypass`
- **Performance Log auto:** `headless.py:335 info {camera,pid} + supervisor.py:639 acquisition_time_s, tracking_error_x/y, loss_count, reacq_time_s, FPS` → `Reports/` CSV + `scripts/benchmark.py` `acq, err p50/p95, RMSE, lock%, FPS`

### 10.8 Evaluation Mapping (100%)
- **Functional 20%:** 1) all 8 caps `10.6` + 2) operational `pytest + Headless 200 steps seed42 deterministic` + 3) GUI 4 cards collapsed Advanced
- **Benchmark Perf-1 30%:** Scenario execution + centroid error log `supervisor tracker.error_px 640/480` + auto `benchmark.py 50 seeds acq/loss/reacq`
- **Benchmark Perf-2 30%:** `.mp4 @30fps` bypass `simulation/fov_pipeline.py` `simulation/headless.py:264 capture clean world + FOV vignetting/post` + `PTZ bypass mode` `--video input.mp4` takes `video` as `world_frame` direct to `supervisor.step` (no PTZ). Compare `tracker.error_px` vs predef, `RMSE/acq/reacq/lock/FPS` `scripts/benchmark.py`
- **Technical 20%:** 1) Understanding `Plan:0 Principle pixel/SNR/TID` + 2) Arch `V2 FSM single source headless→FSM→PID` + 3) Algorithms `detector p30/Gauss/SNR, KF S=HPHᵀ+R, PID τ/deadband` + 4) AI `TinyCNN 80k + MLP + LSTM` `Plan:7` `117k <5MB ONNX CPU` + 5) Novelty `Hybrid 1-frame fallback — deterministic wins` + 6) Doc `Plan/IMPLEMENTATION_PLAN_HYBRID_AI.md + Technical Report` + 7) Q&A `why not YOLO/RL: >28FPS vs 15ms, ≤10px`

## 11. Validation Gates

- `python -m pytest` pass, `HeadlessSimulation 200 steps seed 42` deterministic
- `benchmark.py` 50 seeds: `acq ≤2s ≥95%, steady err p50 3-6px p95 ≤10px, loss <5%, reacq ≤1s, FPS ≥25` both `AI OFF` and `AI ON`
- `AI ON` improves `S&P10%+stars4000+fog` detection `≥8%` without FPS drop below 20

Result: Simple (4 cards, 3 shapes, 1 modulation), Reliable (classical FSM always wins), Best (AI +2ms patch filter, LSTM residual, learned gate) — satisfies ISRO `AI-Based` + `60% Benchmark`.
