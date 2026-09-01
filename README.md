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

## Module map — refactored 2026-09: isolated phase algorithms

| Package | Responsibility |
|---|---|
| `environment/` | 2D scene: background + static clutter (seeded, configurable) |
| `target/` | Beacon true position; linear / curved / random-walk motion, bounce/clamp per profile |
| `camera/` | Virtual pan-tilt camera, FOV cropping, clamped movement (`set_position` added) |
| `disturbance/` | Turbulence, platform vibration, **camera motion** (correlated drift), sensor noise |
| `detection/` | **Isolated detection** — stateless per-frame blob (grayscale→threshold→closing→contour moments→centroid). Own `config.py`/`constants.py`/`preprocessing.py`. No lock memory; runs every frame. |
| `searching/` | **Isolated SEARCHING** — `SearchingHandler` (no estimate, first hit→ACQUIRED) + `SearchingStrategy` (spiral/raster/random offsets for active scan). Own `constants.py`/`config.py`/`handler.py`/`scanner.py`. |
| `acquired/` | **Isolated ACQUIRED** — probation (`AcquiredHandler`: hits≥3→LOCKED, misses≥5→LOST). Own `constants.py`/`config.py`/`handler.py`. |
| `locked/` | **Isolated LOCKED (=TRACKING)** — stable tracking, retention (`LockedHandler`: hit→LOCKED, miss≥5→LOST) + `LockedFilter` (IIR α·y+(1-α)·x, alias for `tracking.filter`). Own `constants.py`/`config.py`/`handler.py`/`filter.py`. |
| `lost/` | **Isolated LOST** — hold last estimate, reacquisition window (`LostHandler`: hit→ACQUIRED, miss≥5·2.0→SEARCHING+clear). Own `constants.py`/`config.py`/`handler.py`. |
| `tracking/` | Orchestrator — `Tracker` + `LockStateMachine` (dispatches to `searching`/`acquired`/`locked`/`lost` handlers) + `ExponentialFilter` + `TrackerConfig`. Backward-compat entry: `from tracking.tracker import Tracker, LockStatus`. |
| `control/` | PID/P controller: tracking error → pan/tilt correction (respects `camera.max_slew*dt`) |
| `perf_log/` | Per-frame stats, exports FPS/error/lock-retention/processing-time as CSV or JSON |
| `gui/` | PyQt5 premium mission-control window (dark video stage `#0f172a`, light deck `#f1f5f9`, pill tabs, telemetry strip). Only wires others each tick (~30 FPS). |
| `tests/` | Headless unit tests for each module (run: `python -m pytest tests -q`) |

## Simulation loop (one tick, in `gui/main_window.py::_tick` — detection→phase→track→control)

1. `target.update(dt)` — advance beacon (dt = real elapsed, clamped 5–100 ms)
2. `scene.get_frame()` + `gui.core.renderer.Renderer.draw_targets()` onto it
3. `disturbance.apply_platform_vibration(...)` + `apply_camera_motion_with_state(...)` (vibration=white jitter, camera motion=correlated drift `state={vx,vy}` decay 0.85)
4. `camera.capture(...)` crops FOV (temporarily perturbed, then restored)
5. `disturbance.apply_turbulence(...)`, `apply_sensor_noise(...)` degrade FOV frame
6. `detection.BeaconDetector.detect_all(...)` — **isolated `detection/`** (grayscale→threshold→closing→contours→moments→centroid, stateless)
7. Hitbox-gated target check → `detection = hit` or `None` (only primary beacon in `hitbox_radius`, distractors ignored)
8. `tracking.Tracker.update(detection)` — **delegates to isolated phase handlers**: `searching/SearchingHandler` → `acquired/AcquiredHandler` → `locked/LockedHandler` → `lost/LostHandler` via `tracking.state.LockStateMachine`; filter `locked/filter.LockedFilter` (IIR) smooths hits
9. `control.PIDController.compute_correction(...)` → `camera.move(...)` closes loop (respects `camera.max_slew*dt` & `controller.output_clamp`)
10. `perf_log.PerformanceLogger.log_frame(...)` records locked/retention/detection/searching/lost
11. `gui.core.renderer.Renderer.render_viewport/minimap(...)` + overlay pulse, then `_update_stats()` + premium telemetry strip
12. `QImage.copy()` used to avoid numpy-buffer lifetime bug; pixmap scaled with `SmoothTransformation`

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
