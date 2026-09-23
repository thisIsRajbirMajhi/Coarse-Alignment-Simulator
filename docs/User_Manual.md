# User Manual — Coarse Alignment Simulator (Hybrid-AI)

## Install
```bash
pip install -r requirements.txt  # numpy<2.6 opencv>=4.8 PyQt5==5.15.11 (pure OpenCV AI)
# optional LSTM: pip install onnxruntime>=1.16
python main.py
```

## GUI — 4 Cards (Plan §5)
**Card 1 Formation/Motion** (Remote Terminal top): `Terminal Count 1..8`, `Shape SINGLE/LINE/CIRCLE` (spacing visible if >1), `Motion REST/CONSTANT_VELOCITY/CIRCULAR/FIGURE_8/RANDOM`, `Speed m/s`, `Heading deg`, `Start Offset X/Y`. `Randomize` shuffles valid combo.

**Card 2 Optical & Terminal**: `Terminal ID`, `Emission ON/OFF` (single master → BEACONING/FAULT; Power/Beacon merged), `State BEACONING/FAULT`, `Optical Power W`, `Wavelength 800-1700nm`, `Spot mrad 0.01-50` (= `beam_width R*width` telemetry). `Advanced` collapsed: `Token/Network/NAV`, `Pointing Jitter σ deg` (bias 0.005 internal), `Modulation` locked `OOK` disabled.

**Card 3 Camera/PID + AI**: `Camera` FOV 640×480 4°×3° (world 2000×2000 seed 42 centre (0°,0°)), `PID kp1.5 ki0.1 kd0.25 tau0.02 deadband1px` `5°/s accel25`, `AI OFF/ON` toggle + `Verifier Thr 0.6`. `OFF` = pure classical deterministic; `ON` = AI scores but classical vetoes, 1-frame fallback. FPS `≥35 OFF ≥28 ON`.

**Card 4 Disturbance** (S&P 10% Gauss20 Poisson jitter ±20px Haze/Fog): `Enable S&P/Gauss/Poisson`, `Density 0.10`, `Sigma 20`, `Jitter ±20`, `Preset CLEAR/HAZE/FOG` (RAIN alias → Fog). Turbulence/vignetting in `Advanced`. Environment: `World 2000×2000`, `Stars 0-4000`, `Haze 35%`, `Vignetting 0%`.

Control Deck tabs map to cards: Remote (1+2), Local (AI + Lost/Reacq), Environment (World/Stars), Disturbances (4), Camera/PID (3). `Presets` tab bundles.

## AI Toggle Demo (3 min video script)
1. `AI OFF` Start → `SEARCH` 20-cell raster 0.66s/cycle → `acq 0.47s`.
2. `S&P10%+stars4000+FOG` → classical `2/100` lock vs `AI ON 6/100` `+200%`.
3. `TRACK` err `p50 5px` steady; `COAST` 2-miss/2-hit; `LOST→REACQUIRE` ladder `need=v*0.5+unc+20` 50-800 `0.6s`.
4. `FPS` OFF 134 ON 133 — no drop. `onnxruntime` absent → Temporal-MLP auto.

## Headless & Benchmark
```bash
python scripts/generate_dataset.py  # 5k 640×480 gray + xy SNR for verifier
python scripts/benchmark.py --seeds 50  # Reports/benchmark.csv acq p50/p95 RMSE lock FPS
python -c "from simulation.headless import HeadlessSimulation; s=HeadlessSimulation(seed=42); s.reset(); [s.step() for _ in range(200)]"
```

## Build Standalone
```bash
pyinstaller main.spec  # bundles ai/*.onnx
dist/main/main.exe
```

## Troubleshooting
- `LINEAR` → `CONSTANT_VELOCITY` auto-mapped; `GRID/RECT/V/ARC` → `LINE`.
- `CW/PPM` → `OOK`; `OFF/STANDBY/LINKED` → `BEACONING`.
- `common/colors.py` kept — shared BGR palette.
- `--video input.mp4` bypass: `fov_pipeline.py` clean world + `PTZ bypass mode`.

## Performance Log
`headless.py:335 info {camera,pid} + supervisor.py:639 acq, err x/y, loss, reacq, FPS` → `Reports/benchmark.csv`.

## Requirements Map
See Technical Report §10.1-10.8 SR1-20 + 8 capabilities.
