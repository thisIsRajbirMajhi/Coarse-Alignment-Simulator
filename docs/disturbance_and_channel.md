# Disturbance and Channel

> **Scope**: Physical atmospheric channel model, disturbance effects, their impact on the received signal, and test-relevant scenarios.

---

## 1. Overview

The disturbance and channel layer models the physical effects of the atmosphere on the optical beam between the remote and local terminals. It is inserted between the RT optical transmitter and the camera sensor:

```
OpticsModel (RT output)
    │  clean optical intensity at aperture
    ▼
Disturbance / Channel Layer
    │  attenuated, scattered, wandered, scintillated signal
    ▼
Sensor / CameraFrame
```

The local terminal **never bypasses** the disturbance channel. All tests that exercise the receiver pipeline must use the real physical channel.

---

## 2. Disturbance Effects

### 2.1 Atmospheric Attenuation

Reduces the mean optical power received:

```
P_rx = P_tx × exp(-α × range_m)
```

Where `α` is the extinction coefficient (dB/km), computed from:
- Haze density (`environment/haze.py`)
- Rain rate (if modelled)
- Aerosol model

**Effect on receiver**:
- Reduced `peak_intensity` and `integrated_intensity` in `OpticalMeasurement`
- Lower SNR → harder synchronization
- Possible CRC failures on sufficiently attenuated signals

### 2.2 Scintillation

Random intensity fluctuations caused by refractive index variations in the turbulent atmosphere:

```
I_rx(t) = I_mean × exp(χ(t))
where χ(t) ~ Normal(0, σ_χ²)
```

Rytov variance:
```
σ_χ² = 1.23 C_n² k^(7/6) L^(11/6)
```

Where:
- `C_n²` — atmospheric structure constant (turbulence strength)
- `k = 2π/λ` — wave number
- `L` — propagation range

**Effect on receiver**:
- Temporal amplitude variation in `intensity_history`
- Increased difficulty for `OOKDemodulator` adaptive threshold
- Potential bit errors and CRC failures during deep fades

### 2.3 Beam Wander

Low-frequency displacement of the beam centroid due to large-scale turbulent eddies:

```
Δx(t) = ∫ random_walk(dt)   (band-limited, f < f_wander)
Δy(t) = ∫ random_walk(dt)
```

**Effect on receiver**:
- Centroid displacement in the camera image
- Association challenges (the blob moves)
- Tracking error during wander events
- Signal-level reduction if wander exceeds partial beam capture

### 2.4 Thermal / Background Noise

Photon shot noise, detector dark current, and read noise are modelled in the sensor (see `camera_and_sensor_system.md §3.2`). The disturbance layer adds:

- **Sky background radiance** — spatially varying, modelled by `environment/haze.py` and `environment/gradient.py`
- **Atmospheric emission** — small contribution at 1550 nm

### 2.5 Partial Obscuration

Transient objects (birds, clouds) can partially block the beam:

```
obscuration_fraction ∈ [0, 1]
I_rx_obscured = I_rx × (1 - obscuration_fraction)
```

Implemented as time-limited random events.

---

## 3. Channel Model Parameters

```python
@dataclass
class DisturbanceConfig:
    # Attenuation
    extinction_coeff_db_per_km: float = 0.5
    range_km: float = 1.0

    # Scintillation
    Cn2: float = 1e-14            # m^(-2/3), moderate turbulence
    wavelength_nm: float = 1550.0
    scintillation_enabled: bool = True
    scintillation_bandwidth_hz: float = 100.0   # temporal bandwidth

    # Wander
    wander_enabled: bool = True
    wander_rms_urad: float = 10.0
    wander_bandwidth_hz: float = 1.0

    # Background
    sky_background_ph_per_pixel_per_s: float = 1000.0

    # Obscuration
    obscuration_enabled: bool = False
    obscuration_mean_duration_s: float = 1.0
    obscuration_mean_interval_s: float = 60.0
    obscuration_max_fraction: float = 0.8
```

---

## 4. Effect on the Receiver Pipeline

| Disturbance | Impact on Stage |
|-------------|----------------|
| Attenuation | ↓ SNR → sync harder, bit errors → CRC failures |
| Scintillation | Temporal amplitude swings → adaptive threshold challenged |
| Wander | Centroid shift → association/tracking harder |
| Background | ↑ noise floor → ↓ SNR, ↑ false alarms |
| Deep fades | Signal disappears → DEGRADED → REACQUIRING |
| Temporary fade | Signal weakens → DEGRADED → recovery |
| Persistent fade | Continuous failures → REACQUIRING |

---

## 5. Disturbance Test Scenarios

These scenarios are required for the disturbance acceptance tests (see `tests_and_verification.md §4`):

### Scenario A: Steady Attenuation

```yaml
extinction_coeff_db_per_km: 2.0  # heavy haze
```

Expected:
- SNR reduced
- Synchronization requires more history
- Acquisition takes longer
- Identity eventually confirmed if SNR ≥ threshold

### Scenario B: Moderate Scintillation

```yaml
Cn2: 5e-14  # moderate turbulence
```

Expected:
- Temporal amplitude variation visible in `intensity_history`
- Occasional bit errors → CRC failures
- `identity_fail_streak` increases temporarily
- System enters DEGRADED, recovers on improved scintillation

### Scenario C: Strong Wander

```yaml
wander_rms_urad: 30.0
```

Expected:
- Centroid displacement visible
- Kalman filter tracks the displacement
- Association maintained
- Tracking error increases

### Scenario D: Deep Fade (Temporary)

```yaml
obscuration_enabled: true
obscuration_max_fraction: 0.95
obscuration_mean_duration_s: 3.0
```

Expected:
- Signal drops to near-zero during fade
- `missed_frame_count` increments
- DEGRADED state
- Recovery when fade ends
- Identity re-validated with new valid sequence

### Scenario E: Persistent Disturbance

```yaml
Cn2: 1e-12   # very strong turbulence
```

Expected:
- CRC failures accumulate
- DEGRADED
- REACQUIRING triggered
- If turbulence clears → TRACKING restored
- If turbulence persists → LOST

---

## 6. Integration with Scene Renderer

The disturbance model is applied by `FOVPipeline` when compositing the scene:

```python
rt_intensity = rt.current_intensity              # from OOK chip
attenuated = channel.apply_attenuation(rt_intensity)
scintillated = channel.apply_scintillation(attenuated, t)
wandered_position = channel.apply_wander(rt.angular_position, t)

scene.add_spot(
    position=wandered_position,
    intensity=scintillated,
    psf=camera.psf,
)
```

---

## 7. Channel Outputs Used by LT

The local terminal never reads channel outputs directly. It observes the final composited `CameraFrame`:

```
channel effects → scene rendering → sensor model → CameraFrame
                                                         ↑
                              LT only sees this ─────────┘
```

This is the core physical realism guarantee: the receiver must cope with whatever the atmosphere does to the signal, just as a real receiver must.
