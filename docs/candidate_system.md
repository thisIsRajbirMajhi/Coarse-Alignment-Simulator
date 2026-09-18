# Candidate System

> **Scope**: Candidate data model, lifecycle state machine, state transition rules, track management, and telemetry.

---

## 1. Overview

A **candidate** is a locally-maintained track record for a blob observed in the camera image. Each candidate is born when an unmatched blob is detected, progresses through a lifecycle as the receiver gathers more information about it, and is eventually either acquired as the active target, rejected, or expired.

```
Blob detected → CandidateTrack created (SEEN)
                     │
                     ▼ (lifecycle engine drives transitions)
                     ...
                     ▼
              TRACKING / REJECTED / LOST / EXPIRED
```

---

## 2. CandidateTrack (`models.py`)

The `CandidateTrack` is the central data structure. Every piece of information the receiver knows about a candidate is stored here.

```python
@dataclass
class CandidateTrack:
    # ── Identity ──────────────────────────────────────────────────
    observation_id: str              # "BEACON-001"  (local, never from RT)
    decoded_terminal_id: str | None  # "RT-001" after successful decode
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    last_valid_sequence: int | None
    identity_state: IdentityState    # VALID_TARGET, WRONG_TERMINAL, etc.
    identity_reason: str
    identity_confidence: float       # 0–1
    valid_frame_count: int
    invalid_frame_count: int
    identity_fail_streak: int

    # ── Lifecycle ─────────────────────────────────────────────────
    lifecycle_state: CandidateState  # enum, see below
    created_at_s: float
    last_updated_s: float
    missed_frame_count: int

    # ── Optical ───────────────────────────────────────────────────
    latest_measurement: OpticalMeasurement | None
    centroid_history: deque[tuple[float, float]]   # (x, y) per frame
    timestamp_history: deque[float]
    intensity_history: deque[float]

    # ── Signal / Decode ───────────────────────────────────────────
    signal_quality: float
    modulation_detected: bool
    sync_state: SyncState
    sync_confidence: float
    decode_state: DecodeState
    decode_reason: str
    last_valid_frame: BeaconDecodeResult | None
    last_valid_frame_time: float | None

    # ── Spatial State ─────────────────────────────────────────────
    position_estimate: np.ndarray    # [x_px, y_px]  filtered centroid
    velocity_estimate: np.ndarray    # [vx, vy]  pixels/frame
    position_uncertainty: np.ndarray # Kalman P matrix diagonal
    predicted_position: np.ndarray   # one-step ahead

    # ── Tracking / Acquisition ────────────────────────────────────
    spatial_lock: bool
    identity_lock: bool
    acquisition_quality: float

    # ── Wavelength ────────────────────────────────────────────────
    measured_wavelength_nm: float | None    # from spectral estimate
    decoded_wavelength_nm: float | None     # from payload
    wavelength_consistency: float | None    # agreement metric

    # ── Legacy ───────────────────────────────────────────────────
    legacy_optical_identification_enabled: bool = False
```

---

## 3. Lifecycle State Machine (`states.py`, `lifecycle.py`)

### 3.1 States

```python
class CandidateState(Enum):
    # Active progression states
    SEEN            = "SEEN"
    TENTATIVE       = "TENTATIVE"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    DECODING        = "DECODING"
    IDENTITY_UNKNOWN = "IDENTITY_UNKNOWN"
    IDENTIFIED      = "IDENTIFIED"
    SELECTED        = "SELECTED"
    ACQUIRING       = "ACQUIRING"
    ACQUIRED        = "ACQUIRED"
    TRACKING        = "TRACKING"
    DEGRADED        = "DEGRADED"
    REACQUIRING     = "REACQUIRING"

    # Terminal / failure states
    REJECTED        = "REJECTED"
    LOST            = "LOST"
    EXPIRED         = "EXPIRED"
```

### 3.2 Primary Transition Diagram

```
        ┌──────────────────────────────────────────────────────────────┐
        │                                                              │
       SEEN                                                            │
        │  blob persists ≥ min_persistence_frames                      │
        ▼                                                              │
    TENTATIVE                                                          │
        │  temporal signal analysis → modulation pattern detected      │
        ▼                                                              │
  SIGNAL_DETECTED                                                      │
        │  frame decoder is activated                                  │
        ▼                                                              │
     DECODING                                                          │
        │  a complete frame received, but identity not yet validated   │
        ▼                                                              │
  IDENTITY_UNKNOWN                                                     │
        │  required_valid_frames unique valid sequences received       │
        │  + all identity fields match                                 │
        ▼                                                              │
    IDENTIFIED                                                         │
        │  system selects this candidate                               │
        ▼                                                              │
    SELECTED                                                           │
        │  PTZ begins centering manoeuvre                             │
        ▼                                                              │
    ACQUIRING                                                          │
        │  identity lock + spatial lock                                │
        ▼                                                              │
    ACQUIRED ──────────────────────────────────────────────────────────┤
        │  centroid stable, PTZ in closed loop                         │
        ▼                                                              │
    TRACKING ◄──────────────────────────────────────────────┐         │
        │                           │                        │         │
        │  quality metrics low      │  temporary signal loss │         │
        ▼                           │                        │         │
    DEGRADED ───────────────────────┘    persistent failure  │         │
        │                                                    │         │
        │  too many fails                                    │         │
        ▼                                                    │         │
   REACQUIRING ──────────────────────────────────────────────┘         │
        │                                                              │
        │  timeout without successful reacquisition                    │
        ▼                                                              │
      LOST                                                             │
        │  (retired after timeout)                                     │
        ▼                                                              │
    EXPIRED                                                            │
                                                                       │
  ─────────────────────────────────────────────────────────────────────│
  Failure transitions (can occur from many states):                    │
  WRONG_TERMINAL / identity mismatch  ─────────────────────────────►  REJECTED
  persistent reacquisition failure    ─────────────────────────────►  LOST
```

### 3.3 Transition Rules (Detailed)

#### SEEN → TENTATIVE

```
condition:
    missed_frame_count == 0
    AND frame_count ≥ min_persistence_frames (default: 2)
```

#### TENTATIVE → SIGNAL_DETECTED

```
condition:
    signal_analyzer.modulation_detected == True
    AND signal_quality ≥ min_signal_quality
```

#### SIGNAL_DETECTED → DECODING

```
condition:
    signal_quality ≥ decoding_threshold
    AND history_length ≥ min_decode_history_samples
```

#### DECODING → IDENTITY_UNKNOWN

```
condition:
    at least one complete frame received (frame_detected == True)
    AND is_new_frame == True
    (identity not yet validated)
```

#### IDENTITY_UNKNOWN → IDENTIFIED

```
condition:
    identity_state == VALID_TARGET
    AND valid_frame_count ≥ required_valid_frames
    AND all unique sequences (no duplicates counted)
```

> **Absolute rule**: optical quality alone can NEVER trigger IDENTIFIED.

#### → REJECTED (from any active state)

```
condition:
    identity_state == WRONG_TERMINAL
    OR identity_state == WRONG_TOKEN
    OR identity_state == WRONG_PROTOCOL
    OR (identity_fail_streak > max_identity_fail_streak
        AND NOT in grace period)
```

#### IDENTIFIED → SELECTED

```
condition:
    selection_engine chooses this candidate
    (must have correct digital identity)
```

#### SELECTED → ACQUIRING

```
condition:
    acquisition_engine activates PTZ command
```

#### ACQUIRING → ACQUIRED

```
condition:
    identity_lock == True
    AND spatial_lock == True
    (dual-lock)
```

#### ACQUIRED → TRACKING

```
condition:
    centroid stable over min_tracking_frames
    AND PTZ in closed-loop
```

#### TRACKING → DEGRADED

```
condition:
    identity_fail_streak > 0
    OR signal_quality < degradation_threshold
    OR snr < degradation_snr_threshold
```

#### DEGRADED → TRACKING (recovery)

```
condition:
    new valid frame received
    AND identity_state == VALID_TARGET
    AND quality recovered above thresholds
```

#### DEGRADED → REACQUIRING

```
condition:
    identity_fail_streak > max_identity_fail_streak
    OR blob lost for > max_missed_frames
```

#### REACQUIRING → TRACKING (successful)

```
condition:
    can_merge_reacquisition(old_track, new_candidate) == True
    (full identity + sequence + spatial gate check)
```

#### REACQUIRING → LOST

```
condition:
    reacquisition_timeout exceeded
```

---

## 4. Candidate Selection Rules

When multiple candidates exist simultaneously, the `SelectionEngine` picks one for acquisition.

### Priority Order

```
1. IDENTIFIED candidate with correct digital identity
       (must have identity_state == VALID_TARGET)
2. Among multiple IDENTIFIED candidates:
       sort by (identity_confidence × signal_quality × optical_quality)
3. Never select based on optical brightness alone
```

### Hard Exclusions

| Condition | Excluded |
|-----------|----------|
| `identity_state == WRONG_TERMINAL` | Always |
| `identity_state == WRONG_TOKEN` | Always |
| `identity_state == WRONG_PROTOCOL` | Always |
| `lifecycle_state == REJECTED` | Always |
| Not yet IDENTIFIED | In normal mode |

---

## 5. Track History Buffers

Each candidate maintains bounded circular deques:

```python
history_size = compute_history_size(
    camera_fps=30.0,
    chip_rate_hz=12.0,
    frame_bits=168,
    safety_factor=3.0,
    reacquisition_margin_s=5.0,
)

centroid_history = deque(maxlen=history_size)
timestamp_history = deque(maxlen=history_size)
intensity_history = deque(maxlen=history_size)
```

The history size is computed — not hard-coded — to guarantee the decoder always has at least two complete beacon frames available.

---

## 6. Telemetry (`telemetry_mgr.py`)

The `TelemetryManager` exports per-candidate and global telemetry.

### Per-Candidate Telemetry

```python
@dataclass
class CandidateTelemetry:
    observation_id: str
    lifecycle_state: str
    decoded_terminal_id: str | None
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    sequence_number: int | None
    last_valid_sequence: int | None
    identity_state: str
    identity_reason: str
    identity_confidence: float
    valid_frame_count: int
    invalid_frame_count: int
    frame_sync_state: str
    frame_sync_confidence: float
    decode_state: str
    decode_reason: str
    estimated_chip_rate_hz: float | None
    signal_quality: float
    optical_quality: float
    snr: float
    centroid_x: float | None
    centroid_y: float | None
    missed_frames: int
```

### Global Telemetry

```python
@dataclass
class SystemTelemetry:
    system_state: str
    active_observation_id: str | None
    active_decoded_terminal_id: str | None
    identity_state: str
    identity_confidence: float
    frame_sync_state: str
    last_sequence_number: int | None
    acquisition_state: str
    tracking_state: str
    reacquisition_state: str
    candidate_count: int
    active_candidate_count: int
    rejected_candidate_count: int
```

---

## 7. IdentityState and ValidatorResult

```python
class IdentityState(Enum):
    VALID_TARGET        = "VALID_TARGET"
    WRONG_TERMINAL      = "WRONG_TERMINAL"
    WRONG_TOKEN         = "WRONG_TOKEN"
    WRONG_PROTOCOL      = "WRONG_PROTOCOL"
    WAVELENGTH_MISMATCH = "WAVELENGTH_MISMATCH"
    INVALID_SEQUENCE    = "INVALID_SEQUENCE"
    UNKNOWN             = "UNKNOWN"

class IdentityReasonCode(Enum):
    DUPLICATE_SEQUENCE     = "DUPLICATE_SEQUENCE"
    OLD_SEQUENCE           = "OLD_SEQUENCE"
    SEQUENCE_DISCONTINUITY = "SEQUENCE_DISCONTINUITY"
    CRC_FAILURE            = "CRC_FAILURE"
    LOW_CONFIDENCE         = "LOW_CONFIDENCE"
    INSUFFICIENT_FRAMES    = "INSUFFICIENT_FRAMES"
    TOKEN_MISMATCH         = "TOKEN_MISMATCH"
    TID_MISMATCH           = "TID_MISMATCH"
    WAVELENGTH_MISMATCH    = "WAVELENGTH_MISMATCH"
    PROTOCOL_MISMATCH      = "PROTOCOL_MISMATCH"
    NO_DATA                = "NO_DATA"
    OK                     = "OK"
```
