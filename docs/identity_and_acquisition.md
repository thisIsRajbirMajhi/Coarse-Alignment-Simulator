# Identity and Acquisition

> **Scope**: Frame parsing, payload decoding, identity validation, dual-lock acquisition, and the identity validator decision rules.

---

## 1. Overview

Identity and acquisition are the critical junction between the digital beacon path and the spatial tracking path. A candidate can only become the active tracking target after both:

1. **Identity lock** — digital identity proven by decoded beacon payload.
2. **Spatial lock** — candidate is visible, stable, and centred within the acquisition window.

```
BeaconDecodeResult
    │
    ▼
PayloadDecoder              → DecodedPayload
    │
    ▼
IdentityValidator           → IdentityDecision
    │
    ├── VALID_TARGET ────────────────────────┐
    │                                        ▼
    │                               Persistence counter increments
    │                               (valid_frame_count++)
    │
    ├── WRONG_TERMINAL → candidate REJECTED (immediate)
    ├── WRONG_TOKEN    → candidate REJECTED
    ├── WRONG_PROTOCOL → candidate REJECTED
    ├── WAVELENGTH_MISMATCH → not IDENTIFIED
    └── INVALID_SEQUENCE → not counted as new liveness
                                             │
                                    valid_frame_count ≥ required_valid_frames
                                             │
                                             ▼
                                    identity_lock = True
                                             │
                              spatial_lock = True (simultaneously)
                                             │
                                             ▼
                                        ACQUIRED
```

---

## 2. PayloadDecoder

`PayloadDecoder` centralises all payload-format knowledge. No payload parsing occurs anywhere else.

```python
class PayloadDecoder:
    def decode(self, payload_bytes: bytes) -> DecodedPayload:
        """
        Raises PayloadDecodeError on any parse failure.
        """
        tid_len = payload_bytes[0]
        tid = payload_bytes[1 : 1 + tid_len].decode("utf-8")
        token_len = payload_bytes[1 + tid_len]
        token = payload_bytes[2 + tid_len : 2 + tid_len + token_len].decode("utf-8")
        offset = 2 + tid_len + token_len
        wl = struct.unpack_from(">H", payload_bytes, offset)[0]
        seq = struct.unpack_from(">I", payload_bytes, offset + 2)[0]
        return DecodedPayload(
            terminal_id=tid,
            token=token,
            wavelength_nm=float(wl),
            sequence_number=seq,
        )
```

### Error Handling

`PayloadDecodeError` is raised for:
- Buffer too short
- Invalid UTF-8 in tid or token
- Inconsistent length fields

A `PayloadDecodeError` results in `BeaconDecodeResult.reason = "MALFORMED_PAYLOAD"` and is treated as an identity failure.

---

## 3. IdentityValidator (`identity_matcher.py`)

### 3.1 Input / Output

```python
class IdentityValidator:
    def validate(
        self,
        decode_result: BeaconDecodeResult,
        payload: DecodedPayload | None,
        track: CandidateTrack,
        config: TargetPayloadConfig,
    ) -> IdentityDecision: ...

@dataclass
class IdentityDecision:
    identity_state: IdentityState
    reason_code: IdentityReasonCode
    confidence: float
    is_new_liveness: bool        # True only if new valid unique sequence
    decoded_terminal_id: str | None
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    decoded_sequence: int | None
```

### 3.2 Validation Logic (in order)

```
Step 1: Frame detected?
    No  → UNKNOWN (NO_DATA)

Step 2: Synchronised?
    No  → UNKNOWN (CRC_FAILURE or similar)

Step 3: CRC valid?
    No  → UNKNOWN (CRC_FAILURE)

Step 4: Protocol version accepted?
    No  → WRONG_PROTOCOL (PROTOCOL_MISMATCH)

Step 5: Message type accepted?
    No  → WRONG_PROTOCOL (PROTOCOL_MISMATCH)

Step 6: Payload decoded?
    No  → UNKNOWN (MALFORMED_PAYLOAD)

Step 7: terminal_id matches expected?
    No  → WRONG_TERMINAL (TID_MISMATCH)

Step 8: token matches expected?
    (only if expected_token is non-empty)
    No  → WRONG_TOKEN (TOKEN_MISMATCH)

Step 9: wavelength_validation_enabled?
    Yes → decoded_wl within tolerance of expected_wl?
        No → WAVELENGTH_MISMATCH

Step 10: sequence_validation_enabled?
    Yes → is sequence new (> last_valid_sequence)?
        No (duplicate) → INVALID_SEQUENCE (DUPLICATE_SEQUENCE)
        No (old)       → INVALID_SEQUENCE (OLD_SEQUENCE)
        Jump too large → INVALID_SEQUENCE (SEQUENCE_DISCONTINUITY)

Step 11: decode_confidence ≥ min_confidence?
    No  → UNKNOWN (LOW_CONFIDENCE)

Step 12: All checks passed → VALID_TARGET (OK)
         is_new_liveness = True
         valid_frame_count++
```

### 3.3 Token Strictness

```
If config.expected_token != "":
    decoded_token == ""  →  WRONG_TOKEN   ← empty token ≠ "no requirement"
    decoded_token != expected_token → WRONG_TOKEN
```

An empty decoded token is never equivalent to "no token requirement" if the receiver is configured to expect one.

### 3.4 Wavelength Validation

Three values are compared:

```python
expected_wl   = config.expected_wavelength_nm     # configured expectation
decoded_wl    = payload.wavelength_nm              # from beacon payload
measured_wl   = track.measured_wavelength_nm       # from spectral estimate

# Primary check:
wl_ok = abs(decoded_wl - expected_wl) <= wl_tolerance_nm

# Optional consistency check (advisory):
wl_consistent = (measured_wl is not None and
                 abs(measured_wl - decoded_wl) <= wl_consistency_tolerance_nm)
```

The `measured_wavelength_nm` comes from the `OpticalMeasurement.spectral_estimate`. It is not fabricated from payload data.

### 3.5 Sequence Validation

```python
seq = payload.sequence_number
last = track.last_valid_sequence

if last is None:
    is_new = True   # first ever valid frame

elif seq == last:
    reason = DUPLICATE_SEQUENCE
    is_new = False

elif seq < last:
    reason = OLD_SEQUENCE
    is_new = False

elif seq - last > config.max_sequence_gap and config.max_sequence_gap > 0:
    reason = SEQUENCE_DISCONTINUITY
    is_new = False

else:
    is_new = True
```

**Duplicate or old sequences are never counted as new liveness.**

---

## 4. Identity Persistence

`valid_frame_count` only increments when `is_new_liveness == True`. This prevents repeated detections of the same sequence from artificially inflating the count.

```python
if decision.identity_state == VALID_TARGET and decision.is_new_liveness:
    track.valid_frame_count += 1
    track.last_valid_sequence = decoded_sequence
    track.identity_fail_streak = 0
else:
    track.invalid_frame_count += 1
    track.identity_fail_streak += 1
```

**IDENTIFIED** is reached when:

```python
identity_lock = (
    track.identity_state == VALID_TARGET
    and track.valid_frame_count >= config.required_valid_frames
)
```

---

## 5. Dual-Lock Acquisition (`acquisition.py`, `acquisition_mgr.py`)

### 5.1 Identity Lock

```python
identity_lock = bool(track.identity_matched)
# where identity_matched = (identity_state == VALID_TARGET
#                           and valid_frame_count >= required_valid_frames)
```

### 5.2 Spatial Lock

```python
spatial_lock = (
    track.latest_measurement is not None
    and track.latest_measurement.snr >= config.min_acquisition_snr
    and track.latest_measurement.optical_quality >= config.min_acquisition_quality
    and centroid_within_window(track, config.acquisition_window_px)
    and motion_plausible(track, config.max_centroid_velocity_px_s)
    and track.missed_frame_count == 0
)
```

### 5.3 Acquisition Decision

```python
acquired = identity_lock and spatial_lock
# Both locks required — no bypass in normal mode
```

> **Never implemented as:**
> ```python
> if require_identity_lock and require_identity_match:
>     id_locked = track.identity_matched
> else:
>     id_locked = True  # ← FORBIDDEN
> ```

### 5.4 Legacy Mode (explicit opt-in only)

```python
if config.legacy_optical_identification_enabled:
    # Legacy path: spatial lock alone may suffice
    acquired = spatial_lock
else:
    # Normal path (default)
    acquired = identity_lock and spatial_lock
```

`legacy_optical_identification_enabled` defaults to `False` and must be explicitly set in configuration.

---

## 6. AcquisitionManager (`acquisition_mgr.py`)

The `AcquisitionManager` orchestrates the SELECTED → ACQUIRING → ACQUIRED transitions for the chosen candidate.

### State

```python
class AcquisitionState(Enum):
    IDLE        = "IDLE"
    CENTERING   = "CENTERING"    # PTZ moving to centre candidate
    VERIFYING   = "VERIFYING"    # checking spatial and identity locks
    ACQUIRED    = "ACQUIRED"
    FAILED      = "FAILED"
```

### Centering Manoeuvre

```python
error_az = candidate.centroid_x - frame_centre_x
error_el = candidate.centroid_y - frame_centre_y

# Convert pixel error to angular error
error_az_rad = error_az * pixel_scale_rad_per_px
error_el_rad = error_el * pixel_scale_rad_per_px

# Command PTZ slew
ptz_command = PTZCommand(
    delta_az_rad = error_az_rad,
    delta_el_rad = error_el_rad,
    rate_limit   = acquisition_slew_rate,
)
```

### Acquisition Timeout

If the candidate is lost (blob disappears) or identity lock is broken during centering:

```python
if elapsed > config.acquisition_timeout_s:
    acquisition_state = FAILED
    candidate.lifecycle_state = DEGRADED  # or REACQUIRING
```

---

## 7. Selection Engine (`system.py`)

### Priority Scoring

```python
score = (
    w_identity × float(candidate.identity_state == VALID_TARGET)
    + w_signal  × candidate.signal_quality
    + w_optical × candidate.optical_quality
    + w_track   × candidate.tracking_quality
)
```

### Hard Exclusions

Candidates with any of the following are **never** eligible for selection:

```python
WRONG_TERMINAL
WRONG_TOKEN
WRONG_PROTOCOL
lifecycle_state in (REJECTED, LOST, EXPIRED)
identity_lock == False  # in normal mode
```

### Multi-candidate Scenario

```
Candidate A (BEACON-001): identity_state=VALID_TARGET,  snr=12 dB
Candidate B (BEACON-002): identity_state=WRONG_TERMINAL, snr=20 dB

→ Candidate A is selected (B is hard-excluded)
```

A bright wrong-identity terminal never outranks a weaker correct one.

---

## 8. Configuration (`local_terminal/config.py`)

```python
@dataclass
class TargetPayloadConfig:
    expected_terminal_id: str = "RT-001"
    expected_token: str = "ALPHA-7"
    expected_wavelength_nm: float = 1550.0
    expected_protocol_version: int = 1
    expected_message_type: int = 1

    required_valid_frames: int = 3
    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = True
    max_sequence_gap: int = 0        # 0 = any increase accepted
    identity_timeout_s: float = 30.0
    max_identity_fail_streak: int = 5

    wavelength_tolerance_nm: float = 50.0
    wavelength_consistency_tolerance_nm: float = 100.0
    min_decode_confidence: float = 0.5

@dataclass
class AcquisitionConfig:
    acquisition_window_px: float = 20.0
    min_acquisition_snr: float = 5.0
    min_acquisition_quality: float = 0.4
    max_centroid_velocity_px_s: float = 10.0
    acquisition_timeout_s: float = 10.0
    acquisition_slew_rate_deg_s: float = 5.0
    legacy_optical_identification_enabled: bool = False
```
