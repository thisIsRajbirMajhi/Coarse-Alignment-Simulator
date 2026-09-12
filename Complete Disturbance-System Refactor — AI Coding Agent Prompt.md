# Task: Complete Refactor of the Disturbance System

You are working on the repository:

`thisIsRajbirMajhi/Coarse-Alignment-Simulator`

Branch: `Main`

Your task is to perform a **complete architectural refactor of the disturbance system**.

The goal is **not** to redesign the disturbance mathematics or add new scientific models. The goal is to reorganize the existing system so that:

1. Shared/global disturbance infrastructure is clean and centralized.
2. Each disturbance is owned by the module it physically affects.
3. Configuration is strongly typed and mirrors the architecture.
4. Temporal state is explicit and per simulation instance.
5. The GUI/simulation tick no longer manually orchestrates individual disturbances.
6. Existing disturbance behavior is preserved as closely as possible.
7. Existing tests continue to pass, and new architecture-level tests are added.
8. Backward compatibility is preserved during migration where practical.

---

# 1. First: Inspect the Entire Repository

Before modifying anything, deeply inspect the repository.

Pay particular attention to:

```text
disturbance/
camera/
target/
environment/
simulation/
tracking/
control/
gui/
tests/
```

Read and understand at minimum:

```text
disturbance/config.py
disturbance/constants.py
disturbance/disturbances.py
disturbance/state.py
disturbance/dt_provider.py
disturbance/turbulence.py
disturbance/vibration.py
disturbance/camera_motion.py
disturbance/camera_jitter.py
disturbance/platform_motion.py
disturbance/atmospheric.py
disturbance/sensor_noise.py
disturbance/image_noise.py
disturbance/helpers.py

camera/ptz_camera.py
camera/config.py

target/motion.py
target/config.py

environment/scene.py
environment/haze.py
environment/vignetting.py

gui/mixins/tick_mixin.py

simulation/headless.py

tests/test_disturbance.py
tests/test_environment.py
tests/test_camera.py
tests/test_target.py
tests/test_closed_loop.py
tests/test_control.py
tests/test_tracker.py
```

Also search the complete codebase for:

```text
from disturbance
import disturbance
apply_turbulence
apply_platform_vibration
apply_platform_motion
apply_camera_jitter
apply_camera_motion
apply_sensor_noise
apply_image_noise
apply_atmospheric_disturbance
DisturbanceConfig
DisturbanceState
_turb_state
_vib_state
_cam_motion_state_global
_platform_state_global
_jitter_state_global
```

Do not begin refactoring until you understand every caller.

---

# 2. Core Architectural Principle

Refactor according to:

> A disturbance belongs to the module where its physical effect occurs.

Use these ownership rules.

## Global/shared infrastructure

Own:

- simulation time
- `dt`
- RNG
- deterministic seeding
- disturbance scenario generation
- disturbance enable/disable state
- shared orchestration
- reset lifecycle

Global/shared code must NOT directly modify camera, target, sensor, or environment state.

---

## Environment-owned disturbances

Environment owns disturbances that modify the world/environment itself.

Examples:

- atmospheric condition state
- haze state
- cloud state if/when implemented
- environmental clutter state if applicable
- visibility/illumination conditions

Do not move scene-generation responsibilities into the disturbance package unnecessarily.

---

## Target-owned disturbances

Target owns anything that changes the target's own physical or optical behavior.

Examples:

- wind perturbation
- angular/AoA jitter
- gimbal lag
- target photometric variation
- target scintillation
- beacon blinking/dropout/coding behavior

Do NOT keep target-specific disturbance logic in the global disturbance subsystem.

---

## Camera-owned disturbances

Camera disturbance subsystem owns effects that physically alter camera/platform pointing.

Examples:

- platform motion
- vibration
- camera jitter
- camera drift/motion

These should remain separate algorithms internally because they have different temporal/frequency characteristics, but they should be exposed through one camera-disturbance interface.

---

## Optical-owned disturbances

Optical subsystem owns image propagation effects.

Examples:

- atmospheric propagation degradation
- turbulence
- seeing blur
- spatial optical distortion
- scintillation caused by propagation

The existing turbulence implementation should be preserved initially.

Do not rewrite its mathematical behavior during the architectural refactor.

---

## Sensor-owned disturbances

Sensor subsystem owns detector/image measurement imperfections.

Examples:

- Poisson/shot noise
- Gaussian/read noise
- dark current
- PRNU
- hot/dead pixels
- salt-and-pepper defects
- quantization
- sensor-level exposure/noise effects

The current `sensor_noise.py` and `image_noise.py` functionality should be consolidated conceptually under this layer.

Do not introduce duplicated sensor-noise pipelines.

---

# 3. Target Architecture

Create a clean structure similar to:

```text
disturbance/
│
├── core/
│   ├── __init__.py
│   ├── context.py
│   ├── scenario.py
│   ├── state.py
│   ├── config.py
│   └── pipeline.py
│
├── global/
│   ├── __init__.py
│   └── randomization.py
│
├── camera/
│   ├── __init__.py
│   ├── subsystem.py
│   ├── platform.py
│   ├── vibration.py
│   ├── jitter.py
│   └── drift.py
│
├── environment/
│   ├── __init__.py
│   └── atmospheric.py
│
├── optical/
│   ├── __init__.py
│   ├── subsystem.py
│   └── turbulence.py
│
├── sensor/
│   ├── __init__.py
│   ├── subsystem.py
│   ├── sensor.py
│   ├── image_noise.py
│   └── defects.py
│
└── legacy.py
```

Exact filenames may vary if a better organization is justified, but ownership and separation must follow the architecture above.

Do NOT create unnecessary files merely for aesthetic organization.

---

# 4. Introduce a DisturbanceContext

Create a strongly typed context object.

Suggested design:

```python
@dataclass
class DisturbanceContext:
    dt: float
    sim_time: float
    rng: np.random.Generator
```

The context may also expose references to subsystem state/config if appropriate, but avoid turning it into a generic dumping ground.

The context must be:

- per simulation instance
- deterministic when seeded
- independent between simultaneous simulations/tests
- free of hidden global mutable state

---

# 5. Eliminate Hidden Global Mutable Disturbance State

The current system contains module-level states such as:

```text
_turb_state
_vib_state
_cam_motion_state_global
_platform_state_global
_jitter_state_global
```

These must no longer be the primary architecture.

Replace them with explicit per-instance state objects.

For example:

```python
@dataclass
class CameraDriftState:
    vx: float = 0.0
    vy: float = 0.0
    bias_pan: float = 0.0
    bias_tilt: float = 0.0
```

Similarly create typed states for:

- turbulence
- vibration
- camera jitter
- platform motion
- sensor defects where persistence is required

Each simulation instance must get its own state.

No simulation should inherit disturbance state from a previous simulation.

---

# 6. Create Typed State Objects

Avoid arbitrary dictionaries where possible.

Replace patterns such as:

```python
state["vx"]
state["vy"]
state["bias_pan"]
```

with dataclasses.

Examples:

```python
@dataclass
class TurbulenceState:
    dx: np.ndarray | None = None
    dy: np.ndarray | None = None
    time: float = 0.0
```

```python
@dataclass
class VibrationState:
    time: float = 0.0
    phases: np.ndarray | None = None
    ou_pan: float = 0.0
    ou_tilt: float = 0.0
```

```python
@dataclass
class JitterState:
    x: float = 0.0
    y: float = 0.0
```

Use equivalent typed state classes for other stateful disturbances.

Do not over-engineer the classes.

---

# 7. Split Configuration by Ownership

The existing `DisturbanceConfig` currently mixes many responsibilities.

Refactor into:

```python
@dataclass
class GlobalDisturbanceConfig:
    enabled: bool = True
    seed: int | None = None
```

```python
@dataclass
class CameraDisturbanceConfig:
    platform: ...
    vibration: ...
    jitter: ...
    drift: ...
```

```python
@dataclass
class OpticalDisturbanceConfig:
    turbulence: ...
```

```python
@dataclass
class SensorDisturbanceConfig:
    sensor_noise: ...
    image_noise: ...
```

```python
@dataclass
class EnvironmentDisturbanceConfig:
    atmospheric: ...
```

```python
@dataclass
class TargetDisturbanceConfig:
    ...
```

Then create a root configuration:

```python
@dataclass
class DisturbanceConfig:
    global_: GlobalDisturbanceConfig
    environment: EnvironmentDisturbanceConfig
    target: TargetDisturbanceConfig
    camera: CameraDisturbanceConfig
    optical: OpticalDisturbanceConfig
    sensor: SensorDisturbanceConfig
```

Use validation on each sub-config.

Do not break YAML/config serialization.

---

# 8. Preserve Existing User-Facing Controls

Existing GUI controls such as:

```text
Turbulence
Vibration
Camera Motion
Noise
Camera Jitter
Atmospheric preset
Platform profile
Platform speed
Gaussian noise
Poisson noise
Salt & pepper noise
```

must continue to work.

Do not remove functionality merely because the internal architecture changes.

The GUI should eventually write to typed configuration, not directly manipulate disturbance implementation state.

---

# 9. Create CameraDisturbanceSubsystem

Create a single public subsystem:

```python
class CameraDisturbanceSubsystem:
    def apply(
        self,
        pan: float,
        tilt: float,
        context: DisturbanceContext,
    ) -> tuple[float, float]:
        ...
```

Internally it should apply, in a documented order:

```text
platform motion
→ vibration
→ jitter
→ drift
```

The exact ordering must preserve current behavior unless testing demonstrates that another order is required.

Keep the individual models separate.

The subsystem should own:

```text
PlatformMotionState
VibrationState
JitterState
DriftState
```

Do not put camera actuator mechanics such as slew rate, backlash or latency into the disturbance subsystem.

Those remain in `camera/ptz_camera.py`.

---

# 10. Preserve the Camera/Disturbance Boundary

The camera's intrinsic mechanics remain in the camera module:

```text
slew rate
acceleration
latency
backlash
resolution
encoder behavior
```

Disturbances modify actual camera/platform pointing externally.

Do not merge these into one model.

Desired conceptual flow:

```text
controller command
        ↓
PTZ actuator model
        ↓
nominal camera pose
        ↓
CameraDisturbanceSubsystem
        ↓
disturbed camera pose
```

---

# 11. Create OpticalDisturbanceSubsystem

Create:

```python
class OpticalDisturbanceSubsystem:
    def apply(
        self,
        frame: np.ndarray,
        context: DisturbanceContext,
    ) -> np.ndarray:
        ...
```

Initially use the existing turbulence implementation without changing its underlying model.

Atmospheric image degradation should also be routed through the optical/environment boundary in a clean way.

The subsystem should own optical-state memory.

Do not allow the GUI to call `apply_turbulence()` directly.

---

# 12. Separate Atmospheric State from Image Application

The current atmospheric implementation directly modifies the frame with:

- blur
- contrast reduction
- brightness reduction
- haze
- bloom
- rain streaks
- low-light degradation

Preserve the current behavior, but architecturally distinguish:

```text
Atmospheric condition
```

from:

```text
Atmospheric image effect
```

For example:

```text
AtmosphericConfig
        ↓
AtmosphericState
        ↓
AtmosphericRenderer / OpticalDisturbance
        ↓
image degradation
```

Do not introduce complex atmospheric science.

This is an architectural separation only.

---

# 13. Create SensorDisturbanceSubsystem

Create:

```python
class SensorDisturbanceSubsystem:
    def apply(
        self,
        frame: np.ndarray,
        context: DisturbanceContext,
    ) -> np.ndarray:
        ...
```

This subsystem should contain:

```text
Poisson / shot noise
Gaussian / read noise
PRNU
dark current
hot pixels
dead pixels
salt & pepper defects
quantization
```

Consolidate existing `sensor_noise.py` and `image_noise.py` behavior conceptually.

Do not apply the same noise twice.

The physical order should remain compatible with current intended behavior:

```text
optical image
→ photon/Poisson
→ read/Gaussian
→ persistent/transient defects
→ quantization
```

Where existing `apply_sensor_noise()` already models these effects, reuse rather than duplicate.

---

# 14. Move Target Disturbances into the Target Module

Do not create a global target-disturbance layer unless required for orchestration.

Target-specific effects should live with the target implementation.

Refactor toward:

```text
target/
    motion.py
    disturbances.py
```

or equivalent.

Target disturbance logic includes:

```text
wind
AoA jitter
gimbal lag
photometric variation
scintillation
dropout/blinking
```

The target subsystem should update target state before rendering.

---

# 15. Keep Environment Responsibilities Clean

Environment code should own:

```text
sky/background
stars
haze/background composition
future clouds
future terrain
future environmental clutter
```

Do not turn `disturbance/environment` into a second scene renderer.

Only move atmospheric disturbance state/effects there where appropriate.

---

# 16. Create a Top-Level DisturbancePipeline

Create one orchestrator:

```python
class DisturbancePipeline:
    ...
```

Its job is orchestration only.

It should expose clear operations such as:

```python
update_environment(...)
update_target(...)
disturb_camera_pose(...)
apply_optical(...)
apply_sensor(...)
```

or an equivalent well-designed API.

Do not put mathematical disturbance implementations directly into this class.

It should delegate.

---

# 17. Refactor the Simulation Tick

The GUI currently manually applies multiple disturbance functions in sequence.

Remove that responsibility from `gui/mixins/tick_mixin.py`.

The target structure should be:

```text
Tick
 ↓
simulation engine / disturbance pipeline
 ↓
camera frame
```

The tick should read more like:

```python
context = self.disturbance_context.step(dt)

self.targets.update(context)

self.camera.update(dt)

pose = self.disturbances.camera.apply(
    self.camera.pan,
    self.camera.tilt,
    context,
)

frame = self.renderer.capture(pose)

frame = self.disturbances.optical.apply(frame, context)

frame = self.disturbances.sensor.apply(frame, context)

tracking = self.pipeline.update(frame, dt)
```

Do not allow `TickMixin` to know implementation details such as:

```text
apply_platform_vibration
apply_camera_jitter_with_state
apply_camera_motion_with_state
apply_turbulence
apply_sensor_noise
apply_image_noise
```

---

# 18. Create a Scenario / Domain-Randomization Layer

Move the existing training randomization logic out of the monolithic configuration class.

Create something like:

```python
class DisturbanceScenarioGenerator:
    def generate(
        self,
        seed: int,
        difficulty: str = "medium",
    ) -> DisturbanceConfig:
        ...
```

Support:

```text
easy
medium
hard
mixed
```

Preserve the existing randomization behavior as much as possible.

The resulting scenario must be deterministic for the same seed.

---

# 19. Preserve Backward Compatibility During Migration

Do not immediately delete:

```text
disturbance/disturbances.py
```

Instead convert it into a compatibility facade.

Example:

```python
from disturbance.camera import ...
from disturbance.optical import ...
from disturbance.sensor import ...
```

Mark old APIs as deprecated internally where appropriate.

Existing external code should not suddenly break.

After migration, search the entire repository to ensure all internal code uses the new architecture.

---

# 20. Testing Requirements

Before refactoring:

1. Run the existing test suite.
2. Record baseline results.
3. Record important numerical/visual sanity outputs where useful.

After each major phase, run tests.

Add tests for:

### State isolation

Create two simulations with different seeds and ensure disturbance states do not leak.

### Determinism

Same:

```text
seed
config
initial state
dt sequence
```

must produce equivalent disturbance behavior.

### Reset

Resetting a simulation must return disturbance state to initial behavior.

### Camera disturbance isolation

Camera disturbance state must not affect optical disturbance state.

### Sensor isolation

Sensor persistent defects must belong only to that sensor simulation.

### Ordering

Test that the disturbance pipeline applies stages in the documented order.

### Configuration validation

Invalid parameters must be clipped/rejected consistently.

### Compatibility

Old disturbance entry points should continue to work during migration.

---

# 21. Performance Requirements

The current simulator is designed around real-time GUI updates and optimized FOV extraction.

Do not destroy that.

Maintain:

- FOV-region rendering optimization
- no unnecessary full-scene rebuild
- no unnecessary array copies
- no unnecessary RNG creation
- cached/static state where currently used
- approximately current runtime performance

Do not move heavy work into the GUI thread unnecessarily.

---

# 22. Important Constraints

Do NOT:

- redesign the disturbance mathematics unnecessarily;
- introduce heavy scientific models;
- introduce 3D simulation;
- add unrelated new features;
- change target/tracker/controller behavior unless required by the refactor;
- change GUI appearance unnecessarily;
- remove existing controls;
- silently change units;
- silently change intensity meanings;
- silently change default values;
- introduce hidden global state;
- introduce duplicated noise application;
- create circular imports.

This is an **architecture refactor first**.

---

# 23. Documentation Requirements

Create/update documentation explaining:

1. disturbance ownership;
2. disturbance pipeline order;
3. configuration hierarchy;
4. state ownership;
5. RNG ownership;
6. reset behavior;
7. backward-compatible APIs;
8. where to add a new disturbance in the future.

Include a concise architecture diagram such as:

```text
                         DisturbanceContext
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
        Environment          Target             Camera
              │                 │                 │
              └─────────────────┼─────────────────┘
                                ▼
                           Optical Path
                                │
                                ▼
                              Sensor
                                │
                                ▼
                            Frame
                                │
                                ▼
                         Detector/Tracker
```

---

# 24. Definition of Done

The refactor is complete only when all of the following are true:

- There is no dependence on module-level disturbance state for normal operation.
- Every simulation owns its own disturbance state.
- RNG and timestep handling are explicit.
- Camera disturbances are grouped behind one camera subsystem.
- Optical disturbances are grouped behind one optical subsystem.
- Sensor/image disturbances are grouped behind one sensor subsystem.
- Target disturbances belong to target code.
- Environment conditions belong to environment code.
- Configuration mirrors ownership.
- GUI tick no longer contains individual disturbance implementation logic.
- Legacy APIs still function where practical.
- Existing functionality and defaults are preserved.
- Tests pass.
- New architecture tests pass.
- No disturbance is accidentally applied twice.
- No circular dependencies exist.
- Performance remains acceptable.
- Documentation explains how to extend the system.

---

# 25. Required Development Process

Work incrementally.

For every major refactor phase:

1. Inspect current code.
2. Implement the smallest architectural change.
3. Run relevant tests.
4. Fix regressions.
5. Only then continue.

Do not perform a blind bulk rewrite.

At the end provide:

```text
1. Files added
2. Files moved
3. Files modified
4. Files deleted
5. Old APIs preserved
6. New architecture
7. Behavioral changes, if any
8. Tests run and results
9. Performance observations
10. Any remaining technical debt
```

Most importantly:

> Preserve behavior first. Improve architecture second. Add new disturbance models later.