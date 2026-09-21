# Coarse Alignment Simulator — Bugs, Errors, Improvements, and Required Changes

**Repository:** `thisIsRajbirMajhi/Coarse-Alignment-Simulator`  
**Branch:** `Main`  
**Scope:** End-to-end coarse-alignment simulation pipeline from remote optical source generation through camera sensing, detection, validation, tracking, PID control, PTZ actuation, re-acquisition, and communication reception.

---

## 1. Executive Summary

The simulator already contains most of the intended subsystems:

- Remote-terminal motion and geometry
- Optical beacon generation
- PTZ camera plant
- Detector and Gaussian spot fitting
- Image-based tracker
- PID controller
- Search / detect / validate / select / track supervisor
- Re-acquisition ladder
- Optical and camera disturbance modules
- Communication / beacon reception
- Acceptance-test infrastructure
- Dual-viewport GUI and terminal interfaces

However, several parts of the implementation are currently disconnected from the physical signal path or use inconsistent coordinate/measurement assumptions. The most important problems are not cosmetic. They can cause the simulator to report successful acquisition/tracking under conditions where a physically coupled FSOC/PAT system should not work, or can cause recovery logic to operate in the wrong coordinate frame.

The highest-priority work is therefore to make the **camera image and photodiode signal consequences of the optical propagation model authoritative**, enforce **explicit coordinate-frame transformations**, and make **validation/tracking source-specific and multi-target aware**.

---

# 2. Priority Classification

| Priority | Meaning | Typical action |
|---|---|---|
| **P0 — Critical** | Can produce incorrect simulator behavior, false acquisition, broken re-acquisition, or physically invalid coupling | Fix before relying on end-to-end results |
| **P1 — High** | Significant realism, robustness, or control-model deficiency | Fix before final validation/benchmarking |
| **P2 — Medium** | Correctness/architecture/maintainability issue with limited immediate impact | Fix during hardening |
| **P3 — Enhancement** | Useful future capability or visualization/test improvement | Add after core correctness |

---

# 3. P0 — Critical Bugs and Errors

## 3.1 Re-acquisition Coordinate-Frame Mismatch

**Affected areas:**

- `local_terminal/reacquisition.py`
- `local_terminal/supervisor.py`
- `local_terminal/tracker.py`
- camera world/FOV coordinate transformations

### Problem

The tracker state is expressed in **FOV-local pixels**, but the re-acquisition manager treats predicted/last-known pixel coordinates as **world coordinates**.

Examples of the current mismatch:

- Supervisor passes `(tsnap.fov_x, tsnap.fov_y)` into re-acquisition.
- Re-acquisition converts that point using camera-home/world-pixel assumptions.
- Standby candidate positions are stored as FOV pixel coordinates but are later compared/used as world locations.
- Re-acquisition scan-cell centers are world coordinates but are passed to `tracker.lock_target()`, which expects FOV-local pixels.

### Consequence

The re-acquisition ladder can search the wrong area or relock the tracker using an invalid coordinate. This can appear as random acquisition failure even when the target is present.

### Required change

Define explicit coordinate-frame types and central conversion functions:

```text
FovPoint      -> camera-frame pixel coordinates
WorldPoint    -> simulation/world pixel coordinates
AnglePoint    -> PTZ pan/tilt angles
ImagePoint    -> sensor/image coordinates if different from FOV coordinates
```

Required transforms:

```text
FOV pixels <-> world pixels
world pixels <-> camera pan/tilt angles
FOV pixels <-> pan/tilt angular offset
```

Do not allow functions to accept raw `(x, y)` tuples without the frame being explicit.

### Acceptance test

A target lost at a known FOV location must be re-acquired at that same world location after camera motion, and all intermediate coordinates must round-trip within a defined tolerance.

---

## 3.2 Re-acquisition Scan Results Are Passed Back in the Wrong Frame

**Affected areas:**

- `local_terminal/reacquisition.py`
- `local_terminal/supervisor.py`
- `local_terminal/tracker.py`

### Problem

Stage 3/4 re-acquisition produces world scan locations, while tracker lock logic expects FOV-local image coordinates.

### Consequence

A successful scan result can still initialize the tracker incorrectly.

### Required change

When a scan finds a target:

```text
World detection location
        ↓
Camera world-to-FOV transform
        ↓
FOV-local centroid
        ↓
tracker.lock_target(FovPoint)
```

Never pass a world coordinate directly to the image tracker.

---

## 3.3 Escalation Scan Incorrectly Resets the Motion Model

**Affected area:**

- `local_terminal/supervisor.py`

### Problem

`escalation_scan()` calls `tracker.reset()`, which clears the α-β motion state.

The intended recovery design is to preserve useful target motion information during escalating search.

### Consequence

Re-acquisition loses the previous velocity estimate, increasing reacquisition time and potentially causing an avoidable full scan.

### Required change

Separate:

```text
reset_measurement_lock()
```

from:

```text
reset_motion_model()
```

Escalation should normally preserve:

- last position
- velocity estimate
- uncertainty trend
- target identity
- blacklist state
- valid standby candidates

unless the target model is explicitly declared invalid.

---

## 3.4 Full Reset Does Not Actually Home the Camera

**Affected areas:**

- `local_terminal/supervisor.py`
- camera integration / headless simulation loop

### Problem

The supervisor performs logical reset operations but does not own or issue an explicit camera-home command in the integrated path.

### Consequence

A nominal `FULL_RESET` can leave the physical camera at its previous pan/tilt state. The next search therefore starts from an unexpected mechanical state.

### Required change

Introduce an explicit reset command/event:

```text
Supervisor → CameraController → PTZCamera.home()
```

Home behavior should define:

- pan reference
- tilt reference
- velocity reset
- acceleration reset
- backlash state
- encoder state if appropriate
- actuator fault state

### Acceptance test

After `FULL_RESET`, camera angle and angular velocity must return to the specified home state within tolerance before the next scan begins.

---

## 3.5 Optical Pointing Error Does Not Control the Rendered Spot

**Affected areas:**

- `remote_terminal/terminal.py`
- `remote_terminal/pointing_model.py`
- `remote_terminal/beam_model.py`
- `remote_terminal/terminal_manager.py`

### Problem

Pointing error is calculated, but the rendered Gaussian spot is still effectively generated from the terminal's nominal geometry. Beam pointing error is therefore largely telemetry rather than a causal optical variable.

### Consequence

A terminal can have a large pointing error and still produce a strong, well-centered camera spot.

This can produce physically impossible acquisition/tracking results.

### Required change

Beam geometry must explicitly depend on angular pointing error:

```text
Pointing error
    ↓
beam-center offset at target plane
    ↓
beam overlap / irradiance distribution
    ↓
received optical power
    ↓
camera + photodiode signals
```

For a simple Gaussian approximation:

```text
r_offset ≈ range × tan(theta_error)
```

Then calculate irradiance/power coupling from the displaced Gaussian footprint.

---

## 3.6 Camera Image Is Not Driven by the Per-Terminal Physical Optical Channel

**Affected areas:**

- `disturbance/core/pipeline.py`
- `disturbance/optical/*`
- `remote_terminal/terminal_manager.py`
- image-rendering path

### Problem

The simulator has a `PropagationChannel`, beam wander/spread/scintillation, attenuation, turbulence, etc., but the primary image-generation path largely creates ideal Gaussian spots first and applies global image disturbances afterward.

The physical propagation result is therefore not the authoritative input to the camera sensor.

### Consequence

A disturbance can exist in the simulator but have little or no effect on the signal seen by the camera.

### Required change

Make the physical optical chain authoritative:

```text
Terminal optical emission
        ↓
Pointing / beam geometry
        ↓
Propagation channel
        ↓
Per-terminal received irradiance / field
        ↓
Atmospheric / turbulence effects
        ↓
Camera optics / PSF
        ↓
Pixel integration + exposure
        ↓
Photon statistics + read noise + defects
        ↓
ADC / image frame
        ↓
Detector
```

The renderer should visualize this same physical signal rather than generating a separate idealized approximation.

---

## 3.7 Photodiode Receiver Uses `chip_at(t)` Instead of a Physical Received Optical Signal

**Affected area:**

- `local_terminal/comm_receiver.py`

### Problem

The receiver's source-selection path identifies a nearby emitting source and directly calls its digital `chip_at(t)` function.

Actual source power, range attenuation, beam overlap, receiver aperture, wavelength response, scintillation, extinction ratio, and pointing loss are not used to generate the analog photodiode signal.

### Consequence

Communication can remain decodable even when a physical receiver should have insufficient optical power.

### Required change

Replace direct chip access with a sampled analog receive chain:

```text
P_tx
  ↓
beam / pointing coupling
  ↓
propagation attenuation
  ↓
scintillation / turbulence
  ↓
receiver aperture / FOV
  ↓
wavelength response
  ↓
photodiode responsivity
  ↓
photocurrent
  ↓
shot noise + thermal/read noise
  ↓
TIA / gain model
  ↓
ADC/sample stream
  ↓
demodulation
```

`chip_at(t)` may remain inside the **transmitter waveform generator**, but it must not be the receiver's measurement.

---

## 3.8 BER Is Injected From Camera SNR Instead of Being Derived From the Photodiode Signal

**Affected areas:**

- `local_terminal/comm_receiver.py`
- `local_terminal/supervisor.py`

### Problem

BER behavior is externally derived from the camera detection SNR rather than calculated from photodiode observations.

### Consequence

Camera and communication sensors are artificially coupled through an indirect shortcut instead of through the common optical channel.

### Required change

Derive link quality from the photodiode receiver model:

```text
received optical power
→ photocurrent
→ noise variance
→ sample SNR
→ symbol decision statistics
→ bit errors / CRC failures
```

Camera SNR and photodiode SNR should be separate measurements of the same physical optical source.

---

## 3.9 Multi-Target Sensor Attribution Is Not Source-Specific

**Affected areas:**

- `local_terminal/comm_receiver.py`
- validation / supervisor integration

### Problem

A dominant-source heuristic is used to select a single source, and CRC/validation state is not robustly associated with a specific visual candidate.

### Consequence

A frame or CRC result caused by one source can be attributed to another source when multiple emitters are present.

### Required change

Introduce a `SensorObservation` object carrying source-independent measurements:

```text
observation_id
frame_timestamp
image centroid
photodiode power
spectral / wavelength estimate
decoded bits (if any)
CRC result
signal quality
candidate association ID
```

Then associate observations with visual candidates using time, geometry, wavelength, and signal consistency.

---

## 3.10 Validation Only Effectively Processes One Detection

**Affected area:**

- `local_terminal/supervisor.py`
- `local_terminal/validator.py`

### Problem

Although the detector supports multiple candidates, supervisor logic largely feeds the first detection (`dets[0]`) into validation-related logic.

### Consequence

The system is not a true multi-candidate validation pipeline.

### Required change

For every detector candidate:

```text
candidate → CandidateTrack → beacon observation → validation state → selector score
```

The selector must then choose from all valid scored candidates.

---

# 4. P1 — High-Priority Physics and Control Improvements

## 4.1 Implement Real Beam Coupling

The received signal should include a coupling factor dependent on:

- transmitter power
- range
- beam divergence
- pointing offset
- receiver aperture
- target-plane footprint
- atmospheric attenuation
- turbulence/scintillation

A simplified normalized Gaussian coupling model is sufficient initially.

---

## 4.2 Add Receiver Aperture and Acceptance Geometry

Camera/photodiode reception should have explicit physical limits:

- aperture diameter
- optical throughput
- field-of-view / angular acceptance
- spectral bandpass
- detector responsivity
- saturation level

This prevents the communication model from seeing energy that the physical receiver cannot collect.

---

## 4.3 Model Finite OOK Extinction Ratio at the Receiver

The transmitter currently supports a non-zero low optical level in the beam model, but the receiver path reduces the waveform to a binary digital abstraction.

Implement:

```text
P_low = extinction_ratio × P_high
```

and propagate that analog level through the photodiode model.

---

## 4.4 Add Wavelength-Dependent Detector Response

The receiver should include at minimum:

- nominal wavelength
- passband
- optical filter response
- detector responsivity versus wavelength
- mismatch penalty

This also makes the spoofer/wavelength rejection test physically meaningful.

---

## 4.5 Model Camera Exposure and Temporal Integration

A 30 Hz camera should not simply take an instantaneous snapshot of a waveform evolving at ~1 ms chip intervals.

Implement:

```text
photons(t)
→ integrate over exposure interval
→ pixel charge
→ readout
```

Important parameters:

- frame period
- exposure time
- rolling/global shutter choice
- duty cycle
- chip-to-frame phase

---

## 4.6 Replace the Current PTZ First-Order Approximation With an Explicit Mechanical Model or Clearly Rename It

Current PTZ behavior is principally an acceleration-limited velocity plant with a first-order lag.

The code also uses terminology suggesting critical damping while the configured damping ratio is `0.707`.

Two valid approaches exist:

### Option A — Keep the simplified plant

Explicitly document it as:

> Acceleration-limited first-order actuator approximation.

Remove incorrect second-order/critical-damping terminology.

### Option B — Implement a second-order gimbal model

Use:

```text
J * theta_ddot + c * theta_dot + k * theta = tau_motor + tau_disturbance
```

with explicit:

- inertia
- motor torque limit
- damping
- stiffness/load torque if applicable
- rate limit
- acceleration limit
- hard stops
- backlash
- encoder model

For a robust engineering simulator, Option B is preferable when the added complexity is acceptable.

---

## 4.7 Apply Optical Turbulence Per Beam / Per Source

A global image warp is useful as a camera-side approximation, but the physical optical path should also support per-source:

- beam wander
- beam spreading
- scintillation
- attenuation
- temporal correlation

This is particularly important when multiple terminals have different ranges or pointing paths.

---

## 4.8 Implement a Physically Meaningful Power-Consistency Validation Score

The current power-consistency validation path does not receive a real expected received power and can fall back to temporal peak stability.

The preferred score should compare measurement to model:

```text
P_expected = f(P_tx, range, attenuation, beam footprint,
               pointing error, aperture, optical efficiency)
```

Then evaluate a normalized residual:

```text
power_residual = |P_measured - P_expected| / P_expected
```

The score should account for model uncertainty rather than requiring perfect agreement.

---

## 4.9 Make Loss Detection Chip-Aware

Target tracking and communication validity should account for whether a signal is physically expected during:

- OOK low symbols
- PPM empty slots
- CW emission
- frame gaps
- transmitter off intervals

A low optical measurement should not automatically be treated as target disappearance.

---

## 4.10 Improve Multi-Target Association

Current nearest-neighbor / brightest-candidate logic can select a brighter distractor when candidates are close.

Association cost should combine:

```text
motion prediction error
+ centroid distance
+ spot-size consistency
+ intensity consistency
+ wavelength consistency
+ beacon identity consistency
+ sequence continuity
```

For a limited number of candidates, a gated Hungarian assignment or equivalent global association method is appropriate.

---

## 4.11 Add Feed-Forward to the PID Controller

The tracker already estimates target motion. Use the angular velocity estimate to reduce tracking lag:

```text
u = PID(error) + feed_forward(target_angular_rate)
```

The feed-forward term should be bounded and should not bypass safety limits.

---

## 4.12 Add Explicit Control/Plant Latency Accounting

The current PID result is stored as pending output and applied on the next frame, creating approximately one frame of delay at 30 Hz.

This should be represented explicitly in the simulator timing model rather than being an accidental side effect.

---

# 5. P2 — Architecture, Consistency, and Correctness Improvements

## 5.1 Enforce the Configured Camera Update Rate

`CameraConfig.update_rate_hz = 30` currently behaves more like metadata because `dt` drives the simulation.

Use independent clocks or scheduled update loops for:

- physics
- optical waveform/chips
- photodiode sampling
- camera exposure/frame generation
- detection
- tracking
- PID
- GUI rendering

The exact rates should be configurable and deterministic.

---

## 5.2 Implement Real Modulation Choices or Remove Unsupported Modes

Configuration exposes:

- CW
- OOK
- PPM

but beacon generation currently always uses OOK encoding.

Choose one:

1. Implement CW, OOK, and PPM end-to-end, including receiver demodulation; or
2. Remove unsupported configuration options until their implementations exist.

Do not expose a mode that the simulator silently ignores.

---

## 5.3 Fix Persistent Hot-Pixel Behavior

The sensor disturbance code maintains a persistent hot-pixel cache, but the actual subset can be randomly sampled each frame when the requested number is smaller than the cache.

### Required design

Generate the persistent defect map once per sensor/pipeline reset:

```text
persistent_defects = fixed set
transient_defects = newly sampled per frame
```

Persistent defects must remain spatially fixed until an explicit reset.

---

## 5.4 Make Protocol Timing Deterministic and Explicit

Current frame/chip timing is not fully aligned with assumptions in the planning documentation.

Current implementation uses a 1 ms chip interval, while frame size can vary with payload size.

Do not hard-code assumptions such as:

```text
42 bytes
336 chips
336 ms/frame
```

unless the protocol specification actually freezes those values.

Instead expose:

```text
chip_rate
payload_length
header_length
CRC_length
framing overhead
frame_period
```

and derive watchdogs / dwell times / miss thresholds from them.

---

## 5.5 Make Tracker Miss Thresholds Time-Based

`10 misses` depends on frame rate.

Prefer:

```text
max_no_detection_time = 0.33 s
```

or a configurable time interval converted into frame counts by the active camera rate.

This keeps behavior consistent when the camera rate changes.

---

## 5.6 Strengthen Beacon Identity Coupling

Once a candidate has a validated TID, subsequent visual observations should be associated with that identity.

Identity consistency can contribute to association cost and re-acquisition.

A re-acquired target should not be considered confirmed solely because a bright spot appears near the last location; it should re-establish identity evidence according to the selected confidence policy.

---

## 5.7 Separate Truth, Observation, and Estimate in the GUI

The GUI should visibly distinguish:

### Ground truth

- actual terminal position
- actual pointing angle
- actual emitted power
- true target identity

### Sensor observations

- camera detections
- photodiode measurements
- decoded data

### Estimator state

- tracker estimate
- predicted target position
- estimated velocity
- selected target

Ground truth must never look like an autonomy output.

---

## 5.8 Update `Plan.md` to Match the Actual Implementation

The current planning document contains assumptions that no longer match the code.

Examples include:

- tracking described as telemetry-driven even though image-driven tracking exists
- physical power consistency described more strongly than implemented
- reset behavior described as preserving state differently from code
- camera update-rate enforcement not implemented
- full-reset homing not integrated

The plan should contain three clearly separated sections:

```text
Implemented
Partially implemented
Required / not yet implemented
```

This avoids planning drift.

---

# 6. P2 — Validation and Test Deficiencies

## 6.1 Current ROC Test Is Not a Real ROC Sweep

The acceptance suite contains a test described as an ROC sweep, but it effectively checks only a small number of cases rather than sweeping detector thresholds.

### Required change

Perform parameter sweeps over combinations of:

- peak threshold
- sigma threshold
- SNR threshold
- R² threshold
- isolation threshold

Evaluate at minimum:

```text
TPR / recall
FPR
precision
false candidates per frame
false acquisitions per scan
miss probability
```

Run the sweep across representative disturbance conditions.

---

## 6.2 Add Multi-Target Acceptance Tests

Required scenarios:

1. Two valid terminals separated spatially
2. Two terminals crossing in the FOV
3. One valid target + one brighter distractor
4. One valid target + spoofed wavelength
5. One valid target + intermittent emitter
6. Multiple valid targets with different beacon timing
7. Target dropout while distractor remains visible

The supervisor must keep target identity stable where expected.

---

## 6.3 Add Re-acquisition Coordinate-Transform Tests

Create deterministic unit tests for:

```text
world → FOV → world
world → angle → world
FOV → angle → FOV
```

Include points near:

- image center
- image edges
- FOV corners
- world boundaries
- pan/tilt limits

Tolerance should be explicit.

---

## 6.4 Add Physical Coupling Tests

Examples:

### Pointing loss

Increasing transmitter pointing error must monotonically reduce coupling over the relevant operating range.

### Range loss

Increasing range must reduce received irradiance according to the configured propagation model.

### Extinction ratio

OOK low symbols must produce a measurable non-zero but reduced photodiode response when finite extinction is configured.

### Atmospheric attenuation

Increasing attenuation must reduce both camera and photodiode signal levels.

### Scintillation

Scintillation should change the received intensity over time without directly changing beacon identity.

---

## 6.5 Add Camera Sensor Chain Tests

Test the complete chain:

```text
received irradiance
→ PSF
→ pixel integration
→ Poisson noise
→ read noise
→ defects
→ ADC
```

Required checks:

- photon-count variance scaling
- read-noise variance
- saturation behavior
- dark/background level
- fixed hot pixels
- transient defects
- exposure-time scaling
- deterministic seeding

---

## 6.6 Add Photodiode Receiver Tests

Test:

- wavelength mismatch
- low-power loss
- high-power saturation
- shot noise
- receiver bandwidth
- symbol timing offset
- CRC failure under controlled noise
- finite extinction ratio
- source separation
- source handoff

---

## 6.7 Add Deterministic Monte Carlo Tests

Run repeated seeds over representative environmental cases.

Recommended dimensions:

```text
seed
range
pointing error
jitter amplitude
platform motion
atmospheric attenuation
scintillation strength
sensor noise
background level
number of targets
```

Record:

- acquisition time
- probability of acquisition
- false acquisition rate
- loss rate
- re-acquisition time
- tracking RMS error
- maximum error
- command saturation percentage
- CRC success rate
- false reset rate

---

# 7. P3 — Robustness and Engineering Enhancements

## 7.1 Add Fault Injection at Every Major Layer

Fault cases should include:

### Optical source

- no emission
- intermittent emission
- incorrect wavelength
- power drift
- pointing bias

### Propagation

- severe attenuation
- scintillation burst
- turbulence burst
- beam wander

### Camera

- frozen frame
- dropped frame
- hot pixel cluster
- saturation
- elevated read noise

### Controller

- actuator saturation
- encoder bias
- encoder dropout
- backlash increase
- hard-stop hit

### Communication

- timing offset
- CRC corruption
- missing chip samples
- invalid TID
- repeated sequence number

---

## 7.2 Add Instrumentation and Telemetry

Every simulation run should be able to emit structured telemetry for:

```text
simulation_time
camera_truth_angle
camera_estimated_angle
camera_commanded_rate
tracker_position
tracker_velocity
pixel_error
PID terms
beam pointing error
received optical power
photodiode SNR
camera SNR
validation score
selected TID
supervisor state
reacquisition stage
CRC result
```

This is necessary for debugging and quantitative controller tuning.

---

## 7.3 Add Reproducibility Metadata

Every acceptance/benchmark run should record:

- random seed
- configuration hash
- git commit
- simulator version
- disturbance configuration
- protocol configuration
- camera configuration
- controller gains

This allows any result to be reproduced exactly.

---

# 8. Recommended Data Model Changes

A robust implementation should avoid passing independent primitive values between layers.

## 8.1 Candidate Observation

```python
@dataclass
class CandidateObservation:
    observation_id: int
    timestamp: float
    centroid_fov: FovPoint
    peak: float
    sigma_px: float
    r2: float
    snr_db: float
    background: float
    confidence: float
```

## 8.2 Candidate Track

```python
@dataclass
class CandidateTrack:
    track_id: int
    state: TrackLifecycle
    position_fov: FovPoint
    velocity_fov_px_s: Vector2
    covariance: Matrix
    last_seen_time: float
    misses: int
    tid: str | None
    sequence: int | None
    validation_score: float
    strike_count: int
```

## 8.3 Optical Observation

```python
@dataclass
class OpticalObservation:
    timestamp: float
    source_hint: int | None
    received_power_w: float
    wavelength_nm: float
    photodiode_current_a: float
    photodiode_snr_db: float
    sample_quality: float
```

## 8.4 Explicit Coordinate Types

```python
@dataclass(frozen=True)
class FovPoint:
    x_px: float
    y_px: float

@dataclass(frozen=True)
class WorldPoint:
    x_px: float
    y_px: float

@dataclass(frozen=True)
class PtzAngles:
    pan_deg: float
    tilt_deg: float
```

This design makes coordinate-frame mistakes much harder to introduce.

---

# 9. Recommended End-to-End Physical Architecture

The target architecture should be:

```text
REMOTE TERMINAL
    │
    ├── Motion state
    ├── Pointing model
    ├── Beacon waveform generation
    └── Optical emission
          │
          ▼
PROPAGATION / CHANNEL
    │
    ├── Range attenuation
    ├── Beam divergence
    ├── Pointing coupling
    ├── Beam wander
    ├── Beam spreading
    ├── Turbulence
    └── Scintillation
          │
          ├─────────────────────────────┐
          ▼                             ▼
CAMERA OPTICAL PATH              PHOTODIODE PATH
    │                             │
    ├── Receiver FOV              ├── Aperture
    ├── PSF / seeing              ├── Filter
    ├── Pixel integration         ├── Responsivity
    ├── Exposure                  ├── Shot noise
    ├── Poisson noise             ├── TIA / gain
    ├── Read noise                ├── Receiver bandwidth
    ├── Defects                   └── ADC / sampling
    └── ADC                              │
    │                                    ▼
    ▼                              DEMODULATOR
IMAGE FRAME                               │
    │                                    ▼
DETECTOR                            CRC / DECODER
    │                                    │
    └──────────────┬─────────────────────┘
                   ▼
            OBSERVATION FUSION
                   │
                   ▼
          VALIDATION / IDENTITY
                   │
                   ▼
              CANDIDATE TRACKS
                   │
                   ▼
              TARGET SELECTOR
                   │
                   ▼
               TRACKER
                   │
                   ▼
                 PID
                   │
                   ▼
              PTZ CAMERA
                   │
                   └────── feedback ──────► next frame
```

The key principle is that **both camera and communication observations must originate from the same propagated optical energy**, even though the sensor-specific noise, bandwidth, and response models differ.

---

# 10. Recommended Implementation Order

## Phase 1 — Correctness Fixes

1. Introduce explicit coordinate-frame types.
2. Fix re-acquisition world/FOV conversion.
3. Correct tracker initialization after scan-based reacquisition.
4. Add camera-home command to `FULL_RESET`.
5. Separate tracker measurement reset from motion-model reset.
6. Make validation multi-candidate rather than `dets[0]` only.

## Phase 2 — Physical Optical Coupling

7. Make per-terminal propagation authoritative for received power.
8. Apply pointing-error coupling to the optical field.
9. Build a physically meaningful camera optical path.
10. Replace photodiode `chip_at(t)` shortcut with an analog receive signal.
11. Derive communication errors from receiver SNR rather than camera SNR.

## Phase 3 — Sensor Fidelity

12. Add camera exposure/integration.
13. Fix persistent hot-pixel behavior.
14. Add receiver aperture/filter/responsivity.
15. Add finite OOK extinction ratio.
16. Add wavelength-dependent response.

## Phase 4 — Control and Estimation

17. Decide between a documented first-order plant and a proper second-order PTZ model.
18. Add explicit latency accounting.
19. Add target-motion feed-forward.
20. Improve multi-target association.

## Phase 5 — Protocol and Timing

21. Separate simulation clocks.
22. Make beacon timing explicit and deterministic.
23. Implement supported modulation modes completely or remove unsupported modes.
24. Convert miss/watchdog thresholds from hard-coded frame counts to time-based parameters.

## Phase 6 — Verification

25. Add coordinate transform tests.
26. Add physical coupling tests.
27. Add camera and photodiode sensor tests.
28. Replace the pseudo-ROC test with a real threshold sweep.
29. Add Monte Carlo acceptance tests.
30. Update `Plan.md` so implementation state and remaining work match the code.

---

# 11. Definition of Done

The simulator should not be considered complete until all of the following are true:

### Optical physics

- [ ] Pointing error changes received optical power.
- [ ] Range changes received optical power.
- [ ] Atmospheric attenuation changes received optical power.
- [ ] Beam spreading/wander/scintillation affect received signal.
- [ ] Camera and photodiode observe the same propagated optical source.

### Camera

- [ ] Explicit FOV/world/angle coordinate transformations exist.
- [ ] Exposure/integration is modeled.
- [ ] Photon noise and read noise are modeled.
- [ ] Persistent sensor defects remain persistent.
- [ ] Saturation behavior is defined.

### Communication receiver

- [ ] Photodiode sees analog received power rather than direct transmitter bits.
- [ ] Wavelength response is modeled.
- [ ] Receiver aperture/FOV is modeled.
- [ ] OOK extinction ratio is modeled.
- [ ] Demodulation and CRC operate on sampled receiver data.
- [ ] Communication errors are not injected directly from camera SNR.

### Tracking

- [ ] Tracker coordinates are explicitly FOV-local.
- [ ] Re-acquisition converts all scan/world coordinates before locking.
- [ ] Motion model is preserved during appropriate escalation stages.
- [ ] Multi-target association is source/candidate specific.
- [ ] Identity information can contribute to candidate association.

### Supervisor

- [ ] FULL_RESET actually homes the PTZ camera.
- [ ] Search/detect/validate/select/track/re-acquire transitions are deterministic.
- [ ] Timeouts are derived from configured rates/protocol timing.
- [ ] Reset rate limiting is tested.

### Verification

- [ ] Real ROC/threshold sweeps exist.
- [ ] Multi-target tests exist.
- [ ] Re-acquisition transform tests exist.
- [ ] Physical coupling tests exist.
- [ ] Camera sensor tests exist.
- [ ] Photodiode tests exist.
- [ ] Monte Carlo robustness tests exist.
- [ ] Runs record seeds/configuration/git commit.

---

# 12. Final Engineering Assessment

The simulator has a substantial subsystem foundation and is suitable for continued development, but its current end-to-end behavior should not yet be treated as a physically faithful FSOC/PAT coarse-alignment reference.

The most consequential architectural issue is that the simulator contains sophisticated disturbance and propagation components without consistently making their outputs the causal inputs to the camera and communication sensors. The second major issue is coordinate-frame ambiguity between image/FOV, world, and PTZ angle spaces. The third is the limited source-specific treatment of multiple candidates.

The implementation should therefore prioritize **causal signal coupling, explicit coordinate systems, sensor-specific observation models, and multi-candidate identity association** before extensive controller tuning or performance claims are made.

Once those foundations are corrected, PID tuning, disturbance sweeps, acquisition-time optimization, and ROC/Monte Carlo benchmarking will provide meaningful engineering results rather than tuning around simulator shortcuts.
