# Remote Terminal

> **Scope**: Remote terminal architecture — beacon generation, OOK optical transmission, motion, and scenario management.

---

## 1. Responsibility

The **Remote Terminal (RT)** is the transmitter side of the FSO link. Its sole job is to:

1. Generate a deterministic binary-framed beacon signal.
2. Encode it as an OOK (On-Off Keying) intensity modulation.
3. Apply that modulation to an optical beam pointed at the local terminal.
4. Simulate platform motion and beam geometry.

The RT **never** directly communicates with the LT except through photons.

---

## 2. Module Overview

```
remote_terminal/
├── config.py           # RemoteTerminalConfig, BeaconConfig
├── terminal.py         # RemoteTerminal — top-level class
├── beacon_encoder.py   # BeaconEncoder — runtime beacon pipeline
├── optics.py           # OpticsModel — beam geometry, divergence, intensity
├── motion.py           # MotionModel — platform kinematics, angular velocity
└── scenario.py         # Scenario — multi-RT management, environment coupling
```

---

## 3. Configuration (`config.py`)

### `BeaconConfig`

All beacon protocol parameters live here as first-class fields:

```python
@dataclass
class BeaconConfig:
    enabled: bool = True

    # Identity
    tid: str = "RT-001"          # terminal ID embedded in payload
    token: str = "ALPHA-7"       # authentication token

    # Protocol
    wavelength_nm: float = 1550.0
    protocol_version: int = 1
    message_type: int = 1        # BEACON = 1

    # Codec
    payload_codec: str = "compact"   # "compact" | "json_debug"

    # Timing
    chip_rate_hz: float = 12.0
```

> **No JSON payload in production mode.** `payload_codec = "compact"` selects the deterministic compact binary codec.

### `RemoteTerminalConfig`

```python
@dataclass
class RemoteTerminalConfig:
    terminal_id: str
    beacon: BeaconConfig
    optics: OpticsConfig
    motion: MotionConfig
    # ...
```

---

## 4. Beacon Encoder (`beacon_encoder.py`)

The `BeaconEncoder` converts a logical beacon payload into an optical intensity stream:

```
BeaconPayload
    │
    ▼  PayloadCodec.encode()  →  bytes
    │
    ▼  BeaconFrameEncoder.encode()
    │      PREAMBLE + SYNC + version + msg_type + len + payload + CRC-8
    │
    ▼  OOKEncoder.encode()
    │      bits → chips (Manchester / NRZ / etc.)
    │
    ▼  intensity_modulation[]   →   fed to OpticsModel
```

**Key invariant**: The receiver **never** has access to `intensity_modulation[]` directly. It can only observe what the camera sees after propagation, disturbance, and sensor rendering.

### Sequence Counter

Each call to `BeaconEncoder.next_frame()`:
- Increments `sequence_number` by 1.
- Re-serializes payload, re-encodes frame, re-encodes OOK chips.
- The chip sequence advances monotonically with simulation time.

### Timing Coherence

The beacon encoder enforces:

```
required_history_duration > 2 × frame_duration

where:
  frame_duration = n_bits_per_frame / chip_rate_hz
```

At initialisation the config is validated:

```python
frame_bits = (preamble_bits + sync_bits + header_bits
              + payload_bits + crc_bits)
frame_duration_s = frame_bits / chip_rate_hz
required_history_s = 2 * frame_duration_s * safety_factor
required_camera_samples = ceil(required_history_s * camera_fps)
```

An `InvalidTimingError` is raised if the camera history budget is insufficient.

---

## 5. Optics Model (`optics.py`)

### Beam Parameters

| Parameter | Description |
|-----------|-------------|
| `wavelength_nm` | Carrier wavelength (e.g. 1550 nm) |
| `divergence_rad` | Full-angle beam divergence |
| `peak_intensity` | On-axis intensity at unit range |
| `pointing_offset_rad` | Static boresight offset |
| `aperture_m` | Transmit aperture diameter |

### Intensity at Receiver

```
I_rx = I_tx × G_tx × G_rx × L_path × L_atm
```

- `G_tx`, `G_rx` — transmit/receive antenna gains
- `L_path` — free-space path loss (Friis)
- `L_atm` — atmospheric attenuation from disturbance model

### OOK Modulation

The optics model multiplies baseline intensity by the chip value:

```python
pixel_intensity = base_intensity * (chip == 1) + dark_current * (chip == 0)
```

This intensity is then rendered by the scene compositor.

---

## 6. Motion Model (`motion.py`)

### Platform State

```python
@dataclass
class PlatformState:
    position_ecef: np.ndarray    # [x, y, z] in metres
    velocity_mps: np.ndarray     # [vx, vy, vz]
    attitude_quat: np.ndarray    # quaternion [w, x, y, z]
    angular_rate_rps: np.ndarray # body-frame angular rates
```

### Kinematics

The motion model integrates:

```
position(t+dt) = position(t) + velocity(t) × dt
attitude(t+dt) = attitude(t) ⊗ exp(ω × dt / 2)
```

Perturbations include:
- Vibration spectra (platform jitter)
- Wind-induced pointing wander
- Slewing rates from commanded manoeuvres

### Angular Position in LT FOV

The RT computes its angular position as seen from the LT using line-of-sight geometry:

```
az, el = los_to_azel(RT.position_ecef, LT.position_ecef, LT.attitude)
```

This value is used **only** by the scene renderer to place the RT spot on the camera image. The LT never reads this.

---

## 7. Scenario Management (`scenario.py`)

### Purpose

`Scenario` manages:
- Multiple simultaneous remote terminals (e.g. RT-001, RT-999 for decoy scenarios).
- Environmental coupling (time of day, weather changes).
- RT enable/disable events (simulating target disappearance).

### Multi-RT Decoy Test

```
t=0:      RT-001 visible, transmitting beacon
t=T_dis:  RT-001 disappears
t=T_dec:  RT-999 appears near predicted position
t=T_reap: RT-001 reappears with seq > last_seen_seq
```

This scenario is the canonical test for identity-gated reacquisition.

### Scenario File Format

```yaml
terminals:
  - id: RT-001
    beacon:
      tid: RT-001
      token: ALPHA-7
      chip_rate_hz: 12.0
    motion:
      trajectory: linear
      speed_mps: 0.5
    events:
      - at_s: 60.0
        action: disable
      - at_s: 90.0
        action: enable

  - id: RT-999
    beacon:
      tid: RT-999
      token: BRAVO-3
    events:
      - at_s: 62.0
        action: enable
      - at_s: 88.0
        action: disable
```

---

## 8. Data Flow Summary

```
Scenario.tick(dt)
    └─ for each RemoteTerminal:
           MotionModel.update(dt)           → PlatformState
           BeaconEncoder.get_chip(t)        → chip ∈ {0, 1}
           OpticsModel.compute_intensity()  → pixel_intensity
           SceneRenderer.place_spot(az, el, intensity)
```

The `SceneRenderer` output is a `CameraFrame` — the only data the local terminal receives.

---

## 9. Invariants

| Invariant | Enforcement |
|-----------|-------------|
| RT ID never leaks to LT | `terminal.py` never passes `self.terminal_id` to LT |
| Sequence is monotonically increasing | `BeaconEncoder` maintains atomic counter |
| Beacon timing is physically coherent | Validated at config load |
| OOK chip state is deterministic | Reproducible from seed and time |
