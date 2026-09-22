# Coarse-Alignment-Simulator — Errors, Bugs, and Weaknesses Found

## Scope

This document records the issues identified during the repository review of:

`https://github.com/thisIsRajbirMajhi/Coarse-Alignment-Simulator`

Repository branch reviewed: `Main`

Review focus:

- V2 autonomy architecture
- optical spot detection
- photodiode/beacon reception
- target association
- Kalman tracking
- supervisor/FSM
- reacquisition
- PID/PTZ control integration
- `deep_headless_test.py`
- false-detection / false-lock behavior
- configuration consistency
- validation correctness

This is an engineering issue report for the problems found during the review. It is **not** a claim that these are every possible defect in the entire codebase.

---

# 1. Executive Summary

The simulator is no longer suffering from a missing high-level architecture. Most of the major V2 components already exist:

```text
Physical simulation
    ↓
Disturbance model
    ↓
Camera
    ↓
Visual detector
    ↓
Photodiode / beacon receiver
    ↓
Identity validation
    ↓
Association
    ↓
Kalman tracker
    ↓
Supervisor / FSM
    ↓
PID / PTZ
```

The main problems found are now concentrated in:

1. **test/validation correctness**
2. **configuration inconsistencies**
3. **association robustness**
4. **state-transition validation**
5. **false-candidate interpretation**
6. **tracking-gate correctness**
7. **legacy/duplicate autonomy paths**

The most important point is:

> **Do not redesign the complete architecture again. Fix the implementation and validation issues first, then tune the autonomy using measured failures.**

---

# 2. Severity Classification

| Severity | Meaning |
|---|---|
| Critical | Can invalidate the simulator's autonomy behavior or make test conclusions unreliable |
| High | Can cause false lock, acquisition failure, incorrect state behavior, or major validation errors |
| Medium | Can degrade robustness, maintainability, or performance under difficult scenarios |
| Low | Cleanup, consistency, or future-hardening issue |

---

# 3. Confirmed / Concrete Issues

## BUG-01 — Stale FSM Transition Table in `deep_headless_test.py`

**Severity:** Critical

### Problem

The actual V2 supervisor contains states similar to:

```text
SEARCH
IDENTIFY
ASSOCIATE
TRACK
COAST
LOST
REACQUIRE
FAULT
```

However, the transition validation logic in `deep_headless_test.py` is still based on an older state model containing states such as:

```text
IDLE
SEARCH
IDENTIFY
TRACK
COAST
```

The test's `VALID_TRANSITIONS` model is therefore stale.

### Why this is a bug

The test harness is validating the system against a different FSM than the one actually implemented.

That means:

- valid V2 transitions can be reported as invalid
- invalid transitions can escape detection
- `invalid_transitions` statistics can be misleading
- regression results cannot be trusted

### Example

A legitimate sequence such as:

```text
SEARCH → IDENTIFY → ASSOCIATE → TRACK
```

may be interpreted incorrectly by a test table that does not contain `ASSOCIATE`.

Likewise:

```text
TRACK → COAST → LOST → REACQUIRE
```

cannot be validated correctly if `LOST` and `REACQUIRE` are missing from the test transition model.

### Required fix

Make the test transition table exactly match the authoritative supervisor state graph.

Preferably:

- define the transition graph in one authoritative place
- expose/read it from the supervisor
- let the test import/use that source rather than maintaining a second manually copied graph

### Do not do

Do not simply add missing states to the test and continue maintaining two independently edited state diagrams.

---

# BUG-02 — `false_candidate_frames` Metric Does Not Necessarily Mean "False Detection"

**Severity:** High

### Problem

The deep headless test currently treats cases such as:

- a visual spot exists
- but no decoded TID / beacon identity is available

as a "false candidate" type of condition.

That is not equivalent to a false visual detection.

### Why this is incorrect

A visual candidate can be completely real while:

- the photodiode frame has not arrived yet
- the beacon is temporarily faded
- decoding fails for one frame
- the communication path is noisy
- identity confirmation is delayed

Therefore:

```text
visual candidate without decoded identity
```

is not automatically:

```text
false visual detection
```

### Impact

This can inflate the reported false-detection rate and make the detector look worse than it actually is.

It also mixes multiple failure modes:

```text
detector failure
communication failure
identity timing failure
association failure
```

into one metric.

### Required fix

Rename/redefine the metric.

A better intermediate metric is:

```text
unconfirmed_candidate_frames
```

For actual detector evaluation, use simulator ground truth **only in the evaluation layer**, for example:

```text
true positive
false positive
false negative
missed target
wrong target association
```

Ground truth must not be injected into the controller/autonomy logic.

---

# BUG-03 — Detector Area Configuration Is Internally Overridden

**Severity:** High

### Problem

The autonomy configuration exposes candidate-area limits such as:

```text
candidate_min_area_px
candidate_max_area_px
```

but the detector internally applies additional hard limits approximately equivalent to:

```text
min_area = max(12, configured_min_area)
max_area = min(250, configured_max_area)
```

This means the public configuration does not actually control the detector over its advertised range.

For example, if configuration says:

```text
candidate_min_area_px = 4
candidate_max_area_px = 4000
```

the effective detector range can still become:

```text
12 … 250
```

### Why this is a bug

The configuration presents one behavior while the implementation enforces another.

This causes:

- confusing tuning
- misleading experiment configuration
- parameters that appear to have no effect
- difficulty reproducing test results
- hidden behavior in detector internals

### Required fix

Choose one of these designs.

### Preferred

Let configuration directly drive the detector:

```text
effective_min_area = configured_min_area
effective_max_area = configured_max_area
```

and validate those values when the configuration is created.

### Alternative

If safety bounds are required, explicitly represent them:

```text
configured_min_area
hard_min_area
configured_max_area
hard_max_area
```

and make the interaction explicit.

Do not silently override user configuration inside the detector.

---

# BUG-04 — Test Validation and Controller State Model Have Diverged

**Severity:** High

### Problem

The existence of an outdated transition model in the test suite indicates that the implementation and the validation model are being maintained independently.

The supervisor has evolved to a more explicit V2 lifecycle, while the stress-test logic still contains assumptions from the older lifecycle.

### Impact

This creates a dangerous situation:

```text
System changes
    ↓
Supervisor behavior changes
    ↓
Test still checks old assumptions
    ↓
Tests may pass/fail for the wrong reasons
```

### Required fix

Create one authoritative state definition.

Recommended structure:

```text
supervisor.py
    ├── states
    ├── transition rules
    └── transition/event definitions

deep_headless_test.py
    └── imports/uses supervisor definitions for validation
```

The test may still impose additional safety assertions, but it should not maintain a stale copy of the core FSM.

---

# BUG-05 — Simplified Mahalanobis Gate Does Not Use the Full 2D Innovation Covariance

**Severity:** Medium / High

### Current behavior

The tracking association gate is effectively using a scalarized distance of the form:

```text
d² = (dx² + dy²) / variance
```

rather than the full Kalman innovation covariance:

```text
ν = z - Hx'
S = HPHᵀ + R

d² = νᵀ S⁻¹ ν
```

### Why this matters

The current form assumes the uncertainty can effectively be represented by one scalar variance.

A Kalman tracker naturally produces covariance information describing uncertainty in both axes.

The full 2D Mahalanobis gate can account for:

- different uncertainty in X and Y
- correlated uncertainty
- prediction uncertainty
- measurement noise
- changing uncertainty during coasting/reacquisition

### Impact

This can result in:

- overly restrictive gates in some situations
- overly permissive gates in others
- less physically correct association behavior
- reduced robustness when motion uncertainty becomes anisotropic

### Required fix

Upgrade the gate to:

```text
S = HPHᵀ + R
d² = νᵀ S⁻¹ ν
```

This is a **V2.1 improvement**, not a reason to replace the Kalman filter or redesign the tracker.

---

# 4. Association and False-Lock Weaknesses

## BUG/WEAKNESS-06 — Acquisition Association Gate Is Very Large and Static

**Severity:** High

### Current behavior

The acquisition association gate has been increased to approximately:

```text
association_gate_px ≈ 200 px
```

This was done because a smaller gate (around 60 px) caused acquisition failures when the scan position was offset.

### Problem

A large static gate solves one problem:

```text
target is outside a small gate
```

but introduces another:

```text
many unrelated bright objects are now eligible
```

This becomes especially dangerous in:

- star clutter
- multiple bright candidates
- off-axis scan positions
- noisy detector scenes

### Impact

The association system can become more dependent on:

- boresight proximity
- candidate brightness/SNR
- timing
- beacon availability

than it should be.

### Risk

A nearby star or wrong candidate may satisfy the broad spatial gate before the true target is strongly confirmed.

### Required improvement

Do not immediately solve this by guessing a new fixed number.

Instead make the acquisition gate context-aware using factors such as:

```text
scan-cell / current search position
+
beacon presence
+
expected image location
+
temporal persistence
+
identity validity
+
Kalman uncertainty when tracking
```

The long-term goal is:

```text
static 200 px gate
        ↓
context-dependent spatial gate
```

---

# BUG/WEAKNESS-07 — Association Selection Can Depend Too Strongly on Boresight Proximity

**Severity:** High

### Current behavior

Acquisition association roughly follows:

1. require a valid beacon/identity condition
2. find visual spots
3. retain candidates within the association gate
4. require sufficient SNR
5. choose the candidate near boresight
6. use SNR as a tie-breaker

### Problem

Boresight proximity is useful, but it is not strong evidence of target identity.

A bright star can easily be:

- closer to the center
- high SNR
- within the large association gate

while still being the wrong optical source.

### Impact

Potential false association / false lock under clutter.

### Required improvement

The decision should increasingly use:

```text
identity
+
spatial consistency
+
temporal consistency
+
motion consistency
+
measurement quality
```

rather than primarily:

```text
closest to boresight
+
high SNR
```

---

# BUG/WEAKNESS-08 — Visual and Beacon Sensors Are Not Being Used as a Full Confirmation Chain

**Severity:** Medium / High

### Current architecture

The two sensors are correctly separated:

```text
camera  → spatial information
photodiode → communication/identity information
```

However, acquisition robustness depends heavily on how aggressively these signals are fused at the association/confirmation stage.

### Failure mode

A sequence can effectively become:

```text
bright visual spot
+
valid beacon somewhere in the system
→
associate candidate
```

when what is safer is:

```text
visual candidate
→
temporal persistence
→
beacon identity
→
spatial consistency with expected target position
→
confirmed target
```

### Required improvement

Treat the sensors as complementary evidence, not as independent triggers.

A valid beacon should significantly increase confidence, but the optical candidate should still satisfy spatial/temporal consistency before confirmation.

---

# BUG/WEAKNESS-09 — Two-Frame Temporal Confirmation Is Potentially Too Weak for Cluttered Scenes

**Severity:** Medium

### Current behavior

Visual confirmation is approximately:

```text
confirm_frames = 2
```

with a spatial consistency gate and area/SNR checks.

### Problem

Two consecutive observations can still be produced by:

- stars
- persistent hot structures
- repeated noise patterns
- camera artifacts
- clutter that remains stationary relative to the simulated camera

This is particularly relevant in star-heavy scenes.

### Required improvement

Do not change this automatically.

First measure false-lock behavior.

A possible later strategy is:

```text
3-of-5 frames
```

or another hysteresis scheme.

The correct value should be selected from stress-test results, not assumed in advance.

---

# 5. Tracker / State-Machine Weaknesses

## BUG/WEAKNESS-10 — Supervisor Debounce Counters Can Become a Second State Machine

**Severity:** Medium

The supervisor contains hidden counters such as:

```text
_assoc_pending
_track_miss_streak
_track_hit_streak
```

These are useful for hysteresis.

### Problem

They become dangerous if their logic starts independently defining transitions that are not represented clearly in the FSM.

That produces:

```text
explicit FSM
+
implicit counter-driven FSM
```

which becomes difficult to reason about.

### Required rule

Keep the counters strictly as transition confirmation mechanisms:

```text
association hit count
track hit count
track miss count
```

They must not become an independent state model.

---

# BUG/WEAKNESS-11 — Reacquisition Search Radius Is Fixed Rather Than Uncertainty-Driven

**Severity:** Medium

### Current ladder

The current reacquisition sequence is approximately:

```text
50 px
100 px
200 px
400 px
800 px
full scan
```

### What is good

The ladder is a sensible staged recovery mechanism.

### Weakness

The radii are fixed and therefore do not directly reflect:

- Kalman covariance
- last known velocity
- elapsed coast time
- disturbance magnitude
- uncertainty growth

### Example

A target that has been lost for a short time with low covariance should not necessarily receive the same search region as a target that has been missing for a long time after a large disturbance.

### Future improvement

Use uncertainty-informed search:

```text
search radius ∝ predicted positional uncertainty
```

while retaining a hard maximum and staged fallback.

This is a future robustness improvement, not a reason to replace the current reacquisition ladder immediately.

---

# BUG/WEAKNESS-12 — Fixed Spatial Thresholds Are Not Scaled by Measurement Uncertainty

**Severity:** Medium

Several current checks use fixed pixel thresholds, for example:

```text
~12 px temporal confirmation gate
~200 px acquisition gate
fixed reacquisition radii
```

### Problem

A fixed pixel threshold does not automatically adapt to:

- different camera resolutions
- different optical noise
- different focal lengths / FOVs
- different Kalman uncertainty
- high-motion vs low-motion conditions

### Impact

A threshold tuned for one simulator condition may become wrong under another.

### Required direction

Where practical, thresholds should be linked to:

- measurement covariance
- predicted covariance
- FOV/image geometry
- configured detector resolution

Do this incrementally rather than redesigning every module at once.

---

# 6. Configuration / Architecture Problems

## BUG-13 — Duplicate / Legacy Autonomy Configuration Path

**Severity:** Medium

There is still a compatibility/migration layer where older configuration concepts coexist with the newer V2 autonomy configuration.

This includes legacy concepts such as:

```text
LocalTerminalConfig
```

alongside:

```text
AutonomyConfig
```

### Problem

Two configuration paths create ambiguity over which setting is authoritative.

### Risks

- parameter duplication
- inconsistent defaults
- changes applied to one path but not another
- harder debugging
- accidental use of legacy behavior

### Required fix

After V2 behavior is validated:

1. identify which legacy configuration fields are still used
2. migrate required values into the V2 configuration
3. remove dead/duplicate configuration paths
4. make one configuration object authoritative

---

# BUG-14 — Legacy Compatibility Code Can Hide Incomplete V2 Migration

**Severity:** Medium

The presence of compatibility logic is useful during migration, but it can hide whether the actual V2 system is fully authoritative.

### Risk

A code path may appear to use:

```text
V2 detector
V2 tracker
V2 supervisor
```

while another path still injects legacy behavior.

### Required action

Trace the runtime execution path from simulator start to control output.

Verify that V1/legacy autonomy components are not silently bypassing or modifying V2 results.

Then remove unnecessary compatibility code.

---

# 7. Test-System Problems

## BUG-15 — Test Suite Does Not Clearly Separate Detector Errors from Communication Errors

**Severity:** High

The deep test suite currently mixes events from:

```text
camera
detector
photodiode
decoder
identity
association
tracking
FSM
```

when determining candidate/lock quality.

### Why this matters

Suppose:

```text
camera sees the correct target
photodiode frame is corrupted
```

That should be classified as a communication/identity failure, not as a detector false positive.

Similarly:

```text
photodiode identifies RT-002
camera candidate corresponds to RT-003
```

is an association problem.

### Required improvement

Track metrics separately:

```text
Detection:
    TP / FP / FN

Identity:
    correct TID / wrong TID / missing TID

Association:
    correct association / wrong association / no association

Tracking:
    position error / innovation / loss

FSM:
    valid / invalid transitions

Control:
    pointing error / settling time
```

---

# BUG-16 — No Single End-to-End Ground-Truth Classification Layer

**Severity:** Medium / High

The simulator already has enough internal information to evaluate against ground truth, but the metrics need clearer separation.

### Required evaluation model

For every frame, the evaluator should know:

```text
ground-truth target position
ground-truth target identity
detector candidates
selected candidate
decoded TID
tracker state
controller output
```

Then classify failures explicitly:

```text
MISS
FALSE DETECTION
WRONG IDENTITY
WRONG ASSOCIATION
FALSE LOCK
TRACK LOSS
REACQUISITION FAILURE
CONTROL ERROR
```

This is substantially more useful than a single aggregate false-candidate counter.

---

# BUG-17 — Transition Metrics Can Be Wrong Even When Runtime Behavior Is Correct

**Severity:** High

This is a consequence of BUG-01 and BUG-04.

A correct runtime sequence can still be counted as invalid because the test suite's transition definitions are stale.

### Result

Metrics such as:

```text
invalid_transitions
```

cannot currently be treated as authoritative until the transition model is corrected.

### Required action

Fix the transition model before using transition statistics to judge autonomy quality.

---

# 8. What Is NOT a Bug

The following were considered during the review but should **not** be treated as current defects by themselves.

## NOT-BUG-01 — Using a Kalman Filter

The current constant-velocity Kalman filter with:

```text
[x, y, vx, vy]
```

plus process noise, measurement noise, prediction, update, coasting and uncertainty is a valid foundation.

Do not replace it with:

- particle filters
- optical flow
- JPDA
- MHT
- neural tracking

unless future testing demonstrates a requirement.

---

## NOT-BUG-02 — Photodiode + Camera as Separate Sensors

This is an appropriate sensor separation:

```text
Camera → spatial position
Photodiode → identity / optical communication
```

The issue is not the architecture itself. The main issue is how strongly and correctly the information is fused during association and confirmation.

---

## NOT-BUG-03 — Reacquisition Ladder Itself

The sequence:

```text
50 → 100 → 200 → 400 → 800 px → full scan
```

is reasonable.

It is simply less adaptive than a future uncertainty-driven approach.

Do not remove it prematurely.

---

## NOT-BUG-04 — Temporal Confirmation

Temporal confirmation itself is correct and desirable.

The issue is that:

```text
2 frames
```

may be insufficient under certain clutter conditions.

This should be measured before changing.

---

# 9. Recommended Fix Order

Do not fix these in arbitrary order.

## Phase 1 — Correct the Test Harness

### 1. Fix FSM transition validation

Make the transition model match:

```text
SEARCH
IDENTIFY
ASSOCIATE
TRACK
COAST
LOST
REACQUIRE
FAULT
```

### 2. Rename/rework candidate metrics

Replace the misleading:

```text
false_candidate_frames
```

with distinct evaluation metrics.

### 3. Add explicit ground-truth classification

Produce:

```text
TP
FP
FN
wrong identity
wrong association
false lock
track loss
reacquisition failure
```

before making detector/autonomy tuning decisions.

---

# Phase 2 — Fix Deterministic Implementation Bugs

### 4. Fix detector area configuration

Remove hidden:

```text
max(12, ...)
min(250, ...)
```

behavior unless those are explicitly documented hard limits.

### 5. Verify the runtime configuration source

Make one V2 configuration object authoritative.

### 6. Trace and remove unintended legacy execution paths

Ensure old autonomy logic cannot silently affect V2 behavior.

---

# Phase 3 — Validate Nominal Operation

Run controlled tests in this order:

```text
1. Single target, clean conditions
2. Single target + detector noise
3. Single target + star clutter
4. Beacon fade
5. Temporary visual loss
6. Target reacquisition
7. Wrong-TID injection
8. Multiple optical candidates
9. Nearby bright star
10. Large pointing disturbance
```

---

# Phase 4 — Fix Association Robustness

Only after the metrics are trustworthy:

### 7. Analyze the 200 px association gate

Do not blindly replace it with another fixed value.

Determine:

```text
How often does the target fall outside the gate?
How many false candidates fall inside it?
How often does the wrong candidate win?
```

### 8. Strengthen target confirmation

Use:

```text
identity
+
spatial consistency
+
temporal consistency
+
motion consistency
+
measurement quality
```

---

# Phase 5 — Tracker Robustness

### 9. Upgrade to full 2D Mahalanobis gating

Use:

```text
ν = z - Hx'
S = HPHᵀ + R
d² = νᵀS⁻¹ν
```

### 10. Add innovation monitoring

Monitor unexpectedly large normalized innovations as an indicator of:

- wrong association
- sudden disturbance
- measurement corruption

---

# Phase 6 — Future Adaptive Improvements

Only after real test evidence:

```text
3-of-5 temporal confirmation
dynamic association gates
uncertainty-driven ROI
uncertainty-driven reacquisition
stronger local background estimation
adaptive measurement noise
legacy-code cleanup
```

---

# 10. Suggested Debug Logging

For every acquisition/association event, log at minimum:

```text
timestamp
FSM state
target TID
decoded TID
candidate count
candidate positions
candidate areas
candidate SNR
candidate peak intensity
selected candidate
distance to boresight
distance to predicted tracker state
Mahalanobis distance
Kalman covariance
association gate
confirmation count
track hit/miss count
innovation
```

For every loss event:

```text
last confirmed position
last predicted position
last covariance
last candidate position
last decoded TID
reason for transition
reacquisition level
time since last confirmed measurement
```

This will make false-lock failures traceable instead of requiring visual inspection of the whole simulation.

---

# 11. Failure Classification to Use Going Forward

Every failed run should end with one primary failure class:

```text
ACQUISITION_TIMEOUT
FALSE_VISUAL_DETECTION
MISSED_VISUAL_DETECTION
MISSING_BEACON_IDENTITY
WRONG_BEACON_IDENTITY
WRONG_ASSOCIATION
FALSE_LOCK
TRACKING_DIVERGENCE
TRACK_LOSS
REACQUISITION_FAILURE
INVALID_FSM_TRANSITION
CONTROL_SETTLING_FAILURE
SIMULATION/TEST_HARNESS_ERROR
```

This prevents unrelated failures from being grouped together.

---

# 12. Overall Assessment

The repository's main issue is **not missing modules**.

The V2 architecture already contains most of the necessary building blocks.

The current risk is that the simulator can produce results that look meaningful while some of the evaluation logic is still measuring the old system or conflating different failure modes.

The most important corrections are therefore:

```text
Fix test correctness
        ↓
Fix configuration correctness
        ↓
Measure real false locks
        ↓
Strengthen association
        ↓
Improve Kalman gating
        ↓
Only then tune thresholds
```

The project should remain architecturally simple.

Avoid adding complexity such as:

```text
neural detector
particle filter
MHT
JPDA
optical flow
multi-model filters
large ML fusion network
```

until the current deterministic pipeline has been properly validated.

---

# 13. Priority Table

| ID | Issue | Severity | Priority |
|---|---|---:|---:|
| BUG-01 | Stale FSM transition table | Critical | P0 |
| BUG-02 | False-candidate metric misclassification | High | P0 |
| BUG-03 | Detector area configuration overridden | High | P0 |
| BUG-04 | Test/runtime FSM divergence | High | P0 |
| BUG-15 | Detector vs communication failures conflated | High | P0 |
| BUG-16 | Weak ground-truth failure classification | Medium/High | P0 |
| BUG-17 | Invalid transition statistics | High | P0 |
| BUG-06 | Large static association gate | High | P1 |
| BUG-07 | Boresight-heavy association | High | P1 |
| BUG-08 | Incomplete confirmation fusion | Medium/High | P1 |
| BUG-05 | Simplified Mahalanobis gate | Medium/High | P1 |
| BUG-09 | Two-frame confirmation may be weak | Medium | P2 |
| BUG-10 | Counters potentially becoming second FSM | Medium | P2 |
| BUG-11 | Fixed reacquisition ladder | Medium | P2 |
| BUG-12 | Fixed pixel thresholds | Medium | P2 |
| BUG-13 | Duplicate/legacy configuration | Medium | P2 |
| BUG-14 | Legacy compatibility path | Medium | P2 |

---

# 14. Final Engineering Direction

The next development cycle should **not** be:

```text
rewrite architecture
```

It should be:

```text
correct metrics
→
correct configuration
→
run controlled scenarios
→
classify failures
→
fix the responsible module
→
rerun regression tests
```

The system is now at the point where measured failure data should drive the next changes.
