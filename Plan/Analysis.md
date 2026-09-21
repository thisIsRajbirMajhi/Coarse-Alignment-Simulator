# Coarse Alignment Simulator — Complete System Analysis, Current Behavior, Bugs, and Corrected V1 Architecture

> **Purpose:** This document is intended to be consumed by an AI coding agent working on the `Coarse-Alignment-Simulator` repository. It describes what the system is intended to do, how the current implementation actually works, the observed behavior from the supplied recordings, identified bugs and architectural problems, and the implementation order required to stabilize V1.
>
> **Repository analyzed:** `https://github.com/thisIsRajbirMajhi/Coarse-Alignment-Simulator`
>
> **Analysis basis:** current `Main` branch code around commit `3f4c2ba8c03826f26f03b26e802ebbbb93713396`, repository architecture, tests, GUI/headless execution paths, and three supplied screen recordings/frame captures.

---

## 1. Executive Summary

The simulator is not suffering from one single failure. It has a **working control loop surrounded by weak measurement, coordinate-frame, association, and state-management boundaries**.

The recordings show that the camera/PTZ/PID loop can genuinely lock onto the target and hold low error for a meaningful interval. The primary failure is therefore **not global inability to track** and it is not primarily a PID-tuning problem.

The dominant observed failure pattern is:

```text
GOOD LOCK
   ↓
measurement / association becomes invalid or mismatched
   ↓
tracker state diverges
   ↓
COAST / large error
   ↓
reacquisition
   ↓
LOCKED again, often with residual error
```

The strongest code-level cause is the ordering of tracking operations:

```text
CURRENT IMPLEMENTATION
----------------------
detection
   ↓
association using old tracker state
   ↓
tracker.step()
   ├── FOV-origin shift / rebase
   └── Kalman predict/update
```

This means the association gate can be evaluated against a prediction that has not yet been transformed into the current FOV coordinate frame and advanced to the current time.

The corrected order should be:

```text
CORRECTED V1
------------
current camera/FOV frame
   ↓
rebase tracker state into current frame
   ↓
Kalman predict to current timestamp
   ↓
detect optical candidates
   ↓
temporal validation
   ↓
associate against CURRENT prediction
   ↓
Kalman measurement update
   ↓
tracking confidence/state transition
   ↓
PID/controller
   ↓
PTZ plant
   ↓
next frame
```

Additional high-priority defects include:

1. Acquisition uses `max(fw, fh)` instead of the configured acquisition gate.
2. `confirmed or spots` bypasses temporal confirmation whenever confirmation is absent.
3. Beacon observations can be stale because the latest observation is reused without a strict freshness policy.
4. Foreign beacon information can contaminate an active track's power/timestamp fields even when the identity is rejected.
5. Tracking association is too dependent on nearest-in-gate candidate selection.
6. There is no integrated regression test covering moving FOV + target motion + coordinate rebase + association.
7. Telemetry metrics such as `detection_rate_pct` and `acquisition_time_s` do not currently represent their intended concepts.
8. UI candidate confidence is conflated with actual identity/tracking confidence.

There are also deeper simulator-fidelity problems, such as the camera image and photodiode not yet being fully driven by an end-to-end physical optical propagation model. Those matter for a high-fidelity simulator, but **they are secondary to fixing V1 tracking correctness**.

---

# 2. System Goal

The simulator is intended to model a coarse optical alignment/tracking system in which:

- one or more remote terminals exist in world coordinates;
- terminals can move;
- terminals emit optical signals and communication beacons;
- a steerable camera/PTZ system observes a field of view (FOV);
- optical spots are detected in the camera image;
- a communication receiver can provide identity / power information;
- a tracker maintains an estimate of target position and velocity;
- the camera control system steers the FOV toward the active target;
- the system can search, acquire, associate, track, coast, lose, and reacquire a target;
- GUI and headless simulation paths should use equivalent runtime logic;
- V1 should be deterministic enough for automated regression testing.

The main engineering objective is not merely to make the target appear centered. The simulator must make the **measurement → estimation → association → control → camera motion** chain internally consistent.

---

# 3. High-Level Architecture

The current architecture is modular and broadly appropriate:

```text
Scenario / Remote Terminal
        │
        ├── terminal position / velocity
        ├── optical emission
        └── communication beacon
        │
        ▼
Camera / PTZ plant
        │
        ├── PTZ state
        ├── disturbed pose
        └── FOV extraction
        │
        ▼
FOV image
        │
        ├── detector
        └── temporal confirmer
        │
        ▼
Communication receiver
        │
        └── beacon observations
        │
        ▼
Supervisor / FSM
        │
        ├── SEARCH
        ├── IDENTIFY
        ├── ASSOCIATE
        ├── TRACK
        ├── COAST
        ├── LOST
        └── REACQUIRE
        │
        ▼
Kalman tracker
        │
        ▼
PID controller
        │
        ▼
PTZ command
        │
        ▼
Next simulation frame
```

The major architectural issue is not that these modules exist; it is that **the contract between modules is insufficiently explicit**.

In particular, the following must be made explicit in V1:

- coordinate frame of every position measurement;
- timestamp of every measurement;
- whether a detection is raw or confirmed;
- whether beacon data is fresh or historical;
- whether a target observation is identity-valid;
- whether the Kalman prediction has already been advanced to the current time;
- whether a control command applies immediately or one frame later.

---

# 4. Current Runtime Flow

The integrated GUI session currently behaves approximately as follows:

```text
1. Update scene
2. Update remote terminals
3. Apply pending PID/search control from previous supervisor tick
4. Advance camera/PTZ plant
5. Apply pose disturbance
6. Extract current FOV
7. Apply FOV/image noise
8. Construct communication sources
9. Supervisor processes current FOV / beacon state
10. Supervisor emits tracking/control output
11. Store that control output for the next camera frame
```

The headless simulation path follows a similar pattern.

### Important consequence: one-frame control latency

Supervisor output generated on frame N is applied during a later step, effectively creating roughly one camera-frame of latency at a 30 Hz camera rate.

This is not automatically wrong. It represents a discrete control pipeline. However, it must be explicit and tested rather than being an accidental implementation detail.

At 30 Hz the nominal frame interval is approximately:

```text
1 / 30 = 33.3 ms
```

For V1, retain the latency if desired, but explicitly model it as part of the timing contract.

---

# 5. Current Supervisor State Machine

The current FSM is approximately:

```text
SEARCH
  ↓
IDENTIFY
  ↓
ASSOCIATE
  ↓
TRACK ←→ COAST
  ↓
LOST
  ↓
REACQUIRE
  ↓
TRACK
```

The states have sensible intent, but the evidence requirements between states are not strict enough.

## SEARCH

Current behavior:

- camera performs a scanning motion;
- optical spots are detected;
- a communication receive condition may indicate that a candidate should be identified;
- when spots and receive evidence coexist, supervisor moves toward IDENTIFY.

Problem:

The distinction between **raw candidate**, **confirmed optical measurement**, and **identity-valid target** is not sufficiently strict.

## IDENTIFY

Current behavior relies on `_pending_beacon`.

Problem:

`_pending_beacon` can represent an older observation because `poll_observation()` can return the latest previously parsed observation even if a new observation has not completed.

V1 requires a clear beacon freshness policy.

## ASSOCIATE

Current code effectively uses:

```python
associate_acquisition(
    confirmed or spots,
    self._pending_beacon,
    (fw, fh),
    gate_px=max(fw, fh),
)
```

Problems:

- `confirmed or spots` may fall back to raw detections;
- `max(fw, fh)` creates a very large acquisition gate;
- the configured `association_gate_px` is not actually used here;
- the resulting gate can accept almost any candidate in the image.

For a 640×480 frame, a 640-pixel gate is so large that even a corner candidate is inside a nominal radius of the image center because the maximum center-to-corner distance is only about 400 pixels.

## TRACK / COAST

Current sequence effectively does:

```text
detect spots
   ↓
associate around tracker.kf.position
   ↓
tracker.step()
   ├── shift for origin change
   └── predict / update
```

This is the primary coordinate/timing defect.

Association is evaluated using a prediction that may belong to the previous FOV frame and previous timestamp.

## REACQUIRE

Reacquisition uses current candidate set plus beacon and the existing Kalman position.

The same freshness and raw-candidate problems apply here.

---

# 6. Coordinate-System Model

The repository contains useful coordinate wrappers:

- `FovPoint`
- `WorldPoint`
- `PtzAngles`

and coordinate conversion utilities.

Conceptually the simulator contains several spaces:

```text
WORLD
  ↓ camera/geometry transform
FOV / IMAGE PIXELS
  ↓ tracking state
TRACKER FRAME
  ↓ control conversion
ANGLE SPACE
  ↓ actuator
PTZ PLANT
```

The danger is that much of the runtime still passes raw `(x, y)` tuples rather than strongly typed values.

That makes a frame mismatch easy to introduce.

### V1 coordinate invariant

At every tracking tick:

> **The Kalman state, measurement, and association prediction must all refer to the same FOV coordinate frame and the same logical timestamp.**

Whenever the FOV origin changes, the track state must be transformed before using it for association.

---

# 7. Primary Bug: Association Before Rebase/Predict

This is the most important bug found.

The tracker performs frame shifting and Kalman prediction inside `tracker.step()`.

Conceptually:

```python
self.kf.shift(-origin_shift[0], -origin_shift[1])

if obs is not None:
    self.kf.predict(dt)
    self.kf.update(obs)
else:
    self.kf.predict(dt)
```

But the supervisor performs association **before** calling `tracker.step()`.

Therefore:

```text
Current image measurement
        │
        ▼
Compare against stale tracker position
        │
        ▼
Association may reject correct target
        │
        ▼
Only afterward does tracker rebase/predict
```

### Why this produces the observed video failure

A target can still exist in the current camera image while the tracker's predicted location is offset because:

- the camera FOV moved;
- the coordinate origin changed;
- target motion occurred;
- the tracker state is not yet advanced to the current timestamp.

The resulting innovation can exceed the association gate.

The target is then treated as missing even though it is visible.

### Required fix

Change the tracking tick to:

```text
1. Determine current FOV-origin shift
2. Shift/rebase tracker state into current FOV frame
3. Predict Kalman state to current simulation timestamp
4. Detect candidates
5. Filter/confirm candidates
6. Associate against current predicted state
7. Update Kalman state with selected measurement
8. Determine state transition
9. Produce target/control output
```

This should be treated as a **P0 correctness fix**.

---

# 8. Primary Bug: Acquisition Gate Ignores Configuration

Current acquisition uses:

```python
gate_px=max(fw, fh)
```

With a 640×480 FOV this is:

```text
640 px
```

while configuration contains a much smaller configured acquisition gate (for example approximately 60 px in the analyzed configuration).

### Why this is wrong

An acquisition gate exists to prevent arbitrary blobs from being accepted as the target.

A frame-sized gate defeats that purpose.

### Required fix

Use:

```python
gate_px=self.cfg.association_gate_px
```

or a state-specific gate explicitly derived from configuration.

Do not silently override configured tracking limits with image dimensions.

---

# 9. Primary Bug: `confirmed or spots` Bypasses Confirmation

The supervisor repeatedly uses the equivalent of:

```python
confirmed or spots
```

This means:

```text
if confirmed detections exist:
    use them
else:
    use raw detections anyway
```

That undermines the temporal confirmation layer.

### Failure scenario

```text
Frame N:
    bright false blob appears

Frame N+1:
    false blob disappears / moves

Temporal confirmer:
    does not confirm it

Supervisor:
    receives empty confirmed set
    falls back to raw spot
```

The system therefore behaves as though validation is optional.

### Required V1 policy

Use different evidence policies by state.

```text
SEARCH
  Raw candidates may be displayed and used by the scan heuristic.
  They should not automatically become an authoritative target.

IDENTIFY
  Require confirmed optical evidence + fresh communication evidence.

ASSOCIATE
  Require a valid candidate and an appropriate identity / proximity test.

TRACK
  Prefer confirmed measurements inside the predicted gate.
  Raw detections may be used only under an explicitly defined degraded mode.

COAST
  Do not invent measurements from arbitrary raw candidates.

REACQUIRE
  Require sufficiently strong spatial/temporal/identity evidence.
```

---

# 10. Primary Bug: Beacon Freshness

`poll_observation()` can expose the latest parsed observation when no new observation has completed.

That is useful for telemetry, but dangerous for event-driven identity association if treated as a fresh measurement.

The supervisor also stores a `_pending_beacon` value.

### Failure mode

```text
T0: valid beacon for RT-001
T1: new camera frame
T2: no new beacon
T3: supervisor still sees RT-001 beacon as current evidence
```

This creates stale identity/power/timestamp evidence.

### Required fix

Represent beacon data with explicit freshness:

```python
class BeaconObservation:
    terminal_id: str
    timestamp_s: float
    sequence_id: int
    received_power_w: float
    valid_crc: bool
```

Then:

```python
age_s = sim_time_s - observation.timestamp_s
```

and require:

```text
age_s <= beacon_freshness_window_s
```

for identity/association use.

The historical observation may remain visible in telemetry, but it must not silently act as current evidence.

### Event handling

Prefer:

```text
new beacon event
    ↓
queue
    ↓
consume once
    ↓
clear pending decision evidence
```

rather than indefinitely latching `_pending_beacon`.

---

# 11. Primary Bug: Foreign Beacon Contaminates Active Track

Tracking association checks terminal identity, but a foreign beacon may still contribute its received power and timestamp when constructing a target observation.

This is dangerous because identity rejection should mean **all target-specific physical measurements from the foreign source are excluded from the active track update**.

### Correct rule

If:

```text
beacon.terminal_id != active_track.target_id
```

then:

```text
Do not use its received power for the active target.
Do not use its timestamp as the active target's measurement timestamp.
Do not update active-target identity confidence from it.
```

The beacon can remain visible as a rejected/foreign signal in diagnostics.

---

# 12. Primary Problem: Candidate Association Is Too Simple

Current tracking association is approximately:

```text
predicted position
       ↓
find candidates inside Mahalanobis gate
       ↓
choose nearest
```

That is reasonable for a clean single-target system, but the simulator intentionally has multiple optical candidates and multiple terminals.

### Risks

A wrong candidate can be:

- closer in pixel distance;
- brighter;
- temporarily inside the gate;
- caused by another terminal;
- a background/noise artifact.

### V1 association score

Use multiple evidence terms:

```text
association score =
    spatial innovation
  + velocity consistency
  + SNR consistency
  + temporal persistence
  + spot-shape consistency
  + beacon identity consistency
```

This does not require a sophisticated global assignment algorithm for V1. A properly structured single-track scored association is enough.

---

# 13. Detector Analysis

The current detector performs a classical image-based detection sequence roughly equivalent to:

```text
greyscale
   ↓
median background estimation
   ↓
brightness threshold
   ↓
connected components
   ↓
area/SNR filtering
```

Defaults include roughly:

- minimum SNR around 6 dB;
- candidate peak margin around 8;
- minimum area around 4 pixels;
- maximum area around 4000 pixels.

This is fine as a prototype detector, but not sufficient as the final discriminator between a true optical source and arbitrary bright structures/noise.

### Observed symptom

The supplied recordings contain many simultaneous labels resembling:

```text
CAND 1.00
CAND 0.15
CAND 0.06
...
```

This indicates the detector is producing a broad candidate population.

### Required improvement

For V1, add candidate validation based on:

- SNR;
- local contrast;
- connected-component area;
- compactness/circularity;
- approximate PSF consistency;
- centroid stability;
- temporal persistence.

Do not solve false detections merely by increasing the SNR threshold. That risks rejecting valid low-SNR targets and hides the actual association problem.

---

# 14. Temporal Confirmation

`TemporalConfirmer` already exists and is a good architectural idea.

It requires persistence over multiple frames.

The problem is not that a temporal confirmer exists. The problem is that the supervisor can bypass it.

### V1 rule

A candidate should transition conceptually through:

```text
RAW CANDIDATE
     ↓
TEMPORALLY CONFIRMED
     ↓
ASSOCIATION-VALID
     ↓
ACTIVE TRACK MEASUREMENT
```

Do not use one generic confidence number to represent all four concepts.

---

# 15. Kalman Tracker Analysis

The tracker is a Kalman-based position/velocity estimator in FOV pixels.

Current properties include:

- process noise around `q = 8`;
- base measurement noise around `4`;
- low-SNR measurement scaling;
- high-SNR measurement scaling;
- coast uncertainty growth;
- prediction covariance used for Mahalanobis gating.

This is conceptually appropriate.

### Important point

The Kalman model is not the primary issue visible in the videos.

The bigger issue is **when and in which coordinate frame it is used**.

A good Kalman filter cannot compensate for a measurement being associated against the wrong frame/state.

### V1 tracker invariant

Before association:

```text
state frame = current FOV frame
state timestamp = current tracking timestamp
prediction covariance = current prediction covariance
```

After a successful measurement:

```text
measurement update
→ confidence update
→ track-state transition
```

After a missed measurement:

```text
prediction only
→ covariance grows
→ track quality decreases
```

---

# 16. COAST / LOST Behavior

COAST is correct as a concept. The problem is that it can be entered because of an association problem rather than a true sensor loss.

The video around approximately 75.9 s shows this strongly:

```text
AUTO COAST
Err ≈ 223.6 px
```

while the God Screen indicates the relevant target remains physically available in or near the camera's observable region.

There is also an association/candidate distance on the screen of roughly 281 px.

### Interpretation

The video establishes the symptom:

> The active track can lose the correct optical measurement even though the target is still physically available.

The video alone does not prove the exact internal cause.

The code analysis strongly points to the rebase/predict/association ordering and overly permissive/ambiguous candidate handling as the likely causes.

---

# 17. Reacquisition Behavior

The system can recover from tracking loss, which is a positive sign.

For example, after the large-error coast episode, the system returns to `LOCKED` with residual errors in the tens of pixels before settling further.

This means the reacquisition pathway works at a basic level.

However, V1 reacquisition should be stricter:

```text
candidate exists
+ candidate is confirmed
+ candidate is spatially plausible
+ beacon is fresh when identity is required
+ candidate is consistent with predicted motion if available
```

Only then should the tracker be relocked.

---

# 18. Video Findings

The supplied recordings show several distinct behaviors.

## Recording 1

Representative observations:

### ~19.0 s

```text
AUTO LOCKED
Err ≈ 1.1 px
```

The target is close to image center.

This demonstrates the basic tracking loop can work correctly.

### ~56.9 s

```text
AUTO LOCKED
Err ≈ 6.4 px
```

Still a plausible and functional lock, though error is higher.

### ~75.9 s

```text
AUTO COAST
Err ≈ 223.6 px
```

The visible UI also indicates a large candidate/boresight separation.

The God Screen still shows the target available in the scene/FOV context.

This is the clearest failure event.

### ~85.4 s

```text
AUTO LOCKED
Err ≈ 18.2 px
```

The system has reacquired but is not perfectly centered.

### ~104.3 s

```text
AUTO LOCKED
Err ≈ 15.9 px
```

The system remains locked but with residual pointing error.

### Interpretation of Recording 1

The problem is not simply:

```text
target lost permanently
```

It is:

```text
correct track
→ association/estimation failure
→ coast
→ reacquisition
→ weaker lock
```

---

## Recording 2

Around the shown ~78 s state:

```text
AUTO SEARCHING
Err 0.0 px
```

The God Screen places the target outside the currently observed FOV.

This is largely legitimate behavior.

Do **not** treat every SEARCH state in the recordings as a software bug.

The simulator correctly needs to search when a target is physically outside the active camera view.

---

## Recording 3

Around the shown ~100 s state:

```text
AUTO SEARCHING
Err 0.0 px
```

Two targets are visible in the world view while the current camera FOV is elsewhere.

Again, this is not by itself evidence of a tracking bug. It demonstrates that:

- multiple terminals can exist simultaneously;
- the current FOV can miss the active target;
- the search system is operating in a multi-target environment.

---

# 19. PID / PTZ Analysis

The PID controller is structurally reasonable:

- proportional control;
- integral term;
- derivative term;
- derivative filtering;
- anti-windup;
- deadband;
- output saturation;
- target-velocity feed-forward.

There is also a closed-loop PID test where a static target converges to a small pixel error.

### Why PID is not the first suspect

The recordings do not primarily show continuous oscillation around the target.

They show sudden degradation of the active track and subsequent recovery.

That pattern points more strongly toward:

```text
measurement
association
coordinate frame
track-state management
```

than toward controller instability.

### V1 rule

Do not aggressively retune PID until association and state estimation are stable.

Otherwise PID changes can mask the root cause.

---

# 20. Camera/PTZ Configuration Observations

Current analyzed camera configuration includes approximately:

```text
FOV: 4° × 3°
resolution: 640 × 480
camera update: 30 Hz
max angular speed: 5°/s
acceleration limit: 25°/s²
```

Pixel-to-angle mapping is approximately:

```text
0.00625° / pixel
```

Therefore:

```text
10 px ≈ 0.0625°
20 px ≈ 0.125°
100 px ≈ 0.625°
```

This is useful when interpreting observed pixel error.

### Important configuration observation

The nominal pan/tilt travel limits are much wider than the effective world/FOV constraints produced by the current simplified scene geometry. This should be documented clearly rather than treated as equivalent to a real mechanical PTZ travel range.

---

# 21. PTZ Plant Fidelity

The PTZ implementation is a simplified acceleration-limited velocity actuator with lag/backlash behavior rather than a complete physical second-order servo model.

That is acceptable for V1 provided it is described correctly.

Do not make the simulator claim to model a full servo plant unless the physical model actually supports it.

For V1:

```text
PTZ model = simplified actuator abstraction
```

For a later high-fidelity version:

```text
motor/drive dynamics
→ velocity loop
→ position loop
→ mechanical limits
→ backlash
→ response delay
```

can be modeled explicitly.

---

# 22. Current Optical Rendering Limitation

The current camera image path still uses synthetic Gaussian spot rendering tied relatively directly to terminal/world state.

The conceptual rendering is closer to:

```text
terminal position
   ↓
draw spot
```

than to a fully causal optical chain.

A higher-fidelity simulation should eventually model:

```text
terminal emission
   ↓
beam geometry
   ↓
pointing error
   ↓
propagation loss
   ↓
received irradiance
   ↓
camera aperture / optics
   ↓
focal-plane location
   ↓
PSF
   ↓
exposure/integration
   ↓
sensor noise
   ↓
ADC
   ↓
image
```

This is a **later-stage fidelity problem**, not the first fix for the observed track-loss bug.

---

# 23. Current Photodiode / Communication Receiver Limitation

The receiver currently operates heavily around the logical chip/frame representation and BER-style perturbation rather than a complete analog optical receiver chain.

A physically stronger model would be:

```text
received optical power
   ↓
photodiode responsivity
   ↓
photocurrent
   ↓
analog noise
   ↓
receiver bandwidth/filter
   ↓
sampling
   ↓
demodulation
   ↓
CRC / frame validation
```

For V1, preserve the existing communication abstraction if it is needed to validate acquisition logic, but keep the boundary explicit so future physics work can replace the source without redesigning the FSM.

---

# 24. Beam Pointing Representation Limitation

Current `BeamModel` behavior applies pointing error to received power attenuation, but the spatial centroid/displacement of the emitted beam is not fully represented in the rendered image.

A more physically consistent model should allow pointing error to affect both:

```text
received power
AND
spatial beam centroid
```

This becomes important later when simulating coarse alignment rather than simply target visibility.

---

# 25. Telemetry Problems

## `detection_rate_pct`

Current behavior effectively reports something close to:

```text
100 if locked else 0
```

This is not a true detection rate.

A proper metric should measure something like:

```text
correct target measurements / valid target observation opportunities
```

and be separated from track lock state.

Recommended V1 metrics:

```text
Detection probability
False candidate rate
Correct association rate
Track retention
Track loss count
Mean track duration
Mean reacquisition time
Mean acquisition time
Position RMSE
95th percentile error
Maximum error
Beacon CRC success rate
```

## `acquisition_time_s`

Current `_first_lock_t` is an absolute simulation time, not necessarily the elapsed acquisition duration.

Correct measurement:

```text
acquisition_duration = first_valid_lock_timestamp - search_start_timestamp
```

The system should reset/record these per acquisition cycle.

---

# 26. UI / Debugging Representation Problems

The UI currently uses candidate confidence in a way that can visually imply much more certainty than the underlying data warrants.

For example:

```text
CAND 1.00
```

is essentially derived from an SNR mapping, not a validated identity confidence.

### Recommended labels

Use clearly distinct overlays:

```text
RAW CANDIDATE
CONFIRMED SPOT
PREDICTION
ACTIVE TRACK: RT-001
BEACON: RT-001 / fresh
BEACON: RT-002 / rejected
TRUTH: RT-001
```

This lets an engineer immediately see where the failure occurs.

---

# 27. Multi-Target V1 Policy

The simulator can contain multiple terminals.

For V1, the cleanest policy is:

```text
One active track at a time.
Multiple candidates may exist.
Multiple terminals may emit.
Association must explicitly reject non-active candidates.
```

Internally, do not collapse identity and detection into one structure.

Use separate conceptual objects:

```text
Detection
TargetObservation
BeaconObservation
TrackState
```

Example:

```text
Detection
    x, y, snr, shape, area, timestamp

BeaconObservation
    terminal_id, rx_power, timestamp, CRC, sequence

TrackState
    target_id
    Kalman state
    covariance
    state = LOCKED/DEGRADED/COAST/LOST
    last_measurement_time
    last_beacon_time
```

---

# 28. Recommended V1 Tracking State Machine

Use an explicit state model:

```text
                 ┌──────────────┐
                 │    SEARCH    │
                 └──────┬───────┘
                        candidate + sufficient evidence
                         ▼
                 ┌──────────────┐
                 │   IDENTIFY   │
                 └──────┬───────┘
                        fresh identity evidence
                         ▼
                 ┌──────────────┐
                 │   ASSOCIATE  │
                 └──────┬───────┘
                        valid match
                         ▼
                 ┌──────────────┐
                 │    TRACK     │◄─────────────┐
                 └──────┬───────┘              │
                        missed measurement     │ valid measurement
                         ▼                     │
                 ┌──────────────┐              │
                 │    COAST     │──────────────┘
                 └──────┬───────┘
                     timeout / confidence loss
                         ▼
                 ┌──────────────┐
                 │     LOST     │
                 └──────┬───────┘
                        reacquisition start
                         ▼
                 ┌──────────────┐
                 │  REACQUIRE   │
                 └──────┬───────┘
                  valid strong match
                         │
                         └──────────────► TRACK
```

### Recommended semantics

#### SEARCH

No active target.

#### IDENTIFY

A plausible optical candidate exists; system seeks current communication identity.

#### ASSOCIATE

Match candidate and communication identity using explicit spatial/identity gates.

#### TRACK

Validated target measurement is available and Kalman state is reliable.

#### COAST

No valid measurement this frame, but the predicted target remains plausible.

#### LOST

Prediction uncertainty or missed time exceeded configured limits.

#### REACQUIRE

Actively attempt to regain target using search/prediction/identity information.

---

# 29. Correct V1 Tracking Tick

This is the recommended core algorithm.

```python
# 1. Current frame/time
now = sim_time
current_fov_origin = camera.current_fov_origin()

# 2. Rebase tracker state into current FOV coordinates
tracker.rebase(current_fov_origin)

# 3. Predict to current time
tracker.predict_to(now)

# 4. Detect image candidates
raw_detections = detector.detect(fov_frame, cfg)

# 5. Temporal confirmation
confirmed_detections = confirmer.update(raw_detections)

# 6. Read only fresh communication evidence
beacon = comm.get_fresh_observation(now)

# 7. State-specific candidate selection
candidates = select_candidates_for_state(
    state=supervisor.state,
    raw=raw_detections,
    confirmed=confirmed_detections,
)

# 8. Association around CURRENT prediction
measurement = associator.match(
    candidates=candidates,
    predicted_state=tracker.prediction,
    active_target=tracker.active_target,
    beacon=beacon,
)

# 9. Update estimator
tracker.update(measurement, now)

# 10. Update FSM based on measurement validity / confidence
state = supervisor.transition(measurement, beacon, now)

# 11. Generate control from CURRENT tracker estimate
command = controller.compute(tracker.state, camera_state)

# 12. Apply command according to explicit control latency model
camera.enqueue_command(command)
```

The exact APIs may differ, but the ordering is essential.

---

# 30. Association Requirements for V1

Association should have these checks in order:

## 30.1 Freshness

Reject stale measurements and stale identity evidence.

## 30.2 Coordinate consistency

All positions must be in the current FOV frame.

## 30.3 Spatial gate

Use configured association threshold, not frame dimensions.

## 30.4 Statistical gate

Use Mahalanobis distance with current prediction covariance.

## 30.5 Candidate validity

Prefer temporally confirmed candidates.

## 30.6 Identity consistency

If beacon identity is available and fresh, use it to support association.

## 30.7 Measurement quality

Use SNR / shape / temporal quality as secondary scoring.

## 30.8 Select best valid measurement

Choose the highest-confidence valid candidate, not simply the nearest pixel.

---

# 31. V1 Association Pseudocode

```python
def associate_tracking(
    candidates,
    prediction,
    covariance,
    active_target_id,
    fresh_beacon,
):
    valid = []

    for c in candidates:
        if not c.temporally_valid:
            continue

        d2 = mahalanobis_distance(c.position, prediction.position, covariance)
        if d2 > MAHALANOBIS_THRESHOLD:
            continue

        score = spatial_score(d2)
        score += snr_score(c.snr_db)
        score += temporal_score(c)
        score += shape_score(c)

        if fresh_beacon is not None:
            if fresh_beacon.terminal_id == active_target_id:
                score += IDENTITY_BONUS
            else:
                score += FOREIGN_BEACON_PENALTY

        valid.append((score, c))

    return max(valid, key=lambda item: item[0])[1] if valid else None
```

The exact weights should be configured and tested rather than arbitrary constants spread across modules.

---

# 32. Explicit Beacon Contract

V1 should distinguish three concepts:

```text
NO BEACON
FRESH BEACON
STALE BEACON
```

Recommended interface:

```python
class BeaconObservation:
    terminal_id: str
    timestamp_s: float
    sequence_id: int
    p_rx_w: float
    crc_valid: bool

    def age(self, now_s: float) -> float:
        return max(0.0, now_s - self.timestamp_s)

    def is_fresh(self, now_s: float, max_age_s: float) -> bool:
        return self.crc_valid and self.age(now_s) <= max_age_s
```

Only `is_fresh == True` should affect current identity decisions.

---

# 33. Explicit Measurement Contract

Use a measurement structure with provenance.

Recommended fields:

```python
class OpticalDetection:
    x_px: float
    y_px: float
    snr_db: float
    area_px: float
    compactness: float
    timestamp_s: float
    confirmation_count: int
    source_status: str
```

where `source_status` may distinguish:

```text
RAW
CONFIRMED
```

The active tracker should consume only those measurement statuses allowed by its current state.

---

# 34. Explicit Track Contract

Recommended conceptual track state:

```python
class TrackState:
    target_id: str | None
    filter_state: KalmanState
    covariance: Matrix
    status: TrackStatus
    last_measurement_time_s: float | None
    last_beacon_time_s: float | None
    consecutive_hits: int
    consecutive_misses: int
    age_s: float
    confidence: float
```

Track status:

```text
SEARCHING
IDENTIFYING
ASSOCIATING
TRACKING
COASTING
LOST
REACQUIRING
```

Avoid hidden flags that duplicate state semantics.

---

# 35. Regression Tests Required Before Declaring V1 Stable

Current tests cover useful individual components, including Kalman and PID behavior, but they do not cover the main integrated failure mode.

Add at least these tests.

## Test 1 — Moving FOV + stationary target

```text
Target stationary in world
Camera moves
Target remains visible
Tracker must remain associated
```

This is the direct regression for the coordinate-rebase bug.

## Test 2 — Moving target + moving camera

```text
Target moves
Camera moves
Target remains in FOV
Tracker must not lose association
```

## Test 3 — False candidate near predicted target

```text
real target + synthetic distractor
```

System should choose the target using temporal/identity evidence rather than nearest-pixel distance alone.

## Test 4 — Stale beacon

```text
valid beacon at T0
no new beacon
T1 exceeds freshness window
```

The stale beacon must not cause a new identity association.

## Test 5 — Foreign beacon

```text
active target = RT-001
foreign beacon = RT-002
```

RT-002 power/timestamp must not update RT-001's active observation.

## Test 6 — Acquisition gate

Put a candidate just outside the configured acquisition gate and verify rejection.

## Test 7 — Confirmation bypass regression

Provide a single-frame false detection and verify that it cannot become an authoritative measurement when the state requires confirmation.

## Test 8 — Genuine out-of-FOV search

Move target outside FOV and ensure SEARCH/scan logic is allowed to operate normally.

## Test 9 — Reacquisition

Force temporary measurement loss while target remains plausible; verify transition:

```text
TRACK → COAST → REACQUIRE → TRACK
```

without jumping to an unrelated candidate.

## Test 10 — Deterministic replay

Run the same scenario twice with the same seed/configuration and verify identical tracking results.

---

# 36. Metrics for V1 Acceptance

Do not judge V1 solely by whether the UI eventually displays `LOCKED`.

Track these metrics:

### Acquisition

- acquisition success rate;
- time to first valid lock;
- number of false acquisitions.

### Tracking

- position RMSE;
- median position error;
- 95th percentile error;
- maximum error;
- percentage of time inside the configured tracking gate;
- track retention percentage.

### Association

- correct association rate;
- false association rate;
- identity mismatch count;
- foreign-beacon contamination count.

### Recovery

- number of track losses;
- mean coast duration;
- mean reacquisition duration;
- reacquisition success rate.

### Sensor

- raw candidate count/frame;
- confirmed candidate count/frame;
- detection probability;
- false candidate rate.

These values should be logged independently from UI labels.

---

# 37. Recommended Logging for Debugging

For every tracking tick, log a compact record:

```text
sim_time
camera_fov_origin
camera_angles
active_track_id
track_status
predicted_x
predicted_y
prediction_covariance
number_raw_detections
number_confirmed_detections
selected_detection_x
selected_detection_y
selected_detection_snr
mahalanobis_distance
beacon_id
beacon_age
beacon_fresh
association_score
innovation_x
innovation_y
tracking_error
control_command_pan
control_command_tilt
```

This would make the current bug extremely easy to diagnose because the log would directly show:

```text
predicted position
vs
measurement
vs
frame shift
vs
association decision
```

---

# 38. Changes to Avoid During the First Fix Pass

Do **not** initially:

- retune PID aggressively;
- add arbitrary large gates to make tracking look stable;
- remove Kalman filtering;
- disable beacon identity checks;
- lower detector thresholds indiscriminately;
- bypass confirmation permanently;
- increase coast duration just to hide association loss;
- modify the simulator physics and tracking architecture simultaneously.

These changes can mask the underlying problem.

The first pass should make the existing architecture internally correct.

---

# 39. Recommended Implementation Order

## P0 — Tracking correctness

1. Fix tracker rebase/predict/associate ordering.
2. Make tracker prediction explicitly current-time before gating.
3. Replace acquisition `max(fw, fh)` gate with configured gate.
4. Remove blanket `confirmed or spots` fallback from tracking and reacquisition.
5. Add beacon freshness.
6. Treat beacon observations as consumable events for identity decisions.
7. Prevent foreign-beacon power/timestamp contamination.
8. Add moving-FOV integration regression tests.

## P1 — Association robustness

9. Introduce explicit candidate/measurement types.
10. Add state-specific measurement policy.
11. Add multi-term association scoring.
12. Improve temporal candidate validation.
13. Separate raw/confirmed/active/predicted UI terminology.
14. Add proper track-state confidence and transition counters.

## P1 — Metrics and observability

15. Replace `detection_rate_pct` with a real detection metric.
16. Correct acquisition duration measurement.
17. Add association and track-retention metrics.
18. Add structured tracking diagnostics.

## P2 — Physical fidelity

19. Build causal per-terminal optical propagation.
20. Make camera image formation physically driven.
21. Add analog photodiode receive path.
22. Add exposure/integration/noise/ADC.
23. Make beam pointing change both power and beam centroid.
24. Add explicit independent simulation clocks.

---

# 40. Correct V1 Architecture

The target V1 architecture should look like this:

```text
                         WORLD / SCENARIO
                                │
              ┌─────────────────┴──────────────────┐
              │                                    │
       Remote Terminal                        Target Truth
              │                                    │
      position / velocity                           │
      optical emission                              │
      beacon                                        │
              │                                    │
              └──────────────┬─────────────────────┘
                             │
                      Camera / PTZ Plant
                             │
                    current camera pose
                             │
                         FOV frame
                             │
                             ▼
                    Optical Image Sensor
                             │
                             ▼
                      Spot Detector
                             │
                             ▼
                   Temporal Confirmation
                             │
                             ▼
                     Candidate Manager
                             │
                             │
                  ┌──────────┴───────────┐
                  │                      │
             Beacon Receiver       Current Track
                  │                      │
                  └──────────┬───────────┘
                             │
                             ▼
                         Association
                             │
                             ▼
                       Kalman Tracker
                             │
                             ▼
                         Track FSM
                             │
                             ▼
                       PID Controller
                             │
                             ▼
                        PTZ Command
                             │
                             ▼
                      Camera / PTZ Plant
                             │
                             └───────── next tick
```

The key property is that the **tracker owns estimation**, the **associator owns measurement selection**, and the **FSM owns state transitions**.

Do not mix those responsibilities.

---

# 41. Responsibility Boundaries

## Detector

Responsible for:

- finding possible optical blobs;
- estimating position;
- computing raw measurement quality.

Not responsible for:

- target identity;
- track state;
- camera control.

## Temporal confirmer

Responsible for:

- deciding whether a candidate has enough temporal persistence.

Not responsible for:

- global target identity;
- PID.

## Beacon receiver

Responsible for:

- decoding communication observations;
- reporting timestamp, identity, CRC, and received power.

Not responsible for:

- choosing the camera candidate.

## Association layer

Responsible for:

- combining optical and communication evidence;
- selecting the measurement corresponding to the active track.

Not responsible for:

- controlling PTZ directly.

## Kalman tracker

Responsible for:

- state prediction;
- covariance;
- measurement update;
- coordinate-frame rebase.

Not responsible for:

- target search strategy;
- UI labels.

## Supervisor/FSM

Responsible for:

- state transitions;
- search/reacquisition policy;
- track lifecycle.

Not responsible for:

- raw image segmentation;
- low-level PID math.

## PID controller

Responsible for:

- converting tracking error/velocity to desired camera motion.

Not responsible for:

- candidate selection.

## Camera/PTZ plant

Responsible for:

- applying commands;
- motion constraints;
- lag/backlash/disturbance;
- resulting FOV.

Not responsible for:

- target identity.

---

# 42. V1 Invariants

The agent should enforce these invariants in code and tests.

### Invariant 1 — Frame consistency

No measurement may be compared with a prediction from a different FOV coordinate frame without an explicit transform.

### Invariant 2 — Time consistency

No measurement should be used as current without knowing its timestamp/age.

### Invariant 3 — Identity isolation

Foreign beacon data cannot modify the active target state.

### Invariant 4 — Confirmation integrity

A measurement marked unconfirmed cannot silently become confirmed through a fallback operator.

### Invariant 5 — Config integrity

Association limits must come from configuration unless a state-specific override is explicitly named and documented.

### Invariant 6 — Track-state integrity

`TRACKING`, `COASTING`, and `LOST` must have distinct semantics.

### Invariant 7 — No hidden control feedback

Control commands must use explicitly defined state/measurement timestamps.

### Invariant 8 — Determinism

Same seed + same scenario + same configuration should reproduce the same result.

---

# 43. Definition of Done for V1

V1 should not be declared stable until all of these are true:

```text
[ ] Moving-camera stationary-target regression passes.
[ ] Moving-camera moving-target regression passes.
[ ] Acquisition gate obeys configured value.
[ ] Raw detections do not bypass confirmation in TRACK/REACQUIRE.
[ ] Stale beacons cannot trigger active identity association.
[ ] Foreign beacon data cannot contaminate active target observations.
[ ] Association uses current Kalman prediction.
[ ] Tracker is rebased before association.
[ ] Track loss/reacquisition transitions are deterministic.
[ ] Multi-candidate distractor test passes.
[ ] Out-of-FOV SEARCH behavior remains valid.
[ ] GUI and headless execution produce equivalent tracking decisions.
[ ] Tracking telemetry uses physically meaningful definitions.
[ ] Deterministic replay test passes.
[ ] PID is tuned only after association is stable.
```

---

# 44. Recommended Agent Execution Strategy

An AI coding agent should implement changes in this order.

### Step 1 — Understand and map the data flow

Read and document:

```text
local_terminal/supervisor.py
local_terminal/tracker.py
local_terminal/association.py
local_terminal/detector.py
local_terminal/comm_receiver.py
camera/config.py
camera/pid_controller.py
camera/ptz.py
common/coordinates.py
gui/application/session.py
simulation/headless.py
remote_terminal/scenario.py
remote_terminal/terminal.py
remote_terminal/optics.py
```

### Step 2 — Refactor tracking tick ordering

Move rebase/prediction before association without changing unrelated physics.

### Step 3 — Correct gates and evidence handling

Fix acquisition gate and measurement confirmation semantics.

### Step 4 — Fix beacon lifecycle

Implement freshness, timestamps, sequence identity, and foreign-source isolation.

### Step 5 — Add integrated tests

Create tests that reproduce the video failure conditions.

### Step 6 — Run deterministic simulations

Compare:

```text
before fix
vs
after fix
```

using the same scenario/seed.

### Step 7 — Only then tune detector/PID

Once the control architecture is correct, adjust thresholds and controller parameters based on measurable errors rather than visual intuition.

### Step 8 — Only after V1 is stable, upgrade physical realism

Do not mix optical-physics redesign into the first tracking-correctness patch unless a test proves it is necessary for V1.

---

# 45. Final Diagnosis

The system is **partially functional but not yet internally robust**.

The most important observation from the recordings is:

> The simulator can achieve a good lock, but the active track can unexpectedly lose the correct measurement while the target is still physically available, then recover through reacquisition.

That symptom is consistent with the current implementation because the system has several opportunities to associate using stale or insufficiently validated information.

The most likely chain is:

```text
FOV moves
   ↓
tracker state remains in previous effective frame until tracker.step()
   ↓
association is performed against stale frame/state
   ↓
correct measurement may fail gate or wrong candidate may be selected
   ↓
Kalman receives no valid measurement
   ↓
COAST prediction continues from compromised state
   ↓
error becomes large
   ↓
LOST / REACQUIRE
   ↓
new lock with residual error
```

The secondary problems increase the probability of that failure:

```text
large acquisition gate
        +
raw-candidate fallback
        +
stale beacon reuse
        +
foreign beacon contamination
        +
simple nearest-candidate association
        +
weak integrated regression coverage
```

Therefore the correct V1 strategy is **not to make the gates larger or tune PID until the UI looks stable**.

The correct strategy is to make the information flow internally consistent first:

```text
CURRENT FRAME
    ↓
CURRENT COORDINATE FRAME
    ↓
CURRENT KALMAN PREDICTION
    ↓
VALIDATED MEASUREMENT
    ↓
CORRECT ASSOCIATION
    ↓
KALMAN UPDATE
    ↓
EXPLICIT TRACK STATE
    ↓
CONTROL
```

Once this chain is correct, the simulator can be extended toward more sophisticated optics, communication physics, multi-target assignment, and realistic sensor models without repeatedly reintroducing tracking ambiguity.

---

# 46. Concise Agent Checklist

```text
P0
[ ] Rebase tracker before association.
[ ] Predict tracker to current timestamp before gating.
[ ] Use configured acquisition gate.
[ ] Remove `confirmed or spots` fallback from authoritative tracking paths.
[ ] Add beacon freshness.
[ ] Consume beacon events or explicitly expire them.
[ ] Prevent foreign beacon fields from entering active-target observations.
[ ] Add moving-FOV integration regression tests.

P1
[ ] Improve association scoring.
[ ] Add candidate quality/temporal validation.
[ ] Separate RAW / CONFIRMED / TRACK / PREDICTED / BEACON semantics.
[ ] Add explicit track lifecycle counters.
[ ] Correct telemetry metrics.
[ ] Strengthen coordinate typing / frame contracts.

P2
[ ] Physical optical propagation.
[ ] Physical image formation.
[ ] Analog photodiode chain.
[ ] Beam centroid displacement.
[ ] Explicit multi-clock model.
[ ] Higher-fidelity PTZ plant.
```

---

## 47. Important Interpretation Rules for Future Agents

1. **Do not treat every SEARCH state in the recordings as a bug.** Some shown SEARCH states are legitimate because the target is outside the current FOV.
2. **Do not claim that PID is the root cause without evidence.** The observed failure pattern is more consistent with measurement/association/coordinate-frame problems.
3. **Do not assume the video alone proves the exact internal bug.** The recordings establish the symptom; the source code establishes the likely mechanism.
4. **Do not fix association failures by arbitrarily widening gates.** That hides false-association problems.
5. **Do not use stale communication observations as though they were current.**
6. **Do not let identity-invalid beacon data influence the active target track.**
7. **Do not remove temporal confirmation just because it makes acquisition slower.** Replace it with a state-appropriate evidence policy.
8. **Do not redesign the physics layer before making the V1 tracking pipeline correct and testable.**

---

# 48. Intended End State

The finished V1 should behave like this:

```text
TARGET OUTSIDE FOV
      ↓
SEARCH
      ↓
OPTICAL CANDIDATE
      ↓
TEMPORALLY CONFIRMED
      ↓
FRESH BEACON / IDENTITY EVIDENCE
      ↓
ASSOCIATION
      ↓
KALMAN LOCK
      ↓
PID STEERING
      ↓
TARGET CENTERING
      ↓
CONTINUOUS TRACK
      │
      ├── valid measurement → TRACK
      │
      └── temporary miss → COAST
                              │
                              ├── measurement returns → TRACK
                              │
                              └── timeout → LOST
                                              ↓
                                         REACQUIRE
                                              ↓
                                            TRACK
```

At every stage, the system should be able to answer four questions unambiguously:

```text
1. What target am I tracking?
2. Where do I currently predict it is?
3. What measurement did I use to update that prediction?
4. Why did I accept or reject that measurement?
```

If those four answers are deterministic and visible in logs/tests, the remaining tuning and physics work becomes substantially easier.
