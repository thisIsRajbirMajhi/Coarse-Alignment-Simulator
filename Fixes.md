# Coarse Alignment Simulator — Re-Checked Bugs, Errors, Improvements, and Required Changes

**Repository:** `thisIsRajbirMajhi/Coarse-Alignment-Simulator`  
**Branch:** `Main`  
**Re-check commit:** `f12b70d7e06948bdce720b636aef20f021b9cf63`  
**Re-check date:** 2026-09-21  
**Scope:** End-to-end PAT/FSOC coarse-alignment simulator: remote terminal → optical source → propagation/disturbance → camera/photodiode → detection/decoding → validation → selection → tracking → PID → PTZ plant → re-acquisition/reset.

> **Important:** This document supersedes the earlier bug list. The repository has already incorporated a number of the previously recommended changes, but several are only partial implementations. This document classifies the current state from the code as it exists in commit `f12b70d`.

---

## 1. Verification Result

### Overall assessment

The simulator has improved materially since the previous review. The following areas now have concrete implementation work behind them:

- Explicit `FovPoint`, `WorldPoint`, and `PtzAngles` coordinate types.
- World/FOV/angle transform helpers.
- Re-acquisition scan results converted back to FOV coordinates before tracker lock.
- Escalation scans no longer call the full tracker reset.
- Pointing-error attenuation is now included in `BeamModel`.
- A physical photodiode SNR/BER calculation exists.
- Persistent hot-pixel maps are now cached as fixed spatial defects.
- Additional coordinate, optical-coupling, photodiode, and re-acquisition tests were added.
- Configurable remote-terminal start offsets and camera start poses were added.

However, several central claims made by the current `Fixes.md` are stronger than what the implementation actually guarantees.

### Current status by severity

| ID | Area | Current status | Severity |
|---|---|---|---|
| C-01 | Re-acquisition coordinate frames | **Fixed structurally, with remaining logic issues** | P1 |
| C-02 | Re-acquisition scan → tracker FOV conversion | **Fixed** | P1 |
| C-03 | Escalation preserving tracker motion model | **Fixed** | P1 |
| C-04 | `FULL_RESET` actually homes PTZ in integrated path | **Not fixed** | **P0** |
| C-05 | Pointing error affects optical strength | **Partially fixed** | P1 |
| C-06 | Physical propagation drives camera image | **Not fixed** | **P0** |
| C-07 | Photodiode observes physical analog optical waveform | **Not fixed** | **P0** |
| C-08 | BER no longer shortcut from camera SNR | **Partially fixed** | **P0** |
| C-09 | Source-specific communication/visual attribution | **Not fixed** | **P0** |
| C-10 | Multi-candidate validation/selection pipeline | **Not fixed** | **P0** |
| C-11 | Photodiode source metadata reaches receiver | **Broken integration** | **P0** |
| C-12 | Wavelength spoofing acceptance test | **Invalid test setup** | **P0** |
| C-13 | Re-acquisition local-search gate | **Logic defect remains** | P1 |
| C-14 | Provisional re-acquisition gate | **Too weak** | P1 |
| C-15 | PTZ mechanical model | **Still simplified and dimensionally questionable** | P1 |
| C-16 | Camera update-rate enforcement | **Not implemented as an independent clock** | P2 |
| C-17 | Camera exposure / radiometric image formation | **Not implemented** | P1 |
| C-18 | Modulation support (CW/OOK/PPM) | **Configuration exceeds implementation** | P1 |
| C-19 | ROC sweep | **Still not a real ROC sweep** | P1 |
| C-20 | Truth vs observation GUI separation | **Still mixed** | P2 |
| C-21 | Photodiode comment/code oversampling mismatch | **Documentation defect** | P2 |
| C-22 | Protocol timing/watchdog assumptions | **Still partially hard-coded** | P2 |
| C-23 | Multi-target association | **Still nearest/brightest gated candidate** | P1 |
| C-24 | Physical power-consistency validation | **Still not fully implemented** | P1 |

---

# 2. What Is Actually Fixed

## 2.1 Explicit coordinate-frame model

**Files:**

- `common/coordinates.py`
- `local_terminal/reacquisition.py`
- `local_terminal/supervisor.py`
- `tests/test_coordinates.py`
- `tests/test_reacquisition_coords.py`

The new typed frames are a significant improvement:

```text
FovPoint
WorldPoint
PtzAngles
```

and helper transforms now exist for:

```text
world ↔ FOV
world ↔ PTZ angle
FOV → PTZ angle
```

This addresses the original raw-tuple ambiguity.

### Remaining caveat

The code still allows raw `(x, y)` tuples at public APIs. The new types are available, but the architecture does not yet enforce them everywhere. A future bug can therefore still be introduced by passing an untyped tuple into a function expecting another frame.

### Required hardening

Move toward APIs that accept the explicit point types and only serialize to tuples at integration boundaries.

---

## 2.2 Re-acquisition scan results are returned as FOV coordinates

The previous world-coordinate → tracker-coordinate defect was addressed in Stage 3/4 of `ReacquisitionManager`.

When a scan finds the target without an explicit detector point, the scan world location is converted through `world_to_fov(...)` before being returned to the supervisor.

This is correct architectural behavior.

---

## 2.3 Escalation no longer destroys the motion model

`AutonomySupervisor.escalation_scan()` now calls:

```python
self.tracker.reset_measurement_lock()
```

instead of a full tracker reset.

`reset_measurement_lock()` preserves the α-β motion model, velocity, and uncertainty.

This is consistent with the intended escalation behavior.

---

## 2.4 Pointing-error attenuation exists in the beam model

`remote_terminal/optics.py` now calculates a Gaussian-style pointing coupling and reduces emitted instantaneous power accordingly.

Conceptually:

```text
pointing error
→ beam displacement
→ coupling loss
→ reduced optical power
```

This is an important improvement over the prior telemetry-only pointing error.

### Remaining caveat

Only the **power amplitude** is currently attenuated in the rendered marker path. The spot center is still placed at the nominal terminal position. Therefore pointing error is not yet modeled as a spatially displaced beam footprint at the receiver plane.

---

## 2.5 A physical photodiode SNR calculation exists

`local_terminal/comm_receiver.py` now contains an explicit calculation using:

- optical power
- beam diameter
- pointing coupling
- atmospheric transmission
- receiver aperture
- optical filter response
- wavelength response
- photodiode responsivity
- shot noise
- thermal noise
- electrical SNR
- BER

This is much closer to the desired architecture.

### Critical integration problem

The end-to-end simulation does **not consistently populate these fields** when constructing `CommSource`. See Section 5.1.

---

## 2.6 Persistent hot-pixel caching was improved

`disturbance/sensor/image_noise.py` now creates a persistent defect map instead of independently choosing the persistent coordinates every frame.

The intended split is now:

```text
persistent defects → fixed spatial positions
transient defects  → newly sampled per frame
```

This addresses the original persistence bug.

### Remaining caveat

The defect map uses randomized integer coordinates without explicit collision rejection. Duplicate coordinates reduce the effective defect count slightly. This is minor compared with the original persistence issue.

---

# 3. P0 — Critical Current Defects

# 3.1 `FULL_RESET` does not home the actual integrated PTZ camera

**Files:**

- `local_terminal/supervisor.py`
- `gui/application/session.py`
- `simulation/headless.py`
- `camera/ptz.py`

The supervisor's `full_reset()` now sets:

```python
self._hold_target_angles = (0.0, 0.0)
```

but it does not issue a direct camera reset/home command.

The actual camera API does have:

```python
PTZCamera.reset()
```

and `reset()` correctly resets position, velocity, acceleration, backlash, target state, and encoder cache.

The problem is that the **autonomy supervisor reset path is not coupled to that camera method**.

In the normal session loop, `camera_target_angles` can remain `None` after `full_reset()`, which does not guarantee an actual physical return to home.

### Required fix

Add an explicit supervisor output/event:

```text
Supervisor
    ↓
CameraResetCommand(home/custom-start)
    ↓
PTZCamera.reset(...)
```

Do not depend on an internal `_hold_target_angles` side effect.

### Acceptance condition

Immediately after a full reset:

```text
pan  = configured home/start angle ± tolerance
 tilt = configured home/start angle ± tolerance
rate = 0 ± tolerance
accel = 0 ± tolerance
```

before search resumes.

---

# 3.2 The camera image is still not driven by the per-terminal propagation model

**Files:**

- `disturbance/core/pipeline.py`
- `simulation/headless.py`
- `gui/application/session.py`
- `remote_terminal/scenario.py`
- `disturbance/optical/*`

The code contains a proper propagation API:

```python
DisturbancePipeline.propagate_beam(...)
```

but the normal image-generation path still does:

```text
remote.render_spots(world_frame)
        ↓
whole-image optical disturbance
        ↓
whole-image sensor noise
        ↓
camera crop
```

rather than:

```text
per-terminal emission
        ↓
per-terminal propagation
        ↓
received irradiance field
        ↓
camera optical formation
        ↓
pixel integration
        ↓
sensor model
```

Therefore the existing propagation subsystem is not yet the authoritative causal source for the camera image.

### Consequence

The simulator can expose a propagation disturbance configuration without guaranteeing that the disturbance physically changes the received terminal field in the way expected by an FSOC link.

### Required fix

Make each terminal produce a propagated optical field or received-power map, then composite those fields before the camera sensor stage.

---

# 3.3 The photodiode still obtains digital chips directly from `chip_at(t)`

**File:** `local_terminal/comm_receiver.py`

The receiver now computes a physical SNR, but `_dominant_chip()` still calls:

```python
best.chip_at(t)
```

and directly creates a digital `0/1` sample stream.

The physical SNR is then converted into BER and bit flips are optionally injected into those already-digital chips.

That is not the same thing as:

```text
optical waveform
→ received optical power(t)
→ photocurrent(t)
→ noise
→ analog sampled signal
→ threshold/demodulation
→ bits
```

### Required fix

Keep `chip_at(t)` only inside the transmitter waveform source.

The receiver should receive a source model capable of evaluating received optical power at time `t` and then generate the sampled analog signal internally.

---

# 3.4 The physical photodiode model is not connected correctly to the end-to-end source metadata

**Files:**

- `gui/application/session.py`
- `simulation/headless.py`
- `local_terminal/comm_receiver.py`

The end-to-end code constructs `CommSource` with only a subset of the physical fields:

```python
position
emitting
power_w
chip_at
```

but the physical receiver expects important values such as:

```text
wavelength_nm
beam_diameter_m
range_m
pointing_error_deg
atm_transmission
```

Those are not populated by the normal session/headless construction path.

### Result

The receiver's detailed formulas can silently fall back to defaults such as:

```text
range = 0
beam diameter = 0
wavelength = 1550 nm
pointing error = 0
atmospheric transmission = 1
```

This defeats most of the new physical receive model during actual end-to-end operation.

### Required fix

Create one authoritative sensor-facing source object populated directly from `RemoteTerminalRuntime`, e.g.:

```python
CommSource(
    position=...,
    emitting=...,
    tx_power_w=...,
    wavelength_nm=...,
    range_m=...,
    beam_diameter_m=...,
    pointing_error_deg=...,
    atm_transmission=...,
    chip_at=...,
)
```

Do not rely on defaults for values that are available from the remote terminal runtime.

---

# 3.5 Power semantics can be double-counted after the receiver integration is fixed

The current remote terminal runtime's `instantaneous_power_w` already includes pointing coupling from `BeamModel`.

The photodiode model separately contains a pointing-coupling term.

If the future integration simply passes `instantaneous_power_w` as `p_tx` **and** also passes `pointing_error_deg`, pointing loss will be applied twice.

### Required design decision

Choose one canonical semantic:

### Recommended

```text
P_tx = transmitter source power before link losses
pointing_error = separate state
beam geometry = separate state
channel = applies coupling exactly once
```

Then derive:

```text
P_rx = Link(P_tx, geometry, pointing, range, atmosphere, receiver)
```

Do not pass already-received power into a function that treats it as transmitter power.

---

# 3.6 Communication source attribution is still not robust for multiple emitters

`CommReceiver._dominant_chip()` selects the nearest emitting source to the photodiode boresight.

That is an explicit simplification, but it is not adequate for a multi-terminal simulator where multiple beams can overlap the receiver.

### Current limitation

The model does not perform:

```text
P_total(t) = Σ P_rx,i(t)
```

followed by physical waveform interference/capture behavior.

### Consequence

A strong nearby source can effectively replace the true target without the receiver modeling the analog superposition.

### Required improvement

At minimum support:

- per-source received power
- aggregate received power
- capture-effect threshold if desired
- source handoff
- wavelength discrimination
- source-specific association

A full physical coherent optical interference model is not required for the coarse simulator, but analog power superposition is.

---

# 3.7 Multi-candidate validation is still not actually multi-candidate

The detector can produce multiple detections, and `TargetSelector` accepts a list.

However, `AutonomySupervisor` still selects a single detection (`best_det`) and maintains a single pending validation snapshot:

```python
self._pending_validation_snap
```

Therefore the system is still effectively:

```text
many detections
    ↓
choose one
    ↓
validate one
    ↓
select one
```

rather than:

```text
many detections
    ↓
many candidate tracks
    ↓
many decode/identity observations
    ↓
many validation states
    ↓
selector
```

### Required architecture

Implement `CandidateTrack` objects with:

- candidate ID
- centroid
- motion state
- validation state
- TID
- sequence history
- strike count
- wavelength evidence
- photometric history
- score
- age/timeout

Then let `TargetSelector` operate over all current candidate tracks.

---

# 3.8 Ground-truth fallback is still mixed into the GUI target marker logic

**File:** `gui/core/renderer.py`

The renderer first uses autonomy telemetry, but it also has a fallback path that directly projects the remote terminal telemetry into the camera FOV.

That is useful for debugging, but it can visually resemble an autonomy estimate.

### Required fix

Label the overlays explicitly:

```text
TRUTH
OBSERVATION
ESTIMATE
COMMAND
```

and allow the truth layer to be turned off.

Ground-truth terminal positions should never be the implicit fallback for the autonomy tracker display in an operational-looking view.

---

# 4. P1 — Major Physics Deficiencies

# 4.1 Pointing error should affect both power and beam position

Current improvement:

```text
pointing error → lower optical power
```

Still missing:

```text
pointing error → beam-center displacement at receiver plane
```

Use a geometric approximation such as:

```text
Δr = R × tan(θ_error)
```

and use that offset in the received field calculation.

---

# 4.2 Beam-width convention is not yet fully calibrated

`spot_size_mrad` is documented as a **full angular width**, but the coupling equation treats half the beam diameter as a Gaussian waist-like radius.

For quantitative FSOC studies, explicitly define whether the width is:

- full geometric width
- 1/e radius
- 1/e² radius
- FWHM
- full divergence angle
- half-angle divergence

Then derive all downstream equations from that single convention.

---

# 4.3 Camera image formation is still not radiometric

Current path remains largely:

```text
uint8 image intensity
→ image disturbance
→ detector
```

A higher-fidelity chain should be:

```text
received irradiance
→ optical PSF / seeing
→ exposure integration
→ photons per pixel
→ Poisson shot noise
→ read noise
→ dark current / background
→ defects
→ gain / offset
→ ADC saturation / quantization
→ observed image
```

The current implementation has noise stages, but does not yet have a physically parameterized exposure/photon/gain/ADC chain.

---

# 4.4 Exposure time is still missing

The camera operates at 30 Hz, while the beacon chip timing is approximately 1 kHz.

A camera frame therefore integrates over many chip intervals unless exposure is deliberately shorter.

The simulator should expose:

```text
frame_period_s
exposure_time_s
readout_time_s
shutter_mode
```

and compute the optical energy collected during exposure.

---

# 4.5 Turbulence and propagation are still not per-source causal fields

The disturbance library contains advanced optical functions, but the main image path still applies image-level effects after the remote Gaussian marker is generated.

For multiple ranges and multiple beams, a stronger model is:

```text
beam 1 → propagation 1 → field 1
beam 2 → propagation 2 → field 2
beam 3 → propagation 3 → field 3
                         ↓
                 sum received fields/powers
                         ↓
                  camera optics
```

This is especially important when terminals differ in range, beam width, wavelength, or pointing state.

---

# 4.6 Photodiode receiver FOV should be angular rather than an arbitrary pixel radius

The current receiver uses:

```python
rx_fov_radius_px=320
```

This ties the receiver geometry to a world-pixel distance rather than a physical optical acceptance angle.

Prefer:

```text
receiver FOV half-angle
camera/diode boresight angle
source angular offset
```

and derive acceptance from angle.

---

# 4.7 Wavelength response is implemented but not end-to-end connected

`CommReceiver` contains a wavelength-dependent filter response, but the normal integration path does not pass each terminal's wavelength into `CommSource`.

Therefore a runtime wavelength mismatch can be invisible to the receiver.

This is directly related to the invalid spoofer acceptance test described later.

---

# 4.8 OOK finite extinction exists in parts of the model but not in the actual analog receive waveform

`BeamModel` uses approximately:

```text
high = 1.0 × P
low  = 0.45 × P
```

and `compute_photodiode_snr()` repeats the low-level assumption.

The actual sampled waveform, however, is still generated as a digital chip from `chip_at(t)`.

The analog low/high levels must exist in the receiver waveform before demodulation.

---

# 4.9 CW and PPM remain exposed but beacon encoding is still OOK

`RemoteTerminalConfig` exposes:

```text
CW
OOK
PPM
```

but `BeaconGenerator` still instantiates `OOKEncoder()` unconditionally.

`BeamModel` can change the optical-power semantics based on the configured modulation, but that does not create a true CW or PPM protocol waveform.

### Required action

Either:

1. implement CW/OOK/PPM end-to-end, including receiver demodulation; or
2. remove unsupported choices from the GUI/configuration until implemented.

Never present a mode as supported when it silently generates OOK data.

---

# 5. P1 — Current Control / Tracking Problems

# 5.1 Re-acquisition Stage 1 checks distance from FOV center, not from the predicted target location

**File:** `local_terminal/reacquisition.py`

The code computes:

```python
pred_fov = FovPoint(pred_x, pred_y)
```

and slews toward it, but the detection gate is effectively:

```text
distance(detection, FOV_center) <= current_radius
```

rather than:

```text
distance(detection, predicted_target_location) <= current_radius
```

### Consequence

A detection elsewhere in the FOV may be accepted simply because it is close to the camera boresight, even though it is far from the predicted target state.

### Required fix

Use:

```python
distance = hypot(
    det.fov_x - pred_x,
    det.fov_y - pred_y,
)
```

and gate against the predicted position.

---

# 5.2 Provisional re-acquisition gate is weaker than the intended identity gate

The current provisional gate is effectively:

```text
photometric detection
        ↓
wait for CRC of target TID
```

The intended robust gate should include at least:

```text
photometric detection
+ expected motion/location consistency
+ target identity evidence when available
+ communication confirmation
```

### Required behavior

Do not allow a generic bright spot in the search region to become a strong provisional lock without geometric/motion consistency.

---

# 5.3 Multi-target tracking still uses brightest gated detection

The tracker currently does approximately:

```text
predict
→ gate detections
→ choose brightest gated detection
```

That is vulnerable to a bright distractor entering the same gate.

### Required association cost

Use a combined score from:

```text
prediction distance
+ centroid continuity
+ spot size
+ intensity consistency
+ wavelength
+ TID
+ sequence continuity
```

For ≤8 candidates, a gated global assignment method is practical.

---

# 5.4 Identity is not yet used strongly enough during visual association

The tracker now stores an active terminal ID, but detector association is still primarily geometric/photometric.

The identity signal should actively constrain candidate matching after a target is validated.

---

# 5.5 PID feed-forward exists in the controller API but is not actually wired from tracker velocity

`PIDController.compute_from_pixels()` accepts:

```python
target_vel_x_px_s
target_vel_y_px_s
```

but the session/headless control calls do not populate these from the tracker model.

Therefore the feed-forward mechanism exists structurally but is effectively unused in the normal path.

### Required fix

Pass the tracker/α-β velocity estimate into the PID call after converting to angular rate.

---

# 5.6 PID-to-camera latency is still implicit

The control path has a pending command mechanism:

```text
frame k observation
→ compute
→ command applied around frame k+1
```

This is real latency, but it is not modeled as an explicit control-loop delay parameter.

### Required improvement

Make delay explicit and measurable:

```text
sensor latency
controller latency
actuator update latency
```

Then include those values in telemetry and controller tuning tests.

---

# 5.7 PTZ mechanical model remains a simplified kinematic/lag model

**File:** `camera/ptz.py`

The current axis update is still fundamentally:

- command velocity
- acceleration limit
- velocity limit
- first-order lag
- backlash
- position limits

The comment refers to an “equivalent” mechanical model, but the time constant is derived using:

```text
inertia / damping_ratio
```

which is dimensionally inconsistent because a damping ratio is dimensionless, not a damping coefficient.

### Required decision

Either:

### Option A — Keep the simplified model

Document it honestly as:

> acceleration-limited velocity actuator with first-order lag and backlash.

Remove claims that it is a physically parameterized second-order gimbal.

### Option B — Implement a real second-order plant

Use a model such as:

```text
J θ¨ + c θ˙ + k θ = τ_motor + τ_disturbance
```

with explicit motor torque, damping, inertia, and limits.

For an FSOC/PAT engineering simulator, Option B is preferred when the added complexity is acceptable.

---

# 5.8 Damping terminology is incorrect

The configuration and preset text refer to approximately `0.707` as “critical damping.”

For a conventional second-order system:

```text
ζ = 1.0 → critical damping
ζ ≈ 0.707 → underdamped / Butterworth-like design point
```

This should be corrected throughout comments, presets, and documentation.

---

# 6. P2 — Timing and Protocol Deficiencies

# 6.1 Camera update rate is still not independently enforced

`CameraConfig.update_rate_hz = 30` is configured, but the simulation loop still advances according to its `dt`.

This means the camera rate is not an independent clock.

### Recommended timing domains

```text
physics clock
optical chip clock
photodiode sample clock
camera frame clock
tracker clock
PID clock
GUI/render clock
```

These do not all need different implementation threads; deterministic scheduled substeps are sufficient.

---

# 6.2 Beacon frame duration is payload-derived, but watchdog assumptions remain partly hard-coded

Beacon frames are variable-length because payload size can vary with fields such as terminal ID.

The receiver/supervisor contains values such as:

```text
0.672 s
```

which are described as approximately two beacon periods.

### Required fix

Derive watchdogs from the actual generated frame period:

```text
frame_period = chip_count × chip_duration
watchdog = N × frame_period
```

or define the protocol as fixed-length and enforce that length.

---

# 6.3 Miss thresholds should be time-based

A threshold such as:

```text
10 misses
```

changes meaning when the camera frame rate changes.

The tracker now has a `max_no_detection_time_s` field, which is an improvement, but all higher-level watchdogs should consistently be expressed in physical time rather than hard-coded frame counts.

---

# 6.4 Receiver comments still say 4× oversampling while the implementation uses 8×

`SUBS_PER_CHIP = 8`, but the module header still describes 4× oversampling in places.

Update comments/docstrings so the implementation and documentation agree.

---

# 7. P1 — Validation Problems

# 7.1 Physical power-consistency score is still incomplete

The validator supports an `expected_peak` input, but the end-to-end supervisor does not currently supply an expected radiometric peak derived from the optical link model.

Therefore the validator can still fall back to temporal peak stability rather than true physical power consistency.

### Required fix

Generate expected received power from the same authoritative link model used by the camera/photodiode:

```text
P_expected = LinkModel(P_tx, range, beam, pointing, atmosphere, receiver)
```

Then compare measured versus expected with an uncertainty-aware score.

---

# 7.2 Navigation/signature capabilities are not fully enforced

The registry supports `require_nav`, but the validator's decode path does not fully enforce every expected capability/signature field.

At minimum, validate the mission-defined signature set consistently:

- TID
- wavelength
- sequence continuity
- required capabilities
- required navigation payload/state
- self-ID rejection
- CRC

---

# 7.3 CRC failures are still global rather than candidate-specific

The supervisor obtains a single receiver parse result and a global CRC-failure counter.

With multiple emitters, a CRC failure caused by one source can influence validation state associated with another visual candidate.

### Required fix

Tie communication observations to candidate tracks by:

- time
- source angle / centroid
- wavelength
- expected identity
- photodiode signal strength

before applying strikes.

---

# 8. P0 — Acceptance/Test Defects

# 8.1 Spoofer rejection test does not actually pass the spoofed wavelength to `CommSource`

**File:** `tests/test_acceptance.py`

The spoofer creates:

```python
BeaconGenerator("RT-001", 1200.0)
```

but the `CommSource` used by the test only passes:

```python
position
emitting
power_w
chip_at
```

and therefore defaults to the receiver's nominal wavelength.

### Consequence

The test does not actually exercise the intended 1200 nm wavelength mismatch.

### Required fix

Pass:

```python
wavelength_nm=1200.0
```

and preferably all other sensor-facing link parameters as well.

---

# 8.2 The ROC test is still not a ROC sweep

The current test is described as a ROC sweep but only validates:

- one clean Gaussian spot
- one small-artifact rejection case

It does not sweep the detector thresholds.

### Required sweep

Sweep at least:

- peak threshold
- sigma threshold
- SNR threshold
- R² threshold
- isolation threshold

and calculate:

```text
TPR / recall
FPR
precision
false candidates / frame
false acquisitions / scan
```

across multiple disturbance conditions.

---

# 8.3 Missing multi-target acceptance tests

The current acceptance suite should add:

1. two valid targets
2. crossing targets
3. bright distractor
4. spoofed wavelength
5. intermittent emitter
6. target dropout with distractor present
7. multiple valid beacon streams
8. source handoff

---

# 8.4 Missing full-reset camera-homing acceptance test

Add a test that:

1. drives camera away from home;
2. triggers `full_reset()`;
3. steps the integrated simulation;
4. verifies the actual `PTZCamera` state is at home/start;
5. verifies velocity and acceleration are zero.

---

# 8.5 Missing end-to-end physical coupling acceptance tests

Required tests:

### Range

Increasing range must reduce received signal.

### Pointing

Increasing pointing error must reduce received signal and move the beam footprint.

### Atmosphere

Increasing attenuation must reduce both camera and diode observations.

### Scintillation

Scintillation must vary received power temporally.

### Wavelength

A mismatched wavelength must reduce detector response and/or cause validation rejection according to the configured filter/mission rules.

---

# 8.6 Missing analog photodiode waveform tests

The current tests verify a calculated SNR and that a parse can succeed, but do not test the full analog chain.

Add tests for:

- high/low optical levels
- finite extinction
- shot-noise variance
- thermal noise
- threshold margin
- timing offset
- sample jitter
- symbol errors
- CRC failure probability

---

# 8.7 No explicit camera exposure tests

Add tests for:

- exposure-time scaling
- short exposure vs long exposure
- target motion during exposure
- chip-to-frame phase
- saturation
- dark background

---

# 9. P2 — GUI and Visualization Corrections

The dual-viewport architecture is useful, but the visualization contract should explicitly distinguish:

## Ground truth

- terminal world position
- true PTZ state
- true pointing error
- true emitted power
- true beacon state

## Sensor observation

- observed image
- detected spot
- measured SNR
- photodiode measurement
- decoded beacon

## Estimate

- tracker position
- tracker velocity
- predicted position
- validation state
- selected target

## Command

- PID rate command
- target angle command
- reset/home command

The operator-facing camera view should never silently substitute ground truth for missing autonomy data.

---

# 10. Recommended Correct Data Flow

The target architecture should now be treated as:

```text
REMOTE TERMINAL
    │
    ├── trajectory / position
    ├── pointing state
    ├── beacon waveform
    └── TX optical power
          │
          ▼
PER-TERMINAL OPTICAL LINK MODEL
    │
    ├── range geometry
    ├── beam divergence
    ├── pointing displacement
    ├── pointing coupling
    ├── attenuation
    ├── turbulence / wander
    ├── scintillation
    └── wavelength/filter effects
          │
          ├──────────────────────────────────┐
          ▼                                  ▼
CAMERA RECEIVER FIELD                PHOTODIODE RECEIVER
    │                                  │
    ├── aperture                       ├── aperture
    ├── optics / PSF                   ├── optical filter
    ├── seeing                         ├── wavelength response
    ├── exposure                       ├── responsivity
    ├── pixel integration              ├── shot noise
    ├── photon noise                   ├── thermal noise
    ├── read noise                     ├── bandwidth
    ├── defects                        ├── analog gain/TIA
    └── ADC                            └── ADC/sample
    │                                  │
    ▼                                  ▼
IMAGE DETECTOR                    DEMODULATOR / CRC
    │                                  │
    └───────────────┬──────────────────┘
                    ▼
             OBSERVATION FUSION
                    │
                    ▼
          CANDIDATE / IDENTITY TRACKS
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
               PTZ ACTUATOR
                    │
                    └──────── feedback ────────► next camera frame
```

### Key engineering rule

The camera and photodiode must receive **two sensor-specific observations of the same propagated optical energy**.

They must not be separately generated from unrelated shortcuts.

---

# 11. Recommended Implementation Order

## Phase 1 — Close the remaining P0 integration gaps

1. Add complete `CommSource` physical metadata propagation from remote terminal runtime.
2. Separate `tx_power_w` from `received_power_w` semantics.
3. Connect `FULL_RESET` to an explicit `PTZCamera.reset()` command/event.
4. Remove digital `chip_at()` as the receiver measurement and replace it with an analog received-power waveform.
5. Make camera image generation use the per-terminal propagation model.
6. Associate communication observations with specific candidate tracks.
7. Implement true multi-candidate validation.
8. Fix the wavelength-spoofer acceptance test.

## Phase 2 — Fix remaining re-acquisition/control logic

9. Gate re-acquisition around the predicted target, not the FOV center.
10. Strengthen provisional re-acquisition with geometric/motion consistency.
11. Wire tracker velocity into PID feed-forward.
12. Explicitly model sensor/controller/actuator latency.
13. Improve target association beyond brightest-gated candidate.

## Phase 3 — Complete sensor physics

14. Add camera exposure integration.
15. Add radiometric photon/gain/ADC units.
16. Add receiver angular FOV.
17. Define/calibrate beam-width convention.
18. Add wavelength response end-to-end.
19. Apply beam-center displacement from pointing error.
20. Add per-terminal turbulence/scintillation to the received optical field.

## Phase 4 — Protocol and timing

21. Enforce independent simulation clocks.
22. Derive watchdogs from actual beacon/frame timing.
23. Implement or remove CW/PPM.
24. Convert all critical miss/watchdog logic to time-based quantities.

## Phase 5 — Verification

25. Implement real detector threshold sweeps.
26. Add multi-target acceptance tests.
27. Add physical link-coupling tests.
28. Add analog photodiode tests.
29. Add full-reset homing tests.
30. Run deterministic Monte Carlo campaigns.
31. Update `Fixes.md` and `Plan.md` to separate `Implemented`, `Partial`, and `Not Implemented` claims.

---

# 12. Recommended Refactoring Targets

## 12.1 Introduce a single authoritative sensor-facing optical source object

Example:

```python
@dataclass
class OpticalLinkSource:
    terminal_id: str
    position_world: WorldPoint
    tx_power_w: float
    wavelength_nm: float
    modulation: ModulationType
    beam_diameter_m: float
    range_m: float
    pointing_error_deg: float
    atmospheric_transmission: float
    chip_at: Callable[[float], int]
```

This object should be created once per terminal per simulation tick and reused by:

- camera optical formation
- photodiode receiver
- telemetry

That prevents the camera and communication paths from receiving inconsistent source physics.

---

## 12.2 Introduce `CandidateTrack`

Recommended fields:

```python
@dataclass
class CandidateTrack:
    track_id: int
    lifecycle: str
    fov_position: FovPoint
    world_position: WorldPoint | None
    velocity_px_s: tuple[float, float]
    uncertainty_px: float
    terminal_id: str | None
    last_sequence: int | None
    wavelength_nm: float | None
    validation_score: float
    strikes: int
    last_seen_s: float
    last_decode_s: float | None
```

The selector should consume these objects rather than a single global validation snapshot.

---

## 12.3 Separate link physics from sensor physics

### Link model owns

- TX power
- beam divergence
- range
- pointing
- atmospheric attenuation
- beam wander
- scintillation
- received irradiance/power

### Camera owns

- aperture
- optics
- PSF
- exposure
- pixel integration
- camera noise
- ADC

### Photodiode owns

- aperture
- filter
- responsivity
- bandwidth
- shot noise
- thermal noise
- gain
- ADC
- demodulation

This separation prevents duplicated attenuation or noise terms.

---

# 13. Definition of Done

## Optical link

- [ ] TX and RX power semantics are explicitly separated.
- [ ] Range affects received power.
- [ ] Pointing affects coupling.
- [ ] Pointing shifts the received beam footprint.
- [ ] Atmospheric attenuation affects received power.
- [ ] Turbulence/scintillation affect the optical field.
- [ ] Wavelength is carried end-to-end.

## Camera

- [ ] Camera observes propagated optical energy rather than ideal terminal markers.
- [ ] Exposure time is modeled.
- [ ] Pixel integration is modeled.
- [ ] Photon statistics are tied to optical energy.
- [ ] Read noise is modeled.
- [ ] Persistent defects remain fixed.
- [ ] ADC gain/offset/saturation are defined.

## Photodiode

- [ ] No direct transmitter-bit shortcut in the measurement path.
- [ ] Analog receive power exists before demodulation.
- [ ] Wavelength response is applied.
- [ ] Receiver angular FOV is applied.
- [ ] Aperture is applied.
- [ ] Shot and thermal noise are applied.
- [ ] Finite extinction ratio is applied to the waveform.
- [ ] CRC errors emerge from sampled receiver degradation.

## Autonomy

- [ ] Multiple detections become multiple candidate tracks.
- [ ] Multiple candidates can be independently validated.
- [ ] Candidate identity is used in association.
- [ ] Re-acquisition gates around predicted state.
- [ ] Re-acquisition uses explicit coordinate frames.
- [ ] Escalation preserves useful motion state.
- [ ] Full reset physically homes the PTZ.

## Controller

- [ ] PTZ dynamics are either physically parameterized or explicitly documented as an approximation.
- [ ] Damping terminology is correct.
- [ ] Feed-forward is actually connected.
- [ ] Latency is explicit.
- [ ] Rate/acceleration/saturation behavior is tested.

## Verification

- [ ] Real ROC threshold sweeps exist.
- [ ] Multi-target tests exist.
- [ ] Wavelength-spoofer test passes the actual spoofed wavelength.
- [ ] Re-acquisition coordinate tests exist.
- [ ] Full-reset homing test exists.
- [ ] Camera sensor-chain tests exist.
- [ ] Photodiode analog tests exist.
- [ ] Physical-link coupling tests exist.
- [ ] Deterministic Monte Carlo tests exist.
- [ ] Benchmark runs record seed, configuration, and git commit.

---

# 14. Final Re-check Conclusion

The current `f12b70d` commit is **not merely the same implementation as the previous review**. Several recommended corrections have been implemented, especially coordinate handling, escalation behavior, pointing-power coupling, persistent sensor defects, and preliminary photodiode physics.

However, the most important remaining problem is architectural:

> **The simulator still contains multiple physical models that are not yet the authoritative source of the sensor observations used by the autonomy stack.**

The three highest-risk gaps are now:

1. **The actual end-to-end `CommSource` integration does not carry the physical terminal/link metadata needed by the new photodiode model.**
2. **The photodiode receiver still decodes a digital `chip_at(t)` stream rather than demodulating an analog received optical waveform.**
3. **The camera image is still generated from idealized rendered terminal spots rather than from the per-terminal propagated optical field.**

Those should be resolved before using the simulator to make quantitative claims about FSOC/PAT acquisition probability, tracking robustness, false acquisition rate, communication reliability, or controller performance under realistic disturbances.

Once those are corrected, the next validation step should be a deterministic multi-target Monte Carlo campaign combining:

```text
range
+ pointing error
+ atmospheric attenuation
+ turbulence/scintillation
+ platform jitter
+ sensor noise
+ motion
+ multi-target clutter
+ wavelength spoofing
+ communication timing errors
```

and reporting:

```text
acquisition probability
acquisition time
tracking RMS / max error
loss probability
re-acquisition time
false acquisition rate
CRC success rate
controller saturation
reset/fault rate
```

That is the point at which the simulator becomes a meaningful engineering benchmark rather than primarily a subsystem integration demonstrator.

---

## Appendix A — Files Re-checked in the Current Commit

### Core autonomy / tracking

- `local_terminal/supervisor.py`
- `local_terminal/reacquisition.py`
- `local_terminal/tracker.py`
- `local_terminal/validator.py`
- `local_terminal/selector.py`
- `local_terminal/registry.py`
- `local_terminal/comm_receiver.py`

### Camera / controller

- `camera/config.py`
- `camera/constants.py`
- `camera/pid_controller.py`
- `camera/ptz.py`

### Remote optical source

- `remote_terminal/config.py`
- `remote_terminal/optics.py`
- `remote_terminal/scenario.py`
- `remote_terminal/beacon_encoder.py`

### Disturbances / simulation integration

- `disturbance/core/pipeline.py`
- `disturbance/sensor/image_noise.py`
- `simulation/fov_pipeline.py`
- `simulation/headless.py`
- `gui/application/session.py`
- `gui/core/renderer.py`

### Tests

- `tests/test_acceptance.py`
- `tests/test_coordinates.py`
- `tests/test_optical_coupling.py`
- `tests/test_photodiode_receiver.py`
- `tests/test_reacquisition_coords.py`

---

## Appendix B — Verification Limitation

This review is a **source-level re-check against the current GitHub commit**. The repository's GitHub connector returned no CI status entries for `f12b70d`, and the current execution environment could not clone the repository directly from GitHub. Therefore this document does **not** claim that the entire test suite was executed successfully.

The test files were inspected for logical correctness, and several test/setup defects were identified directly from their source.
