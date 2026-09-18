# Configuration Reference

> **Scope**: Complete, precise reference for every configuration parameter in the system, with types, units, valid ranges, and defaults.

---

## Overview

All configuration is expressed as Python `@dataclass` objects. They can be:
- Constructed programmatically in Python.
- Loaded from a `dict` via `.from_dict()`.
- Serialised to a `dict` via `to_dict()` / `asdict()`.
- Loaded from YAML in headless mode.

All configs validate themselves on construction via `.validate()`.

---

## 1. `LocalTerminalConfig` (top-level)

Located in `local_terminal/config.py`.

```python
@dataclass
class LocalTerminalConfig:
    identity:      IdentityConfig
    state:         LocalStateConfig
    position:      PositionConfig
    camera:        LocalCameraConfig
    ptz:           PTZConfig
    display:       DisplayConfig
    angular_model: AngularModelConfig
    realism:       RealismConfig
    acquisition:   AcquisitionConfig
    detection:     DetectionConfig
    tracking:      TrackingConfig
    communication: LocalCommunicationConfig
    target_payload: TargetPayloadConfig
    vignetting:    float = 0.0
```

### Construction Example

```python
from local_terminal.config import LocalTerminalConfig, TargetPayloadConfig

config = LocalTerminalConfig()
config.target_payload = TargetPayloadConfig(
    expected_terminal_id="RT-001",
    expected_token="ALPHA-7",
    expected_wavelength_nm=1550.0,
    required_valid_frames=3,
)
config.validate()
```

---

## 2. `IdentityConfig`

```
Parameter           Type   Default                    Description
─────────────────── ────── ─────────────────────────  ─────────────────────────────────────────────────
id                  str    "LT-001"                   Local terminal identifier
name                str    "Local PTZ Camera 01"      Human-readable name
type                str    "LOCAL_OPTICAL_TERMINAL"   Terminal type label
platform_id         str    "PLATFORM-001"             Platform / host ID
```

---

## 3. `LocalCameraConfig`

Camera sensor and optics geometry.

```
Parameter            Type   Default    Valid Range         Unit    Description
──────────────────── ────── ─────────  ──────────────────  ──────  ─────────────────────────────────────
type                 str    "MONO-     —                   —       Sensor type label (MONOCHROME / COLOR)
                             CHROME"
sensor_type          str    "FOCAL_    —                   —       Array type label
                             PLANE_
                             ARRAY"
resolution_width     int    640        20 – 5000           px      Horizontal pixel count
resolution_height    int    480        20 – 5000           px      Vertical pixel count
fov_x                float  4.0        0.5 – 30.0          deg     Horizontal field of view
fov_y                float  3.0        0.5 – 30.0          deg     Vertical field of view
```

**Derived**:
```
pixel_scale_x = fov_x / resolution_width   [deg/px]
pixel_scale_y = fov_y / resolution_height  [deg/px]
```

---

## 4. `PTZConfig`

Pan-tilt actuator mechanics and limits.

```
Parameter           Type   Default    Valid Range          Unit     Description
─────────────────── ────── ─────────  ───────────────────  ───────  ──────────────────────────────────────────
pan_min             float  0.0        ≥0                   px       Left pan limit (0 = auto: FOV/2)
pan_max             float  0.0        ≥0                   px       Right pan limit (0 = auto: W - FOV/2)
home_pan            float  1000.0     0 – scene_width      px       Pan home position
pan_speed           float  8.0        1.0 – 60.0           deg/s    Pan slew rate
pan_resolution      float  0.10       0.001 – 10.0         px       Minimum pan step
tilt_min            float  0.0        ≥0                   px       Bottom tilt limit
tilt_max            float  0.0        ≥0                   px       Top tilt limit
home_tilt           float  1000.0     0 – scene_height     px       Tilt home position
tilt_speed          float  8.0        1.0 – 60.0           deg/s    Tilt slew rate
tilt_resolution     float  0.10       0.001 – 10.0         px       Minimum tilt step
resolution          float  0.10       0.001 – 10.0         px       Unified resolution (overrides pan/tilt)
latency             int    12         0 – 1000             ms       Actuator command-to-motion latency
update_rate         int    30         1 – 240              Hz       PTZ control loop update rate
control_mode        str    "AUTO"     AUTO/MANUAL/SEARCH/  —        PTZ control mode
                                      TRACKING
```

---

## 5. `RealismConfig`

Mechanical imperfection models.

```
Parameter           Type   Default    Valid Range    Unit      Description
─────────────────── ────── ─────────  ─────────────  ────────  ────────────────────────────────────
max_acceleration    float  20.0       0.1 – 500.0    deg/s²    PTZ maximum angular acceleration
backlash            float  0.25       0.0 – 10.0     px        Direction-reversal dead zone
encoder_sigma       float  0.040      0.0 – 2.0      px        Encoder position measurement noise (σ)
latency_jitter      float  1.2        0.0 – 100.0    ms        Random jitter added to actuator latency
```

---

## 6. `AcquisitionConfig`

Target search mode, scan pattern, and boundaries.

```
Parameter               Type   Default    Valid Range            Unit    Description
─────────────────────── ────── ─────────  ─────────────────────  ──────  ──────────────────────────────────────
mode                    str    "AUTO"     AUTO/MANUAL/SEARCH/    —       Acquisition mode
                                          AUTO_ACQUISITION/
                                          TARGET_POINTING
search_pattern          str    "RANDOM"   RANDOM/RASTER/SPIRAL   —       Scan pattern
                                          /SECTOR/GRID/CUSTOM/
                                          FIGURE_8
search_region_pan_min   float  -20.0      any                    deg     Left boundary of search region
search_region_pan_max   float   20.0      any                    deg     Right boundary
search_region_tilt_min  float  -10.0      any                    deg     Bottom boundary
search_region_tilt_max  float   10.0      any                    deg     Top boundary
search_speed            float   15.0      0.1 – 60.0             deg/s   PTZ scan speed during search
timeout                 float   30.0      1.0 – 300.0            s       Search timeout before restart
```

### Search Patterns Explained

| Pattern | Behaviour |
|---------|-----------|
| `RANDOM` | Random steps within the search region |
| `RASTER` | Left-to-right, top-to-bottom systematic sweep |
| `SPIRAL` | Expanding outward spiral from centre |
| `SECTOR` | Fan-shaped sector sweep |
| `GRID` | Grid of fixed dwell points |
| `FIGURE_8` | Figure-8 / lemniscate path |

---

## 7. `DetectionConfig`

Optical detection thresholds and code correlation.

```
Parameter                       Type   Default   Valid Range     Unit    Description
─────────────────────────────── ────── ────────  ──────────────  ──────  ────────────────────────────────────────────
wavelength                      float  1550.0    400 – 2000      nm      Expected beacon wavelength
bandwidth                       float  10.0      0.1 – 200       nm      Spectral filter bandwidth
intensity_threshold             float  0.0       ≥0              DN      Minimum detection intensity
minimum_snr                     float  8.0       0 – 100         dB      Minimum SNR to accept a detection
expected_spot_size              float  1.0       0.01 – 50       mrad    Expected beacon spot angular size
expected_spot_tolerance         float  1.5       0 – 20          mrad    Tolerance on spot size
modulation_type                 str    "AM"      AM/PM/OOK/PPM   —       Expected modulation type
modulation_frequency            float  10.0      0 – 1000        kHz     Expected modulation frequency
confidence_threshold            float  0.85      0 – 1           —       Minimum detection confidence
identification_code             str    ""        ≤32 chars       —       Legacy: OOK code (use TargetPayloadConfig)
identification_code_chip_rate_hz float  8.0      0.5 – 30        Hz      Legacy: chip rate for code correlation
code_correlation_threshold      float  0.75      0 – 1           —       Legacy: correlation match threshold
code_persistence                int    2         1 – 20          frames  Legacy: frames required for code match
```

---

## 8. `TargetPayloadConfig` ⭐

**The primary identity configuration for the digital beacon receiver.**

```
Parameter                       Type   Default    Valid Range     Description
─────────────────────────────── ────── ─────────  ─────────────   ──────────────────────────────────────────────────────────────
expected_terminal_id            str    "RT-001"   any string      Terminal ID that the decoded payload must contain
expected_token                  str    "ALPHA-7"  any string      Authentication token the payload must contain.
                                                                  Non-empty: empty decoded token → WRONG_TOKEN
expected_wavelength_nm          float  1550.0     400 – 2000 nm   Wavelength the payload must declare
wavelength_tolerance_nm         float  20.0       ≥ 0.1 nm        Acceptance window around expected wavelength
expected_protocol_version       int    1          ≥ 1             Protocol version byte the frame must contain
expected_message_type           int    1          ≥ 1             Message type byte the frame must contain
chip_rate_hz                    float  12.0       0.5 – 60.0 Hz   Expected OOK chip rate (for synchroniser seeding)
min_decode_confidence           float  0.40       0.0 – 1.0       Minimum fraction of CRC-passing frames in window
min_consecutive_valid           int    3          ≥ 1             Frames required before IDENTIFIED (alias: required_valid_frames)
required_valid_frames           int    3          ≥ 1             Same as above (canonical name)
require_sequence_advance        bool   True       True/False      Require sequence_number > last_valid_sequence
sequence_validation_enabled     bool   True       True/False      Whether to validate sequence advancement
wavelength_validation_enabled   bool   True       True/False      Whether to validate wavelength field
max_sequence_gap                int    0          ≥ 0             Max allowed jump in seq (0 = no limit)
identity_timeout_s              float  5.0        ≥ 0.1 s         Time before identity lock expires on no new frame
max_identity_fail_streak        int    10         ≥ 1             Consecutive identity failures before degradation
legacy_optical_identification   bool   False      False (only)    Enable optical-only identity (unsafe; default off)
_enabled
allow_wavelength_override       bool   False      True/False      Allow wavelength mismatch without rejection
```

> **Critical**: `legacy_optical_identification_enabled` must remain `False` in all production and simulation runs. Setting it to `True` bypasses the digital identity requirement.

---

## 9. `TrackingConfig`

Tracking loop control algorithm parameters.

```
Parameter               Type   Default     Valid Range      Unit    Description
─────────────────────── ────── ──────────  ───────────────  ──────  ───────────────────────────────────────
mode                    str    "AUTO"      OFF/TRACKING/AUTO —      Tracking mode
algorithm               str    "CENTROID"  CENTROID/PEAK/   —      Position measurement algorithm
                                           KALMAN
update_rate             int    30          1 – 240          Hz      Tracking loop rate
prediction              bool   True        True/False       —       Enable Kalman position prediction
prediction_horizon      float  0.15        0 – 5.0          s       How far ahead to predict position
smoothing               float  0.2         0 – 1.0          —       Centroid smoothing coefficient (0=none)
lost_target_behavior    str    "RESUME_    see values       —       What PTZ does on target loss
                               SEARCH"
kp                      float  0.25        0 – 10.0         —       PID proportional gain
ki                      float  0.05        0 – 10.0         —       PID integral gain
kd                      float  0.02        0 – 10.0         —       PID derivative gain
dead_zone               float  0.5         0 – 50.0         px      Deadband — corrections below this ignored
output_clamp            float  500.0       1.0 – 5000.0     px      Maximum PTZ correction per frame
```

**Lost target behaviours:**
- `RESUME_SEARCH` — return to scanning (default)
- `HOLD_POSITION` — PTZ freezes at last position
- `RETURN_HOME` — PTZ returns to home_pan / home_tilt

---

## 10. `LocalStateConfig`

Runtime operational state values (not user-configurable; derived at runtime):

```
Field                   Values
─────────────────────── ─────────────────────────────────────────────────────
operational_state       OFF | INITIALIZING | STANDBY | ACTIVE | FAULT
power_state             OFF | ON
ptz_state               IDLE | MOVING | AT_POSITION | LIMIT_REACHED | FAULT
acquisition_state       IDLE | SEARCHING | ACQUIRING | ACQUIRED
detection_state         NO_TARGET | DETECTING | DISCRIMINATING | TARGET_CONFIRMED
tracking_state          OFF | TRACKING | LOST | REACQUIRING
link_state              NO_LINK | OPTICAL_LOCK | HANDSHAKE | CONNECTED
```

---

## 11. `PositionConfig`

Platform physical position (distinct from PTZ pan/tilt angle).

```
Parameter        Type   Default   Unit   Description
──────────────── ────── ───────── ────── ──────────────────────────────────
x                float  0.0       m      Platform X position in reference frame
y                float  0.0       m      Platform Y position
z                float  0.0       m      Platform Z (altitude)
reference_frame  str    "WORLD"   —      Reference frame label
```

---

## 12. `AngularModelConfig`

Derived pixel-to-angle conversion. **Do not set manually** — always call `recalculate()`.

```
Parameter          Type   Unit          Description
────────────────── ────── ───────────── ──────────────────────────────────────
pixel_to_angle_x   float  μrad/px       Horizontal angular scale
pixel_to_angle_y   float  μrad/px       Vertical angular scale
angle_to_pixel_x   float  px/μrad       Inverse (horizontal)
angle_to_pixel_y   float  px/μrad       Inverse (vertical)
unit               str    "urad_per_px" Always this value
```

**Formula**:
```
pixel_to_angle_x = (fov_x_deg × 1e6 × π/180) / resolution_width
```

For `fov_x=4.0°`, `width=640px`: `pixel_to_angle_x = 109.08 μrad/px`.

---

## 13. Configuration Validation Rules

The following invariants are enforced by `.validate()`:

| Rule | Error |
|------|-------|
| `pan_min < pan_max` | Swapped automatically |
| `tilt_min < tilt_max` | Swapped automatically |
| `search_region_pan_min < pan_max` | Swapped automatically |
| `chip_rate_hz ∈ [0.5, 60.0]` | Clamped |
| `required_valid_frames ≥ 1` | Clamped |
| `identity_timeout_s ≥ 0.1` | Clamped |
| `wavelength ∈ [400, 2000] nm` | Clamped |
| `fov_x, fov_y ∈ [0.5°, 30°]` | Clamped |
| `resolution_width ∈ [20, 5000]` | Clamped |

---

## 14. YAML Configuration File Format

For headless mode, the configuration can be specified as YAML:

```yaml
local_terminal:
  camera:
    resolution_width: 640
    resolution_height: 480
    fov_x: 4.0
    fov_y: 3.0

  ptz:
    pan_speed: 8.0
    tilt_speed: 8.0
    latency: 12
    update_rate: 30

  acquisition:
    search_pattern: SPIRAL
    search_speed: 15.0
    timeout: 60.0

  tracking:
    algorithm: KALMAN
    kp: 0.25
    ki: 0.05
    kd: 0.02
    prediction: true
    prediction_horizon: 0.15

  target_payload:
    expected_terminal_id: "RT-001"
    expected_token: "ALPHA-7"
    expected_wavelength_nm: 1550.0
    required_valid_frames: 3
    sequence_validation_enabled: true
    wavelength_validation_enabled: true
    chip_rate_hz: 12.0
    identity_timeout_s: 5.0
    max_identity_fail_streak: 10

remote_terminal:
  beacon:
    tid: "RT-001"
    token: "ALPHA-7"
    wavelength_nm: 1550.0
    chip_rate_hz: 12.0
    payload_codec: "compact"
    enabled: true

scenario:
  terminals:
    - id: RT-001
      enable_at_s: 0.0
    - id: RT-999
      enable_at_s: 65.0
      disable_at_s: 88.0
```

---

## 15. camelCase Support

All `from_dict()` methods accept both `snake_case` and `camelCase` keys. For example:

```json
{
  "targetPayload": {
    "expectedTerminalId": "RT-001",
    "expectedToken": "ALPHA-7",
    "requiredValidFrames": 3
  }
}
```

is equivalent to:

```json
{
  "target_payload": {
    "expected_terminal_id": "RT-001",
    "expected_token": "ALPHA-7",
    "required_valid_frames": 3
  }
}
```
