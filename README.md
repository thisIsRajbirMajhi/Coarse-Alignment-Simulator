# FSOC virtual camera tracking system — coarse alignment simulator

A software-only simulator for the **coarse-alignment (PAT) stage** of a
mobile Free Space Optical Communication terminal: a moving beacon in a
2D scene, a virtual pan-tilt camera with limited FOV, CV-based
detection and tracking, a closed-loop controller, configurable
disturbances, and a live performance dashboard.

## Run it

```bash
pip install -r requirements.txt
python main.py
```

Click **Start**, pick a target motion profile, and drag the disturbance
sliders to see the tracker acquire, follow, and (if you push the sliders
high enough) lose and reacquire lock.

## Controls

- **Target motion** — `linear` / `curved` / `random_walk` switchable live.
- **Target speed** — 10–150 px/s.
- **Detector threshold** — 100–255 (higher = stricter).
- **Controller gain** — 0.02–0.50 via slider + spinbox (P-controller).
- **Disturbances (0–10 each):**
  - *Turbulence* — Gaussian blur + warp + flicker (atmospheric model).
  - *Vibration* — high-frequency jitter (platform shake).
  - *Camera Motion* — low-frequency correlated drift (mount drift).
  - *Noise* — additive Gaussian sensor noise.
- **Start / Pause / Reset / Export performance log** (CSV or JSON).

## Module map

| Package | Responsibility |
|---|---|
| `environment/` | 2D scene: background + static clutter (seeded, configurable) |
| `target/` | Beacon true position; linear / curved / random-walk motion, bounce/clamp per profile |
| `camera/` | Virtual pan-tilt camera, FOV cropping, clamped movement (`set_position` added) |
| `disturbance/` | Turbulence, platform vibration, **camera motion** (correlated drift), sensor noise |
| `detection/` | Brightness-threshold + contour centroid, per-frame, no memory |
| `tracking/` | Exponential smoothing + lock-status state machine (searching/acquired/tracking/lost) |
| `control/` | Proportional controller: tracking error → pan/tilt correction |
| `perf_log/` | Per-frame stats, exports FPS/error/lock-retention/processing-time as CSV or JSON |
| `gui/` | PyQt5 window; only module wiring others each tick (QTimer ~30 FPS, real-dt) |
| `tests/` | Headless unit tests for each module (run: `python tests/test_*.py`) |

## Simulation loop (one tick, in `gui/app.py::_tick`)

1. `target.update(dt)` — advance beacon (dt = real elapsed, clamped 5–100 ms)
2. `scene.get_frame()` + draw beacon onto it
3. `disturbance.apply_platform_vibration(...)` + `apply_camera_motion_with_state(...)`
4. `camera.capture(...)` crops FOV (temporarily perturbed, then restored)
5. `disturbance.apply_turbulence(...)`, `apply_sensor_noise(...)` degrade FOV frame
6. `detector.detect(...)` finds beacon (or `None`)
7. `tracker.update(detection)` updates smoothed estimate + lock status
8. `controller.compute_correction(...)` → `camera.move(...)` closes loop
9. `perf.log_frame(...)` records outcome
10. viewport, minimap (with FOV rect + estimated position dot), and stat labels redrawn
11. `QImage.copy()` used to avoid numpy-buffer lifetime bug; pixmap scaled with `SmoothTransformation`

## Design notes & future upgrades

- **Detection**: threshold + largest-contour centroid — optimal for bright beacon on dim background. Upgrade path: adaptive threshold or lightweight CNN in `detection/detector.py` only.
- **Tracking**: exponential smoothing + hit/miss counters, not Kalman. Kalman would predict through occlusion better — upgrade `tracking/tracker.py` only.
- **Turbulence**: blur + warp + flicker, not Zernike wavefront — visibly degrades detection at high intensity; note simplification in report.
- **Target motion**: linear heading randomized via seeded RNG; curved orbits center (clamped not bounced); random-walk uses `sqrt(dt)` diffusion scaling for speed-comparable motion.
- **Camera motion vs vibration**: intentionally distinct — vibration is white jitter, camera motion is correlated drift via `state={vx,vy}` with exponential decay 0.85.
- **Controller**: P-only; PID as future work.

## Testing

```bash
python tests/test_detector.py
python tests/test_tracker.py
python tests/test_camera.py
python tests/test_target.py
python tests/test_perf_log.py
python tests/test_disturbance.py
```

All tests are headless (no GUI) and deterministic via seeds.

## Packaging as standalone executable

```bash
pip install pyinstaller
pyinstaller --onedir --windowed --name FSOC-Simulator main.py
# output in dist/FSOC-Simulator/
```

For `--onefile`, replace `--onedir` with `--onefile` (slower startup).

## Deliverables checklist

- [x] Configurable virtual environment (size/seed/clutter, background color)
- [x] Moving target with 3 motion profiles (speed/brightness/radius configurable)
- [x] Movable virtual pan-tilt camera (FOV 200×150, clamped)
- [x] Automatic beacon detection (threshold configurable live)
- [x] Continuous CV-based tracking with lock status + reacquisition
- [x] Camera control/repositioning (closed loop, gain configurable live)
- [x] Disturbances: turbulence, platform vibration, **camera motion**, sensor noise (each 0–10)
- [x] Real-time performance display (FPS, error, lock status/retention, sim time)
- [x] Auto-generated performance report (CSV/JSON: duration, FPS, acquisition time, avg/max error, lock retention, processing time)
- [x] Unit tests (detector/tracker/camera/target/perf/disturbance)
- [ ] Standalone executable (PyInstaller command above — run before submission)
- [ ] Technical report & user manual (write once behavior is finalized — structure in docs/ if needed)
