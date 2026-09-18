# Tracking

> **Scope**: Image-based closed-loop tracking, PTZ control, continuous identity monitoring, identity swap detection, and degradation handling.

---

## 1. Overview

Once a candidate reaches `ACQUIRED`, the tracking system takes over. Tracking is **purely image-based** — the PTZ is commanded from the measured camera centroid and its Kalman-filtered derivatives. The digital beacon path runs in parallel and only validates identity and liveness.

```
CameraFrame (each tick)
    │
    ▼
CandidateDetector → association → track.update_optical_measurement()
    │
    ▼
StateEstimator (Kalman)
    │
    ├── position_estimate (filtered centroid)
    ├── velocity_estimate
    └── predicted_position (next frame)
    │
    ▼
TrackingEngine → tracking_error → PTZActuator
    │
    ├── centroid_error_x
    ├── centroid_error_y
    └── (NOT: sequence number, payload, remote position)
    │
    ▼
IdentityMonitor (parallel, every new decode result)
    │
    ├── VALID_TARGET + new sequence → identity_ok, reset fail streak
    ├── temporary no-data gap → allow grace period
    ├── wrong terminal decoded → immediate identity break
    └── persistent failures → trigger DEGRADED / REACQUIRING
```

---

## 2. TrackingEngine (`tracking.py`)

### 2.1 Tracking Error

The tracking error is the pixel displacement of the candidate centroid from the frame centre:

```python
target_cx = frame_width_px / 2.0
target_cy = frame_height_px / 2.0

error_x = track.position_estimate[0] - target_cx
error_y = track.position_estimate[1] - target_cy
```

### 2.2 PID Controller

```python
# Per-axis PID
u_x = Kp × error_x + Ki × integral_x + Kd × derivative_x
u_y = Kp × error_y + Ki × integral_y + Kd × derivative_y

# Convert pixel error to angular command
delta_az_rad = u_x × pixel_scale_rad_per_px
delta_el_rad = u_y × pixel_scale_rad_per_px
```

Anti-windup is applied to the integrator:
```python
integral_x = clip(integral_x, -anti_windup_limit, anti_windup_limit)
```

### 2.3 Predictive Tracking

During missed frames, the Kalman filter predicts the next centroid position:

```python
track.predicted_position = (
    track.position_estimate
    + track.velocity_estimate × dt
    + 0.5 × track.acceleration_estimate × dt²
)
```

The PTZ is commanded to the **predicted** position during temporary dropouts.

### 2.4 What Tracking Uses / Does NOT Use

| Used for PTZ control | NEVER used for PTZ control |
|---------------------|---------------------------|
| `track.position_estimate` (Kalman centroid) | `decoded_terminal_id` |
| `track.velocity_estimate` | `decoded_sequence_number` |
| `track.acceleration_estimate` | `payload_contents` |
| `track.predicted_position` | Remote world position |
| `track.latest_measurement.centroid_x/y` | RT pose from scenario |

---

## 3. StateEstimator (`estimator.py`)

A constant-acceleration Kalman filter maintains the track state:

### State Vector

```
x = [cx, cy, vx, vy, ax, ay]
    [centroid_x, centroid_y, velocity_x, velocity_y, acceleration_x, acceleration_y]
```

### Process Model (F matrix)

```
cx(t+1) = cx + vx·dt + 0.5·ax·dt²
cy(t+1) = cy + vy·dt + 0.5·ay·dt²
vx(t+1) = vx + ax·dt
vy(t+1) = vy + ay·dt
ax(t+1) = ax
ay(t+1) = ay
```

### Measurement Model (H matrix)

Centroid observation: `z = [cx, cy]`

### Update Equation

Standard Kalman:
```python
K = P H^T (H P H^T + R)^{-1}          # Kalman gain
x = x + K (z - H x)                   # state update
P = (I - K H) P                        # covariance update
```

### Configuration

```python
@dataclass
class EstimatorConfig:
    process_noise_px: float = 0.5       # per-axis per-frame
    measurement_noise_px: float = 0.3   # centroid measurement noise
    initial_position_variance: float = 10.0
    initial_velocity_variance: float = 2.0
    initial_acceleration_variance: float = 0.5
```

---

## 4. PTZActuator (`ptz_actuator.py`)

### 4.1 Rate Limiting

Physical PTZ mechanics impose a maximum slew rate:

```python
commanded_rate = delta_angle / dt
actual_rate = clip(commanded_rate, -max_rate, max_rate)
actual_delta = actual_rate * dt
```

### 4.2 Backlash Model

A dead-band zone around direction reversals:

```python
if sign(current_command) != sign(last_command):
    effective_delta = max(0, abs(delta) - backlash_deg) * sign(delta)
```

### 4.3 Position Limits

```python
new_az = clip(current_az + delta_az, az_min, az_max)
new_el = clip(current_el + delta_el, el_min, el_max)
```

### 4.4 Configuration

```python
@dataclass
class PTZConfig:
    max_rate_deg_s: float = 10.0
    backlash_deg: float = 0.05
    az_range_deg: tuple = (-180, 180)
    el_range_deg: tuple = (-30, 90)
    pixel_scale_rad_per_px: float = ...  # derived from focal length / pixel pitch
```

---

## 5. Continuous Identity Monitoring

During tracking, every newly decoded frame is validated:

```python
def monitor_identity(track: CandidateTrack, result: BeaconDecodeResult):
    decision = identity_validator.validate(result, payload, track, config)

    if decision.identity_state == VALID_TARGET and decision.is_new_liveness:
        track.last_valid_sequence = decision.decoded_sequence
        track.last_valid_frame_time = now()
        track.identity_fail_streak = 0
        track.identity_confidence = min(1.0, track.identity_confidence + 0.1)

    elif decision.identity_state == WRONG_TERMINAL:
        # Identity swap — immediate action
        _handle_identity_swap(track)

    elif decision.identity_state in (INVALID_SEQUENCE, UNKNOWN, ...):
        # Temporary miss
        track.identity_fail_streak += 1
        track.identity_confidence = max(0.0, track.identity_confidence - 0.05)
        _check_degradation(track)
```

### Distinction between failure types

| Condition | Action |
|-----------|--------|
| No new frame (signal gap) | Grace period; increment fail streak mildly |
| Bad frame (CRC fail) | Increment fail streak |
| Wrong terminal decoded | Immediate identity break → REJECTED or REACQUIRING |

---

## 6. Identity Swap Detection

If the decoded `terminal_id` changes while tracking:

```python
if (track.decoded_terminal_id is not None
        and decision.decoded_terminal_id != track.decoded_terminal_id):
    _handle_identity_swap(track)
```

```python
def _handle_identity_swap(track: CandidateTrack):
    track.identity_state = WRONG_TERMINAL
    track.identity_matched = False
    track.identity_lock = False
    track.lifecycle_state = CandidateState.REACQUIRING
    # Spatial tracking may continue briefly for prediction
    # but acquisition lock is immediately revoked
```

The received identity is authoritative. A position match does not override an identity mismatch.

---

## 7. Tracking Quality Metrics (`metrics.py`)

```python
@dataclass
class TrackingMetrics:
    rms_error_px: float          # RMS centroid error from target
    rms_velocity_px_s: float     # RMS centroid velocity
    valid_frame_fraction: float  # fraction of frames with valid optical blob
    identity_confidence: float   # current identity confidence
    snr: float                   # current SNR
    valid_decode_fraction: float # fraction of frames with valid decode
    link_quality: float          # composite 0–1 score
```

---

## 8. Degradation

### Entry Conditions

The track enters `DEGRADED` if any of the following is true:

```python
degraded = (
    track.signal_quality < config.degradation_signal_threshold
    OR track.latest_measurement.snr < config.degradation_snr_threshold
    OR track.identity_fail_streak > config.degradation_fail_streak
    OR track.missed_frame_count > config.degradation_missed_frames
)
```

### Behaviour During DEGRADED

- PTZ continues to track on Kalman prediction.
- Identity monitoring continues.
- If a new valid frame restores quality → back to `TRACKING`.
- If degradation persists → transitions to `REACQUIRING`.

### Recovery Conditions

```python
recovered = (
    track.identity_state == VALID_TARGET
    AND track.signal_quality >= config.tracking_signal_threshold
    AND track.latest_measurement.snr >= config.tracking_snr_threshold
    AND track.identity_fail_streak == 0
)
```

### Configuration

```python
@dataclass
class TrackingConfig:
    # PID
    Kp: float = 0.5
    Ki: float = 0.05
    Kd: float = 0.1
    anti_windup_limit: float = 50.0

    # Degradation thresholds
    degradation_signal_threshold: float = 0.3
    degradation_snr_threshold: float = 3.0
    degradation_fail_streak: int = 3
    degradation_missed_frames: int = 5

    # Recovery thresholds (higher hysteresis)
    tracking_signal_threshold: float = 0.5
    tracking_snr_threshold: float = 5.0

    # Persistence
    identity_timeout_s: float = 10.0
    max_missed_frames_before_reacquire: int = 30
```

---

## 9. TrackingController (`tracking_controller.py`)

The `TrackingController` is a thin wrapper that selects the active tracking mode based on lifecycle state:

```python
class TrackingController:
    def update(self, track: CandidateTrack, frame: CameraFrame):
        if track.lifecycle_state == CandidateState.TRACKING:
            self.tracking_engine.update(track, frame)
        elif track.lifecycle_state == CandidateState.DEGRADED:
            self.tracking_engine.update_degraded(track, frame)
        elif track.lifecycle_state == CandidateState.REACQUIRING:
            self.reacquisition_engine.update(track, frame)
```
