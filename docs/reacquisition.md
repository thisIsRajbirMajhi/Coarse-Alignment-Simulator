# Reacquisition

> **Scope**: Identity-gated reacquisition — staged spatial search, candidate evaluation, identity gate, and track merge rules.

---

## 1. Overview

Reacquisition is triggered when tracking degrades to the point that the target lock is broken — either because the blob is lost, the signal fails persistently, or an identity swap is detected. The receiver searches predictively around the last known position, decodes any candidate found, and merges back to the old track **only** if a new valid identity-matching sequence is received.

```
REACQUIRING state
    │
    ▼
ReacquisitionEngine
    │
    ├── predict target position (Kalman extrapolation)
    │
    ├── Stage 1: ±2° search window
    ├── Stage 2: ±5° search window  (if Stage 1 fails)
    ├── Stage 3: ±10° search window (if Stage 2 fails)
    │
    ▼ candidates found in search
    │
    ├── CandidateDetector → new candidate tracks
    │
    ├── Signal extraction → modulation detection
    │
    ├── Frame decode → BeaconDecodeResult
    │
    ├── Identity validation → IdentityDecision
    │
    └── Merge gate: can_merge_reacquisition(old_track, new_candidate)?
            │
            ├── YES → restore lock → ACQUIRED → TRACKING
            └── NO  → keep searching / LOST on timeout
```

---

## 2. Trigger Conditions

Reacquisition is entered from `DEGRADED` when:

```python
trigger_reacquisition = (
    track.identity_fail_streak > config.max_identity_fail_streak
    OR track.missed_frame_count > config.max_missed_frames_before_reacquire
    OR track.identity_state == WRONG_TERMINAL   # identity swap
)
```

---

## 3. Position Prediction

The Kalman filter extrapolates the last known position forward in time:

```python
def predict_position(track: CandidateTrack, dt_s: float) -> np.ndarray:
    return (
        track.position_estimate
        + track.velocity_estimate * dt_s
        + 0.5 * track.acceleration_estimate * dt_s ** 2
    )
```

The predicted position grows increasingly uncertain as `dt_s` increases. This uncertainty expands the spatial gate.

```python
position_uncertainty_px = sqrt(
    track.position_uncertainty_diagonal[0]
    + (track.velocity_uncertainty * dt_s) ** 2
)
```

---

## 4. Staged Search

```
Stage    │  Angular window   │  Search pattern      │  Priority
─────────┼───────────────────┼──────────────────────┼───────────
Stage 1  │  ±2° radius       │  Spiral / raster     │  High
Stage 2  │  ±5° radius       │  Expanding spiral    │  Medium
Stage 3  │  ±10° radius      │  Expanding raster    │  Low
```

Each stage has a configurable dwell time. If no valid target is found within the stage's timeout, the search expands to the next stage.

```python
@dataclass
class ReacquisitionConfig:
    stage_radii_deg: list[float] = field(default_factory=lambda: [2.0, 5.0, 10.0])
    stage_timeout_s: list[float] = field(default_factory=lambda: [5.0, 10.0, 15.0])
    reacquisition_total_timeout_s: float = 30.0
    spatial_gate_px: float = 30.0
    pattern: str = "spiral"
```

---

## 5. Identity Gate: `can_merge_reacquisition`

This function is the definitive rule for whether a newly found candidate can restore the old target lock:

```python
def can_merge_reacquisition(
    old_track: CandidateTrack,
    new_candidate: CandidateTrack,
    reacquisition_spatial_gate_px: float,
) -> bool:

    # 1. Both tracks must exist
    if old_track is None or new_candidate is None:
        return False

    # 2. Old track must have had a verified identity
    if not old_track.decoded_terminal_id:
        return False

    # 3. New candidate must have achieved identity validation
    if not new_candidate.identity_matched:
        return False

    # 4. Terminal IDs must match
    if old_track.decoded_terminal_id != new_candidate.decoded_terminal_id:
        return False

    # 5. New sequence must be strictly greater (new liveness)
    if (new_candidate.last_valid_sequence is None
            or old_track.last_valid_sequence is None):
        return False
    if new_candidate.last_valid_sequence <= old_track.last_valid_sequence:
        return False

    # 6. Spatial gate: new candidate near predicted position
    predicted = old_track.predicted_position
    actual = new_candidate.position_estimate
    spatial_error_px = euclidean(actual, predicted)
    if spatial_error_px > reacquisition_spatial_gate_px:
        return False

    return True
```

### What Each Check Prevents

| Check | Prevented Failure |
|-------|------------------|
| `decoded_terminal_id` on old | Merging if old was never identified |
| `identity_matched` on new | Merging without digital proof |
| Terminal ID match | Wrong RT-999 masquerading as RT-001 |
| New sequence > old sequence | Replayed/duplicated frames restoring lock |
| Spatial gate | Wildly incorrect association |

---

## 6. Wrong Terminal During Reacquisition

Canonical scenario:
```
Old target:   RT-001, seq=100
Target disappears at t=60s

RT-999 appears near predicted position at t=62s
```

Required behaviour:

```
RT-999 detected
    → signal extracted
    → frame decoded
    → PayloadDecoder produces: tid="RT-999"
    → IdentityValidator: WRONG_TERMINAL (TID_MISMATCH)
    → can_merge_reacquisition → False (TID mismatch at step 4)
    → RT-999 candidate → REJECTED
    → Reacquisition search continues
    → RT-999 never becomes active target
```

The decoder **actually decodes** the wrong terminal's identity — this is desirable. The system must not rely on the wrong terminal being optically indistinguishable.

---

## 7. Correct Terminal Reappearing

Canonical scenario:
```
Old target:   RT-001, seq=100
Target disappears at t=60s

RT-001 reappears at t=90s with seq=105
```

Required behaviour:

```
RT-001 detected (new candidate BEACON-005)
    → signal extracted
    → frame decoded
    → PayloadDecoder produces: tid="RT-001", seq=105
    → IdentityValidator: VALID_TARGET (OK, is_new_liveness=True)
    → can_merge_reacquisition:
          old_track.decoded_terminal_id = "RT-001" ✓
          new_candidate.identity_matched = True ✓
          TIDs match ✓
          new_seq (105) > old_seq (100) ✓
          spatial_error < gate ✓
    → Merge accepted
    → Old track restored
    → ACQUIRED → TRACKING
```

A duplicate sequence (`seq=100`) reappearing would fail step 5 and not restore the lock.

---

## 8. Merge Operation

When `can_merge_reacquisition` returns True:

```python
def merge_reacquisition(
    old_track: CandidateTrack,
    new_candidate: CandidateTrack,
):
    # Carry forward accumulated history
    old_track.decoded_terminal_id = new_candidate.decoded_terminal_id
    old_track.last_valid_sequence = new_candidate.last_valid_sequence
    old_track.valid_frame_count += new_candidate.valid_frame_count
    old_track.identity_state = VALID_TARGET
    old_track.identity_fail_streak = 0
    old_track.identity_matched = True
    old_track.identity_lock = True

    # Adopt new spatial state
    old_track.position_estimate = new_candidate.position_estimate
    old_track.velocity_estimate = new_candidate.velocity_estimate
    old_track.position_uncertainty = new_candidate.position_uncertainty

    # Transition back to active
    old_track.lifecycle_state = CandidateState.ACQUIRED

    # Retire the new candidate (it was only a probe)
    new_candidate.lifecycle_state = CandidateState.EXPIRED
```

---

## 9. Reacquisition Timeout → LOST

If no valid candidate satisfies the merge gate before `reacquisition_total_timeout_s`:

```python
old_track.lifecycle_state = CandidateState.LOST
```

After a further `expiry_timeout_s`, the track is retired:

```python
old_track.lifecycle_state = CandidateState.EXPIRED
```

Expired tracks are removed from the active candidate pool.

---

## 10. ReacquisitionEngine (`reacquisition.py`)

```python
class ReacquisitionEngine:
    def update(
        self,
        old_track: CandidateTrack,
        current_candidates: list[CandidateTrack],
        config: ReacquisitionConfig,
    ) -> ReacquisitionResult:

        predicted = old_track.predicted_position
        stage = self._get_current_stage(old_track)
        radius_px = deg_to_px(config.stage_radii_deg[stage])

        for candidate in current_candidates:
            if not candidate.identity_matched:
                continue
            if can_merge_reacquisition(old_track, candidate, config.spatial_gate_px):
                merge_reacquisition(old_track, candidate)
                return ReacquisitionResult(success=True, merged_candidate=candidate)

        if self._stage_timeout_exceeded(old_track, stage, config):
            if stage < len(config.stage_radii_deg) - 1:
                self._advance_stage(old_track)
            else:
                old_track.lifecycle_state = CandidateState.LOST
                return ReacquisitionResult(success=False, timed_out=True)

        self._command_search(old_track, stage, config)
        return ReacquisitionResult(success=False, searching=True)
```

---

## 11. Sequence Integrity During Reacquisition

A duplicate sequence (`seq=100` when old was `last_valid_sequence=100`) must NOT restore lock:

```
new_candidate.last_valid_sequence = 100
old_track.last_valid_sequence = 100

can_merge_reacquisition → False (step 5: not strictly greater)
```

Only a new, advancing sequence provides evidence that the target is genuinely still alive.
