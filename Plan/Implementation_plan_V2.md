# Implementation Plan — V1 FSOC Coarse-Alignment Tracking Redesign

**Version:** 2.0 — Aligned to V1 Target Model Specification
**Supersedes:** Implementation_plan.md (v1)

---

## 0. Purpose

This document is the implementation specification for an AI coding agent that will
**redesign the existing `Coarse-Alignment-Simulator` autonomy and tracking pipeline**
around a simpler, cleaner architecture built for:

- fast, deterministic execution,
- reliable acquisition and tracking of multiple remote terminals,
- one actively controlled PTZ target at a time,
- physical received-beam-power (P_rx) and beacon identity (TID) as the primary
  target-identification signals,
- camera image centroid as the sole spatial measurement for closed-loop control,
- realistic disturbances and genuinely closed-loop behavior,
- minimal algorithmic complexity.

The redesign **MUST preserve** the simulator's required physical components
(remote-terminal motion, optical emission, atmospheric/disturbance models,
PTZ camera/gimbal dynamics, camera sensor, photodiode receiver, beacon protocol,
PID controller, coordinate transforms, GUI/headless simulation, deterministic tests)
while removing or consolidating unnecessary autonomy complexity.

This is an **implementation plan**, not an invitation to redesign the physics model.
Changes to the physical model must be explicitly justified and isolated from the
autonomy redesign.

---

## 1. Core Design Decision

### 1.1 New pipeline (one sentence)

```
Coarse PTZ search
  → received-power / SNR detection
  → beacon TID/CRC identification
  → camera spot detection
  → TID/spatial association
  → 2D constant-velocity Kalman tracking
  → image-based PID
  → PTZ/camera feedback
  → uncertainty-based coast/loss
  → target-specific local reacquisition
  → TID confirmation
  → return to tracking
```

### 1.2 Architecture diagram

```
                     ┌──────────────────────┐
                     │        SEARCH        │
                     │  coarse PTZ raster   │
                     └──────────┬───────────┘
                                │ optical candidate (P_rx / SNR)
                     ┌──────────▼───────────┐
                     │       IDENTIFY       │
                     │  beacon TID + CRC    │
                     └──────────┬───────────┘
                                │ valid target
                     ┌──────────▼───────────┐
                     │      ASSOCIATE       │
                     │  TID ↔ image spot    │
                     └──────────┬───────────┘
                                │ selected
                     ┌──────────▼───────────┐◄────────────────┐
                     │        TRACK         │                 │
                     │  Kalman predict/upd  │                 │
                     └──────────┬───────────┘                 │
                                │ measurement missing         │
                     ┌──────────▼───────────┐                 │
                     │        COAST         │                 │
                     │  Kalman predict only │                 │
                     └──────────┬───────────┘                 │
                                │ uncertainty/timeout         │
                     ┌──────────▼───────────┐                 │
                     │         LOST         │                 │
                     └──────────┬───────────┘                 │
                                │                             │
                     ┌──────────▼───────────┐                 │
                     │      REACQUIRE       │─────────────────┘
                     └──────────────────────┘
                                (TID confirmed → TRACK)

FAULT remains as a safety/system state but MUST NOT dominate the normal path.
```

### 1.3 Important simplification

The simulator supports **multiple targets**, but the PTZ control loop controls
**one active target at a time**.

Do NOT build a full simultaneous multi-object tracker.

The system maintains:

- a mission registry containing all target configurations,
- lightweight observation information for multiple targets,
- one active `TargetTrack` for the PTZ controller,
- lightweight last-known records for previously observed targets.

---

## 2. Design Principles

### 2.1 Separate WHO, WHERE, and HOW STRONG

```
Terminal ID        → WHO is transmitting?
Image centroid     → WHERE is the optical spot?
Received P_rx (W)  → HOW STRONG is the received beam?
Kalman tracker     → WHERE will it be next?
PID                → HOW should the PTZ move?
```

Do not use one quantity for another purpose.

### 2.2 Fast path vs. parallel path

The tracking/control loop must remain fast.

**Fast path — every camera frame:**

```
camera frame
  → spot detection
  → association with active target (via predicted position gate)
  → Kalman prediction/update
  → image error
  → PID
  → PTZ
```

**Parallel path — runs independently, never blocks the fast path:**

```
photodiode
  → clock recovery / beacon decode
  → TID + CRC + metadata
  → candidate identity update
```

The 30 Hz camera loop **MUST NOT** wait for a complete ~336 ms beacon frame.
The beacon decoder runs asynchronously and pushes updates when a frame completes.

### 2.3 No ground-truth leakage

Ground-truth terminal position, velocity, internal state, or scenario geometry
**MUST NOT** be passed into:

- detector,
- tracker,
- association,
- selector,
- reacquisition,
- PID error generation.

Ground truth may only be used inside the physical simulation layers
that generate sensor observations.

### 2.4 Prefer deterministic classical algorithms

V1 uses only:

- thresholding,
- connected components,
- centroid calculation,
- temporal confirmation,
- nearest-neighbour association,
- Mahalanobis gating,
- Kalman filtering,
- expanding search windows,
- PID.

AI is a future extension point, not the foundation of V1.
See Section 17 for the explicit AI integration interface.

### 2.5 Configuration must remain external

Target-specific differences (TID, optical power, wavelength, modulation,
beam divergence, motion profile, pointing behavior, operational state)
must continue to come from scenario/mission configuration,
not from hardcoded autonomy logic.

---

## 3. What V1 Explicitly Does NOT Contain

The following are **deliberately excluded** from V1.
Do not implement them unless a later requirement explicitly demands it.

| Excluded feature | Reason |
|---|---|
| AI detector / YOLO / RT-DETR / CNN | Not needed for V1 |
| Quadrant detector | Not necessary for first working architecture |
| Particle filter | Too complex for this problem |
| EKF / UKF | State model is linear enough for standard KF |
| Full multi-object tracking | One active target; others use last-known records |
| Hungarian assignment | TID + spatial gating is sufficient |
| Elaborate composite confidence score | Use straightforward gates and signal quality |
| Standby candidate pool | Not needed in the primary implementation |
| Complex strike lifecycle | Keep basic invalid-beacon handling |
| MPC / Reinforcement Learning | PID is sufficient |
| Full multi-emitter waveform demodulation | Use existing dominant-source simplification |

---

## 4. Existing System — Keep / Simplify / Remove

### 4.1 Keep

| Component | Decision | Reason |
|---|---|---|
| `remote_terminal/*` | KEEP | Physical target/beam/configuration model is required |
| `camera/*` | KEEP | PTZ, FOV, sensor and kinematics are required |
| `disturbance/*` | KEEP | Needed for robustness testing |
| `environment/*` | KEEP | Required simulation environment |
| `common/coordinates.py` | KEEP | Coordinate transforms are fundamental |
| `common/protocol/beacon/*` | KEEP | Beacon protocol and CRC are required |
| `local_terminal/comm_receiver.py` | KEEP + simplify API | Physical photodiode/decoder is valuable |
| `local_terminal/scan.py` | KEEP + simplify | Coarse search is required |
| `local_terminal/detector.py` | KEEP + simplify | Camera spot localisation is required |
| `local_terminal/tracker.py` | REDESIGN | Replace with `KalmanFilter2D` + active `TargetTrack` |
| PID controller | KEEP | Required closed-loop control |
| PTZ dynamics | KEEP | Required plant/actuator model |
| Tests | KEEP + rewrite around new contracts | Preserve regression coverage |
| GUI / headless simulation | KEEP | Required for evaluation and debugging |

### 4.2 Simplify

**`local_terminal/validator.py` → `identity.py`**

Keep:
- CRC gate,
- TID registry lookup,
- self-ID rejection,
- wavelength check (within tolerance),
- modulation check,
- sequence freshness,
- optional basic strike counter for repeated invalid traffic.

Remove:
- composite 0.60 confidence score,
- centroid-stability evidence used as identity signal,
- power-consistency weighted score,
- elaborate `DETECTED → DECODING → SIGNATURE_CHECK → SCORED → SELECTED` lifecycle.

**`local_terminal/selector.py`**

Keep:
- selection among validated terminals,
- mission priority support,
- explicit target switching.

Remove:
- complex score ranking as the default mechanism,
- large standby candidate scoring infrastructure.

Default selector: mission priority if configured, otherwise highest-quality
currently observed target.

**`local_terminal/reacquisition.py`**

Keep the escalation concept. Simplify to exactly four levels:

```
1. Predicted local window
2. Expanded local window
3. Last-known region
4. Full coarse scan
```

Remove the standby-pool stage entirely from V1.

**`local_terminal/supervisor.py`** (previously `autonomy.py`)

Replace the existing large state flow with the compact FSM described in Section 5.

---

## 5. State Machine

### 5.1 States

```
SEARCH
IDENTIFY
ASSOCIATE
TRACK
COAST
LOST
REACQUIRE
FAULT
```

`ASSOCIATE` is an explicit state between IDENTIFY and TRACK.
It is not merely an internal processing step — it is visible in telemetry
and allows the supervisor to handle association failures cleanly.

### 5.2 State definitions

#### SEARCH

PTZ follows the coarse scan schedule (20-position 4×5 grid, 10% overlap).

Inputs:
- camera frame,
- photodiode received power,
- beacon decoder output.

Goal: find a plausible optical candidate.

Transition:
```
P_rx >= SNR_min AND optical spot detected → IDENTIFY
```

#### IDENTIFY

Confirm the decoded terminal identity against the mission registry.

Checks:
```
CRC valid
TID known in mission registry
TID != local ID
wavelength within tolerance
modulation acceptable
sequence fresh
```

Transition:
```
all checks pass → ASSOCIATE
any check fails → SEARCH
```

#### ASSOCIATE

Match the validated TID with the best image-plane spot candidate.

At initial acquisition, associate using boresight proximity:

```
nearest camera spot to FOV centre → associated with decoded TID
```

Association succeeds when:
```
valid TID from IDENTIFY
AND camera spot within boresight gate at acquisition time
AND spot quality acceptable (SNR, area)
```

Transition:
```
association succeeds → TRACK (Kalman initialised from spot)
association fails    → IDENTIFY (retry from identity stage)
```

#### TRACK

Fast closed-loop state. Runs every camera frame.

```
predict
  → detect spots
  → Mahalanobis gate
  → associate active target with nearest in-gate spot
  → Kalman update with measurement (R scaled by SNR)
  → compute image-plane pixel error
  → PID
  → PTZ
```

When SNR is high (e.g. 25 dB): trust camera measurement more (smaller R).
When SNR is low (e.g. 6 dB): trust prediction more (larger R).

Transition:
```
measurement missing this frame → COAST
```

#### COAST

Temporary detection loss. Kalman continues with predict-only step.
PID uses predicted position during configurable grace period.
Covariance grows each missed frame.

Example covariance growth (to be calibrated against actual Q):

```
1 missed frame  → uncertainty ≈  3 px
5 missed frames → uncertainty ≈  9 px
10 missed frames → uncertainty ≈ 22 px
```

Transition:
```
valid measurement returns → TRACK (Kalman update, covariance reduced)
uncertainty > threshold OR timeout → LOST
```

#### LOST

Active target no longer has a trustworthy image measurement.
PID is disabled or held safely (safe-hold command).
Reacquisition begins immediately.

Transition criterion — use BOTH conditions:

```
time_since_valid_measurement > loss_timeout_s
AND
kalman_uncertainty > lost_uncertainty_threshold_px
```

Do NOT use only a raw missed-frame count.

Transition:
```
→ REACQUIRE
```

#### REACQUIRE

Search only for the lost target.
At each search position, check:

```
P_rx?   → Is there a beam?
beacon? → Can it be decoded?
TID?    → TID == lost active target?
```

Escalation ladder (expanding radius centred on Kalman predicted position):

```
50 px radius
  ↓ miss
100 px radius
  ↓ miss
200 px radius
  ↓ miss
400 px radius
  ↓ miss
800 px radius
  ↓ miss
Full coarse scan
```

If a different valid TID is observed during reacquisition:
```
record as candidate
do NOT accept as reacquisition of lost target
```

Transition:
```
TID == lost target AND other checks pass → TRACK (via REACQUIRE → TRACK fast path)
```

See Section 14 for the full REACQUIRE → TRACK confirmation contract.

#### FAULT

Only for actual system conditions:
- invalid/inconsistent configuration,
- controller numerical failure,
- impossible sensor output,
- repeated reset-loop condition,
- unrecoverable internal simulation exception.

A normal no-target condition is NOT a fault.

---

## 6. Core Data Models

All data classes live in `local_terminal/models.py`.

### 6.1 `SpotCandidate`

Camera-only observation. No identity belongs here.

```python
@dataclass
class SpotCandidate:
    x: float
    y: float
    peak: float
    snr_db: float
    area_px: int
    sigma_px: float | None = None
```

### 6.2 `BeaconObservation`

Photodiode/beacon decoder output.

```python
@dataclass
class BeaconObservation:
    terminal_id: str
    valid_crc: bool
    sequence: int | None
    wavelength_nm: float | None
    modulation: str | None
    p_rx_w: float
    snr_db: float
    timestamp_s: float
```

### 6.3 `TargetObservation`

The fully merged observation produced by the association step.
This is the unit that flows into the Kalman update and PID.

```python
@dataclass
class TargetObservation:
    terminal_id: str
    fov_x: float          # image-plane x in pixels
    fov_y: float          # image-plane y in pixels
    p_rx_w: float         # physical received power
    snr_db: float         # for adaptive R
    timestamp_s: float
```

Example:
```python
TargetObservation(
    terminal_id="RT-002",
    fov_x=421.3,
    fov_y=238.7,
    p_rx_w=0.0018,
    snr_db=18.4,
    timestamp_s=12.53,
)
```

### 6.4 `TargetTrack`

Active Kalman track state for one target. Produced by `tracker.py`.

```python
@dataclass
class TargetTrack:
    terminal_id: str
    x: float                  # Kalman filtered image-plane x
    y: float                  # Kalman filtered image-plane y
    vx: float                 # estimated pixel velocity x
    vy: float                 # estimated pixel velocity y
    uncertainty_px: float     # position uncertainty (from covariance)
    last_measurement_time_s: float
    last_beacon_time_s: float | None
    p_rx_w: float
    misses: int
    status: str               # "TRACKING" | "COASTING" | "LOST"
```

Example:
```python
TargetTrack(
    terminal_id="RT-002",
    x=420.7,
    y=239.1,
    vx=35.2,
    vy=-4.7,
    uncertainty_px=3.8,
    status="TRACKING",
)
```

### 6.5 `AutonomyConfig`

All autonomy tuning parameters in one place.

```python
@dataclass
class AutonomyConfig:
    # Search
    search_pattern: str             # "systematic" | "last_known" | "predicted"
    search_dwell_frames: int        # default 1
    search_extended_dwell_frames: int  # extended dwell when P_rx candidate found

    # Detection
    candidate_min_snr_db: float
    candidate_peak_margin: float
    candidate_confirm_frames: int   # temporal confirmation count (2-3)

    # Association
    association_gate_px: float      # base gate at acquisition
    association_mahal_threshold: float  # Mahalanobis gate during tracking

    # Kalman
    kalman_process_noise_q: float
    kalman_measurement_noise_r_base: float
    kalman_r_scale_low_snr: float   # R multiplier when SNR is poor
    kalman_r_scale_high_snr: float  # R multiplier when SNR is good

    # Coast / Lost thresholds
    coast_max_uncertainty_px: float
    coast_timeout_s: float
    lost_uncertainty_threshold_px: float
    lost_timeout_s: float

    # Reacquisition
    reacq_radii_px: list[float]     # e.g. [50, 100, 200, 400, 800]
    reacq_full_scan_enabled: bool

    # Selector
    active_target_policy: str       # "priority" | "strongest_prx" | "highest_snr"
```

---

## 7. V1 Data Flow

```
TargetObservation
       ↓
   Association
       ↓
  Kalman update
       ↓
  TargetTrack
       ↓
     PID
```

The `TargetObservation` is the only struct that crosses the sensor-autonomy boundary.
It is assembled by `association.py` from `SpotCandidate` (camera) and
`BeaconObservation` (photodiode/beacon decoder).

---

## 8. Sensor Architecture

### 8.1 Camera sensor

The camera provides spatial information only:

```
frame
  → grayscale
  → background estimate
  → adaptive threshold
  → connected components
  → component filters (area, SNR, optional compactness)
  → centroid
  → SpotCandidate[]
```

Recommended initial gates for the detector:
- minimum peak above background,
- minimum SNR,
- minimum component area,
- optional maximum component area.

Temporal confirmation: require 2–3 consecutive detections at approximately
the same location before promoting a spot to a reacquisition candidate.
(A one-frame hot pixel must be rejected.)

Avoid expensive Gaussian fitting unless benchmarks show it is necessary.

### 8.2 Photodiode receiver (`comm_receiver.py`)

The photodiode provides:

```
P_rx_W
SNR_dB
BER estimate
beacon synchronisation
TID
CRC
sequence
wavelength
modulation
```

The existing physical receiver model must be retained.

### 8.3 Beacon runs parallel to camera loop

The beacon decoder must operate on a separate path.
The 30 Hz camera-frame loop must NOT wait for a complete ~336 ms beacon frame.
The decoder pushes a `BeaconObservation` into a shared slot whenever a frame
completes; the camera loop reads the latest available observation.

### 8.4 Multi-emitter simplification

Keep the existing dominant/nearest-to-boresight capture-effect simplification.
Full mixed-beam multi-emitter demodulation is not a V1 requirement.

---

## 9. Detection Design

### 9.1 Objective

Detection only needs to answer:

> Is there a plausible optical spot in this frame, and where is its centroid?

It does NOT determine target identity.

### 9.2 Algorithm

```
frame
  → gray
  → background estimate
  → threshold = background + configurable margin
  → connected components
  → component filters
  → centroid
  → SpotCandidate[]
```

### 9.3 Temporal confirmation

Use short temporal confirmation rather than sophisticated image classification.

```
Frame N:   spot at (320, 240)
Frame N+1: spot at (322, 241)
Frame N+2: spot at (321, 239)
→ likely real candidate
```

Make the confirmation count configurable (default: 2–3 frames).

---

## 10. Identity and Received Power

### 10.1 Received power is the primary signal-strength gate

A target is eligible for identification only when the received signal is
above the configured detection floor:

```
SNR_dB >= candidate_min_snr_db
```

Retain `P_rx_W` as the physical telemetry value.
Do not hardcode a single absolute power threshold that ignores noise conditions.

### 10.2 Identity gate

```
valid_crc
AND known_tid
AND tid != local_id
AND wavelength within tolerance
AND modulation acceptable
```

Sequence freshness is used to reject stale/replayed traffic.

### 10.3 Blacklist — keep it lightweight

```
invalid observation → ignore

repeated invalid observation from known TID
  → optional strike counter

N strikes within window
  → session blacklist
```

Normal detector misses do NOT cause strikes.

---

## 11. TID ↔ Camera Spot Association

### 11.1 At initial acquisition

Use boresight proximity (consistent with the dominant-source photodiode model):

```
FOV centre = (320, 240)

Spot A = (311, 236)  distance = 10 px
Spot B = (455, 241)  distance = 135 px

Decoded TID = RT-002

→ associate RT-002 with Spot A
```

### 11.2 During tracking

Do not re-solve global multi-target identity association every frame.
Use the active target's Kalman predicted position and Mahalanobis gate:

```
predicted position
  → Mahalanobis gate
  → nearest in-gate spot → measurement for Kalman update
```

This prevents the tracker from jumping to another terminal merely because
it momentarily becomes brighter or closer to boresight.

### 11.3 For multiple simultaneous visible targets

Association uses three signals in order of precedence:

1. **Identity** — prefer the spot whose TID matches the active target.
2. **Spatial consistency** — compare the spot with the target's predicted position.
3. **Signal consistency** — optionally use P_rx / SNR for additional confidence.

### 11.4 Association gate

During tracking, use Mahalanobis distance:

```
innovation r = z - H x_pred
gate matrix S = H P_pred H^T + R
Mahalanobis distance d² = r^T S⁻¹ r

accept measurement if d² < mahal_threshold
```

This allows the gate to grow naturally during COAST and tighten when well-observed.

A fixed pixel-radius fallback may be used for initial acquisition only.

### 11.5 Outlier rejection

A single implausible detection must not move the track.
Use the same Mahalanobis calculation: reject if `d²` exceeds the gate threshold.
Rejection increments a diagnostic counter but does not immediately cause loss.

---

## 12. Target Tracking

### 12.1 Kalman filter

Replace the existing tracker with `KalmanFilter2D` using state:

```
x = [x, y, vx, vy]^T
```

where `x, y` are image-plane coordinates (pixels) and
`vx, vy` are pixel/second velocities.

The filter must expose:
```
predicted_x, predicted_y
filtered_x, filtered_y
velocity_x, velocity_y
position_uncertainty_px    (derived from covariance diagonal)
```

### 12.2 Prediction model

Standard constant-velocity transition for frame interval `dt`:

```
[x ]   [1  0  dt  0 ] [x ]
[y ]   [0  1  0   dt] [y ]
[vx] = [0  0  1   0 ] [vx]
[vy]   [0  0  0   1 ] [vy]
```

### 12.3 Measurement model

```
z = [measured_x, measured_y]^T
```

The measurement covariance `R` must scale adaptively with signal quality:

```
High-quality detection (SNR = 25 dB) → smaller R → trust camera measurement more
Poor detection       (SNR = 6 dB)  → larger R → trust prediction more
```

### 12.4 Coasting

When no acceptable measurement arrives:

```
Kalman predict only (no update)
  → covariance grows
  → PID continues using predicted position
```

Covariance growth examples (to be calibrated against `Q`):

```
 1 missed frame  → uncertainty ≈  3 px
 5 missed frames → uncertainty ≈  9 px
10 missed frames → uncertainty ≈ 22 px
```

Do not reset the filter immediately on a missed frame.

### 12.5 COAST → LOST transition

Do not rely on a raw miss count alone.
Use BOTH elapsed time and uncertainty:

```
COAST
  ↓
kalman_uncertainty still below threshold → continue
  ↓
kalman_uncertainty > coast_max_uncertainty_px
OR elapsed_since_valid > coast_timeout_s
  ↓
LOST
```

Expose all thresholds through `AutonomyConfig`.

### 12.6 Multiple targets

Maintain at most:

```
mission registry
+
one active KalmanFilter2D track
+
lightweight last-known position/time records for other validated TIDs
```

---

## 13. Closed-Loop Control

### 13.1 Control loop

```
image centroid
  → Kalman filtered position
  → pixel error
  → PID
  → pan/tilt velocity command
  → PTZ dynamics
  → new camera FOV
  → new image
```

Image error:

```
e_x = x_filtered - W/2
e_y = y_filtered - H/2
```

**The PID must use the Kalman estimated image position, never target ground truth.**
This is what makes the simulator genuinely closed-loop.

### 13.2 PID configuration

Retain:
- proportional, integral, filtered-derivative terms,
- deadband,
- anti-windup,
- output limit,
- NaN/Inf protection.

### 13.3 PID during COAST and LOST

During COAST: PID uses the Kalman predicted position.
During LOST: PID is disabled; issue a safe-hold command until a valid
measurement is restored.

---

## 14. Search

### 14.1 Initial search

Use the existing 20-position 4×5 grid as the default systematic search.

```
640×480 FOV
10% overlap
4×5 = 20 cells
deterministic schedule
```

Keep the cell geometry configurable.

### 14.2 Search dwell

Default: 1 camera frame per cell.

If P_rx / SNR exceeds the candidate threshold during a scan cell:
```
extend dwell → allow beacon frame to complete decoding
```

Do not extend every scan cell to the full beacon frame duration.

### 14.3 Search priority modes

```
SYSTEMATIC    → default full raster
LAST_KNOWN    → last known target region
PREDICTED     → Kalman predicted position
```

---

## 15. Reacquisition

### 15.1 Entry condition

Enter REACQUIRE only after LOST is confirmed (see Section 5).

### 15.2 Escalation ladder

Centred on the Kalman predicted position at loss time:

```
50 px radius   → search
  ↓ miss
100 px radius  → search
  ↓ miss
200 px radius  → search
  ↓ miss
400 px radius  → search
  ↓ miss
800 px radius  → search
  ↓ miss
Full coarse scan (20-cell grid)
```

At each search position:
```
P_rx > threshold?   → is there a beam?
valid beacon?       → can it be decoded?
TID == lost target? → is this the right terminal?
```

### 15.3 Target identity is mandatory for reacquisition

Example:
```
Lost target = RT-002
Detected TID = RT-003
→ RT-002 NOT reacquired
→ RT-003 recorded as candidate but does not steal the lock
```

### 15.4 REACQUIRE → TRACK confirmation contract

All four conditions must be true simultaneously:

```
P_rx > p_rx_threshold
AND valid beacon CRC
AND TID == active_target
AND camera spot within expected region
```

When confirmed:
```
REACQUIRED
  → Kalman state reinitialised/updated from new observation
  → TRACK
```

No elaborate validation state machine is required.

---

## 16. Target Selection

### 16.1 One active PTZ target

The selector chooses exactly one target for closed-loop pointing.

### 16.2 Selection policy (configurable)

Default priority order:
1. Mission priority TID (if configured)
2. Highest P_rx
3. Highest SNR
4. Nearest predicted target

Example:
```
RT-001 priority = 1
RT-002 priority = 2
RT-003 priority = 3

RT-001 available? YES → select RT-001
```

Do not use a composite score unless later testing proves it necessary.

### 16.3 Target switching

A switch must be explicit.

Allowed reasons:
- active target permanently unavailable,
- mission priority change,
- user/manual change,
- target completes mission condition.

A random bright target **must never automatically steal the PTZ lock**.

---

## 17. AI Integration Point

AI is NOT required for V1. The architecture must make a future AI detector
easy to insert at exactly one point.

```
Camera Frame
  ↓
SpotDetector interface
  ├── ClassicalSpotDetector   ← V1 (default)
  └── AISpotDetector           ← future drop-in replacement
```

Both implementations must output:

```python
list[SpotCandidate]
```

The first recommended future AI role is a lightweight candidate verifier
that receives classical candidates and filters false positives.
Do not replace the whole physics + beacon + tracker + PID pipeline
with a general-purpose object detector.

---

## 18. V1 Module Structure

The redesigned `local_terminal/` must use this layout exactly:

```
local_terminal/
│
├── scan.py               Coarse PTZ search
│
├── detector.py           Camera spot detection
│
├── comm_receiver.py      Photodiode + beacon decoding  (parallel to camera)
│
├── identity.py           TID/CRC/config validation
│
├── association.py        TID ↔ camera spot association
│
├── tracker.py            KalmanFilter2D + active TargetTrack
│
├── selector.py           Multi-target active-target selection
│
├── reacquisition.py      Target-specific local-to-global reacquisition
│
├── supervisor.py         V1 state machine (SEARCH/IDENTIFY/ASSOCIATE/TRACK/
│                         COAST/LOST/REACQUIRE/FAULT)
│
└── models.py             SpotCandidate / BeaconObservation /
                          TargetObservation / TargetTrack / AutonomyConfig
```

**The existing physics layers stay outside this directory:**

```
remote_terminal/
camera/
disturbance/
environment/
common/
simulation/
```

### 18.1 Module responsibility rules

| Module | Owns | Must NOT touch |
|---|---|---|
| `scan.py` | PTZ search schedule, cell transitions | Identity, PID |
| `detector.py` | Spot detection, centroid, `SpotCandidate[]` | TID, mission registry, PID |
| `comm_receiver.py` | Photodiode physics, beacon decode, `BeaconObservation` | Camera, PTZ |
| `identity.py` | CRC gate, TID lookup, sequence, blacklist | Camera spots, PID |
| `association.py` | Merging TID + spot into `TargetObservation` | PTZ commands |
| `tracker.py` | Kalman state, uncertainty, coast flag | TID validation |
| `selector.py` | Choosing active target | Kalman internals, PID |
| `reacquisition.py` | Recovery search, escalation ladder | Active track state |
| `supervisor.py` | FSM transitions, high-level state | Camera processing, PID math |
| `models.py` | Data class definitions only | All logic |

---

## 19. Configuration

### 19.1 Remove duplicate target settings from camera configuration

Current camera configuration contains expected terminal fields
(`expected_tid`, `expected_wavelength_nm`, `expected_wl_tolerance_nm`,
`expected_require_nav`).

These must be moved to mission/receiver validation configuration.
Camera configuration describes the camera, not the remote mission registry.

### 19.2 `AutonomyConfig`

See Section 6.5. This is the single source of all autonomy tuning parameters.
Do not scatter threshold values across modules.

---

## 20. Telemetry

Expose at minimum:

```
state
active_target_id
p_rx_w
snr_db
last_decoded_tid
last_decoded_sequence
spot_count
active_spot_x
active_spot_y
predicted_x
predicted_y
track_vx
track_vy
track_uncertainty_px
tracking_error_x_px
tracking_error_y_px
miss_count
loss_count
reacquisition_count
reacquisition_time_s
reacq_radius_px           (current expanding search radius)
search_cell
pid_pan_cmd
pid_tilt_cmd
camera_pan
camera_tilt
```

Log all FSM state transitions with timestamp and reason:

```
1.233  SEARCH      → IDENTIFY    reason=beacon_detected
1.301  IDENTIFY    → ASSOCIATE   reason=RT-002_valid
1.302  ASSOCIATE   → TRACK       reason=spot_associated
3.842  TRACK       → COAST       reason=spot_missing
4.103  COAST       → TRACK       reason=spot_recovered
8.521  TRACK       → COAST       reason=spot_missing
8.600  COAST       → LOST        reason=uncertainty_threshold_exceeded
8.601  LOST        → REACQUIRE   reason=track_timeout
9.037  REACQUIRE   → TRACK       reason=RT-002_confirmed
```

Do not hide lifecycle behaviour in GUI-only variables.

---

## 21. Error Handling

### 21.1 Normal conditions are not faults

These are normal:
- no beam,
- no spot,
- invalid beacon,
- unknown TID,
- temporarily low SNR,
- target leaves FOV,
- target in OFF/STANDBY/FAULT operational state.

### 21.2 Fault conditions

Only raise FAULT for actual system-level failures:
- invalid/inconsistent configuration,
- controller numerical failure,
- impossible sensor output,
- repeated reset-loop condition,
- unrecoverable internal simulation exception.

---

## 22. Test Strategy

The redesign must be implemented **test-first at module boundaries**.

### 22.1 `models.py` / data contract tests

- all fields serialise and deserialise correctly,
- default values are sensible,
- `AutonomyConfig` rejects obviously invalid parameters.

### 22.2 Detector tests

1. clean Gaussian spot,
2. low-SNR spot,
3. hot pixel (must be rejected by temporal confirmation),
4. diffuse background,
5. multiple spots,
6. two close spots,
7. edge-of-FOV spot,
8. empty frame.

### 22.3 Beacon / identity tests

1. valid TID,
2. unknown TID,
3. self TID,
4. invalid CRC,
5. stale sequence,
6. freshening sequence,
7. different wavelengths,
8. different modulation types,
9. low-SNR input,
10. receiver clock offset.

### 22.4 Association tests

| Scenario | Expected |
|---|---|
| Two spots; nearest to boresight has matching TID | Nearest spot associated |
| Active track; brighter spot appears outside gate | Active track unchanged |
| No in-gate candidate | Miss recorded; coast begins |
| Mahalanobis distance exactly at threshold | Configurable edge behaviour |

Also test: active track must not jump to a different TID merely because it is brighter.

### 22.5 Tracker tests

- stationary target (zero velocity convergence),
- constant-velocity target,
- noisy centroid (covariance filter smooths),
- temporary missed frames (coast; covariance grows),
- long loss (LOST transition triggered),
- target crossing another spot (Mahalanobis gate prevents jump),
- measurement outlier rejected.

Verify covariance growth rate against calibrated `Q`.

### 22.6 Reacquisition tests

```
local recovery (50 px)
expanded recovery (100 px)
expanded recovery (200 px)
last-known region recovery
full-scan recovery
wrong TID during reacquisition → MUST NOT reacquire
no-target case
```

Wrong-TID example:
```
lost = RT-002
reacquisition sees RT-003
→ must NOT reacquire
→ must record RT-003 as candidate
```

### 22.7 Closed-loop tests

- measured image centroid drives PID,
- controller does not consume ground truth,
- PTZ rate/acceleration limits hold,
- final tracking error meets configured requirement,
- disturbances degrade performance realistically without bypassing the sensor loop,
- COAST and recovery cycle completes without instability.

---

## 23. Acceptance Scenarios

### Scenario A — One target, clean channel

```
start → raster scan → P_rx detected → RT-001 decoded → spot associated
  → TRACK → PID centres spot
```

Expected: acquisition within one scan cycle; stable track; final image error within limit.

### Scenario B — Multiple targets

```
RT-001 (1550 nm, 0.5 W, OOK)
RT-002 (1310 nm, 0.8 W, PPM)
RT-003 (1550 nm, 0.2 W, OOK)
```

Expected:
- valid IDs are distinguished by TID not power,
- active target does not randomly switch,
- each target can be acquired when requested by mission policy.

### Scenario C — Lost target and reacquisition

```
RT-002 TRACK → beam fades → COAST → LOST → REACQUIRE
  → local search finds RT-002 → TRACK
```

Expected:
- no immediate unnecessary full scan,
- correct TID identity restored,
- no false lock to RT-001 or RT-003.

### Scenario D — Wrong TID during reacquisition

```
Lost target = RT-002
Reacquisition observes: TID = RT-003
```

Expected: not accepted; RT-003 recorded as candidate; search continues.

### Scenario E — Low power fading

```
P_rx falls near sensitivity threshold
```

Expected: SNR degrades; tracker coasts; eventual LOST; reacquisition; no numerical instability.

### Scenario F — Disturbances

Include: camera jitter, pointing jitter, atmospheric attenuation, scintillation/fading,
encoder noise, mechanical lag/backlash.

Expected: closed loop remains stable; track may degrade but sensor-derived control
stays valid; reacquisition works after sufficiently severe loss.

### Scenario G — Normal successful run (end-to-end timeline)

```
t=0.00   SEARCH    camera scans grid
t=0.73   P_rx = 1.5 mW → optical candidate
t=0.79   Beacon decoded: TID = RT-002, CRC = PASS
t=0.80   Camera finds spot at (470, 260) → RT-002 associated
t=0.83   Kalman initialised → TRACK
t=0.83+  Kalman → PID → PTZ → camera loop begins
t=4.20   RT-002 temporarily fades → COAST
t=4.27   beam returns → Kalman UPDATE → TRACK
t=8.10   large fade → uncertainty exceeds threshold → LOST
t=8.13   REACQUIRE near Kalman predicted position
t=8.31   P_rx detected, TID = RT-002 → confirmed
t=8.32   TRACK
```

---

## 24. Physical-Model Boundary

The current repository already distinguishes physical optical emission from
visualisation in `remote_terminal/scenario.py`. Preserve this rule.

```
Physical optical power
        ↓
photodiode model
        ↓
P_rx_W / SNR / beacon decode
```

versus:

```
render_spots()
        ↓
visualisation marker
```

**Do NOT use the visualisation marker brightness formula as the receiver's
physical received-power measurement.**

If camera photometry is later calibrated to optical power,
implement a dedicated sensor calibration model.

---

## 25. Simplifications Explicitly Accepted for V1

V1 intentionally does NOT implement:

- full multi-emitter photodiode waveform separation,
- multi-object Kalman filter for every target simultaneously,
- deep learning spot detector,
- optical-flow tracking,
- particle filter,
- JPDA/MHT multi-object association,
- model-predictive control,
- reinforcement learning,
- large target-confidence scoring equations,
- large standby candidate graph,
- complex reset sub-state machines.

The simulator can support more sophisticated algorithms later through the
`SpotDetector` interface and by extending `AutonomyConfig`.
V1 must remain small and deterministic.

---

## 26. Migration Plan

Implement in this order. **Do not rewrite the whole repository in one step.**

### Phase 1 — Freeze and test physics

Before any autonomy changes:

1. Run all existing tests.
2. Identify and document current failures.
3. Ensure remote-terminal optics, disturbances, camera/PTZ, and PID remain reproducible.
4. Add regression tests for any valid physical behaviour at risk.

Do not change the physical model during this phase.

### Phase 2 — Introduce `models.py`

Add to `local_terminal/models.py`:

- `SpotCandidate`,
- `BeaconObservation`,
- `TargetObservation`,
- `TargetTrack`,
- `AutonomyConfig`.

Write unit tests for each data class.

### Phase 3 — Simplify `detector.py`

Replace the current large candidate-gating pipeline with the minimal classical
spot detector described in Section 9.

Keep an optional debug mode that reports old detector metrics during migration.

### Phase 4 — Simplify `comm_receiver.py`

Verify the photodiode and beacon decoder run in parallel with the camera loop.
Clean up the API to expose exactly `BeaconObservation` per decoded frame.

### Phase 5 — Implement `identity.py`

Replace the current large validator lifecycle with lightweight identity validation
as specified in Section 10.

Write tests before integrating into the supervisor.

### Phase 6 — Implement `association.py`

Implement the three-context association logic (acquisition, tracking, multi-target)
from Section 11.

Write tests before connecting to the supervisor.

### Phase 7 — Redesign `tracker.py`

Replace the existing tracker with a small `KalmanFilter2D` implementation.

Implement:
```
predict → Mahalanobis gate
measurement accepted → Kalman update (R scaled by SNR)
measurement missing → predict/coast
uncertainty too large or timeout → LOST signal
```

The Kalman implementation MUST expose configurable `Q`, `R`, and
the Mahalanobis gating threshold. Defaults must be calibrated in simulation,
not hardcoded from arbitrary values.

Add tests for:
- stationary target,
- constant-velocity target,
- noisy measurements,
- temporary misses,
- outlier rejection,
- covariance growth during coast,
- uncertainty-aware association gate.

### Phase 8 — Simplify `scan.py`

Retain the 20-cell 4×5 grid with the three priority modes (SYSTEMATIC,
LAST_KNOWN, PREDICTED). Remove unnecessary schedule complexity.

### Phase 9 — Simplify `reacquisition.py`

Implement the four-level expanding-radius escalation ladder exactly as
specified in Section 15, with the exact five default radii [50, 100, 200, 400, 800] px.

Require correct TID confirmation before returning to TRACK.

### Phase 10 — Simplify `selector.py`

Implement the three-policy selector (priority / strongest P_rx / highest SNR).
Remove composite score infrastructure.

### Phase 11 — Replace `supervisor.py`

Create the compact eight-state FSM (SEARCH / IDENTIFY / ASSOCIATE / TRACK /
COAST / LOST / REACQUIRE / FAULT).

Keep the old supervisor temporarily under a compatibility name if required,
but stop routing production simulation through the old architecture once
the new FSM passes acceptance tests.

### Phase 12 — Reconnect GUI and headless simulation

Update telemetry consumers to the new schema (Section 20).

The GUI must report at minimum:
- state,
- active target ID,
- P_rx,
- TID,
- camera spot (x, y),
- predicted spot (x, y),
- track uncertainty,
- PID output,
- loss/reacquisition counters.

### Phase 13 — Delete obsolete complexity

After all tests pass, remove or archive:

- old validation scoring path,
- obsolete standby-pool logic,
- duplicate state transitions,
- duplicate target-selection scoring,
- dead compatibility variables,
- telemetry fields that no longer reflect actual behaviour.

Do not leave two competing autonomy pipelines in the repository.

---

## 27. Compatibility and Refactoring Rules

The AI agent MUST NOT:

- modify public APIs unnecessarily,
- break existing GUI behaviour without replacing it,
- silently change units (keep pixels / degrees / metres / radians separate),
- use target ground truth in autonomy code,
- use visualisation brightness as a physical sensor value,
- remove physical disturbances just because they complicate tracking,
- add ML dependencies to the baseline runtime,
- introduce asynchronous concurrency unless benchmarking proves it is required.

When an old module becomes obsolete:

1. replace its callers,
2. run targeted tests,
3. run full tests,
4. delete the obsolete implementation.

---

## 28. Definition of Done

### Architecture

- [ ] New compact FSM is the only production autonomy path.
- [ ] SEARCH / IDENTIFY / ASSOCIATE / TRACK / COAST / LOST / REACQUIRE / FAULT
      are all implemented and visible in telemetry.
- [ ] One active target is controlled at a time.
- [ ] Multiple targets with different configurations are supported.
- [ ] Module structure matches Section 18 exactly.

### Sensor integrity

- [ ] `P_rx_W` comes from the photodiode physical model.
- [ ] TID comes from beacon decoding.
- [ ] Spatial target position comes from camera observations / Kalman tracker.
- [ ] No ground-truth target position reaches the autonomy or controller path.
- [ ] Visualisation brightness is not used as physical received power.
- [ ] Beacon decoder runs in parallel; camera loop never waits for it.

### Tracking

- [ ] 2D constant-velocity Kalman tracking is stable at the configured camera rate.
- [ ] Measurement covariance `R` adapts to SNR.
- [ ] Mahalanobis gating is used for both association and outlier rejection.
- [ ] Temporary misses produce COAST, not immediate LOST.
- [ ] LOST is triggered by time + uncertainty, not raw miss count alone.
- [ ] Active track cannot jump to a distant unrelated target.

### Reacquisition

- [ ] Expanding-radius local search occurs before full scan.
- [ ] Correct TID is required for reacquisition confirmation.
- [ ] Wrong target IDs cannot silently steal the lock.
- [ ] Full REACQUIRE → TRACK confirmation contract enforced (Section 15.4).

### Control

- [ ] PID consumes image-derived Kalman filtered position.
- [ ] PID respects output limits and anti-windup.
- [ ] PTZ respects speed/acceleration/travel limits.
- [ ] Closed-loop tracking remains stable with disturbances.
- [ ] PID is disabled (safe-hold) during LOST.

### Performance

- [ ] Camera/tracking path meets the intended frame-rate budget.
- [ ] Beacon decoding does not block the PID loop.
- [ ] No unnecessary ML dependency is required.

### Testing

- [ ] Unit tests for `models.py`, `detector.py`, `identity.py`, `association.py`,
      `tracker.py`, `reacquisition.py`, `selector.py`, `supervisor.py` pass.
- [ ] Multi-target scenario tests pass.
- [ ] Wrong-TID reacquisition test passes.
- [ ] Low-power/fading test passes.
- [ ] Disturbance closed-loop test passes.
- [ ] Full headless simulation acceptance tests (Scenarios A–G) pass.
- [ ] Repeated runs with identical seed/config remain deterministic.

---

## 29. Example End-to-End Walkthrough

### Three configured targets

```
RT-001: P_tx = 0.5 W, wavelength = 1550 nm, modulation = OOK
RT-002: P_tx = 0.8 W, wavelength = 1310 nm, modulation = PPM
RT-003: P_tx = 0.2 W, wavelength = 1550 nm, modulation = OOK
```

Mission priority: RT-001 > RT-002 > RT-003.

Camera starts at home.

**Step 1 — SEARCH:** PTZ moves to cell 0. No beam. Continue.

**Step 2 — Optical candidate:** At cell 7, P_rx = 0.95 mW, SNR = 18 dB.
Camera sees: Spot A = (323, 241), Spot B = (480, 250).

**Step 3 — IDENTIFY:** Photodiode decodes TID = RT-002, CRC = PASS,
wavelength = 1310 nm, modulation = PPM, sequence = 31.
Registry confirms RT-002.

**Step 4 — ASSOCIATE:** FOV boresight = (320, 240).
Spot A distance = 3.2 px; Spot B distance = 160 px.
RT-002 associated with Spot A.

**Step 5 — TRACK:** Kalman initialised: x=323, y=241, vx=0, vy=0.
Subsequent frames update the filter.

**Step 6 — Control:** Pixel error: e_x = 323-320 = +3 px, e_y = 241-240 = +1 px.
PID generates small PTZ correction.

**Step 7 — Disturbance:** Jitter shifts measured spot to (328, 245).
Kalman filter smooths. PID corrects.

**Step 8 — COAST:** Spot disappears for 3 frames due to fade.
Kalman predicts forward. PID uses predicted position.

**Step 9 — LOST:** Uncertainty exceeds threshold after timeout.
PID enters safe hold. Reacquisition begins.

**Step 10 — REACQUIRE:** PTZ searches from 50 px radius.
Sees TID = RT-001 first → NOT accepted (lost target was RT-002).
Next position: TID = RT-002, CRC = PASS, camera spot matches expected region.
RT-002 confirmed. TRACK resumes.

---

## 30. Final Implementation Rule

When choosing between two valid implementations, prefer the one that is:

```
simpler
  ↓
more deterministic
  ↓
lower latency
  ↓
easier to test
  ↓
easier to replace later
```

Do NOT add complexity merely because a more advanced algorithm exists.

The reference V1 pipeline is:

```
COARSE SEARCH (20-cell raster)
  ↓
RECEIVED POWER / SNR gate
  ↓
BEACON DECODE (parallel thread)
  ↓
TID + CRC VALIDATION
  ↓
CAMERA SPOT ASSOCIATION (boresight at acquisition; Mahalanobis during tracking)
  ↓
2D CONSTANT-VELOCITY KALMAN FILTER (R adaptive to SNR)
  ↓
PIXEL ERROR  (e_x = x_filtered - W/2,  e_y = y_filtered - H/2)
  ↓
PID
  ↓
PTZ CAMERA
  ↓
CLOSED LOOP

TRACK → COAST (covariance grows) → LOST (time + uncertainty)
  → REACQUIRE (50→100→200→400→800 px → full scan)
  → TID CONFIRMED → TRACK
```

This is the baseline to implement before considering AI detectors,
nonlinear filtering, multi-object tracking, full multi-emitter photodiode
demodulation, or any other advanced subsystem.
