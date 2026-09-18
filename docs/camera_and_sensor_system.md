# Camera and Sensor System

> **Scope**: Camera model, sensor physics, frame rendering pipeline, and the `OpticalMeasurement` produced for each candidate.

---

## 1. Overview

The camera and sensor system is the **sole data source** for the local terminal. It converts physical photon arrival into a discrete pixel array (`CameraFrame`) that the receiver processes.

```
Photons from RT beam
      │
      ▼
  Scene Compositor (SceneRenderer / FOVPipeline)
      │  stars + haze + gradient + vignetting + spots
      ▼
  Disturbance Layer
      │  scintillation, wander, attenuation noise
      ▼
  Sensor Model
      │  photon → electron conversion, dark current, read noise, ADC
      ▼
  CameraFrame  (H × W uint16 or float32 array + timestamp)
      │
      ▼
  FrameProcessor (local terminal)
```

---

## 2. Scene Rendering Pipeline (`simulation/fov_pipeline.py`, `environment/scene.py`)

### FOVPipeline

The `FOVPipeline` computes, for each simulation tick, a composite image of everything visible within the local terminal's field of view.

```python
class FOVPipeline:
    def render(self, ptz_pose: PTZPose, scenario: Scenario) -> np.ndarray:
        frame = np.zeros((height, width), dtype=np.float32)
        frame += self.star_layer.render(ptz_pose)
        frame += self.haze_layer.render(ptz_pose)
        frame += self.gradient_layer.render(ptz_pose)
        frame += self.vignetting.apply(frame)
        for rt in scenario.active_terminals:
            az, el = rt.angular_position_in_fov(ptz_pose)
            frame += self.spot_renderer.render(az, el, rt.current_intensity)
        return frame
```

### Layer Stack

| Layer | Source | Effect |
|-------|--------|--------|
| Star field | `environment/stars.py` | Persistent point-source clutter |
| Atmospheric haze | `environment/haze.py` | Spatially-varying background luminance |
| Sky gradient | `environment/gradient.py` | Day/night sky gradient |
| Vignetting | `environment/vignetting.py` | Radial intensity roll-off |
| RT spot | `remote_terminal/optics.py` | OOK-modulated point source |
| Disturbance overlay | `disturbance/` | Scintillation, wander, noise |

---

## 3. Sensor Model

### 3.1 Photon-to-Electron Conversion

```
electrons = photons × quantum_efficiency
```

### 3.2 Noise Sources

| Noise Type | Model |
|------------|-------|
| Shot noise | Poisson(`electrons`) |
| Dark current | Gaussian(μ=dark_rate×t, σ²=dark_rate×t) |
| Read noise | Gaussian(0, σ_read²) |
| Fixed-pattern noise | Per-pixel gain/offset (PRNU) |

### 3.3 ADC Quantisation

```
DN = clip(electrons / full_well × (2^bit_depth - 1), 0, 2^bit_depth - 1)
```

Default: 12-bit ADC, 16-bit storage (uint16).

### 3.4 Camera Parameters

| Parameter | Symbol | Typical Value |
|-----------|--------|---------------|
| Frame rate | fps | 30 Hz |
| Pixel pitch | p | 5 μm |
| Focal length | f | 200 mm |
| Aperture | D | 30 mm |
| Full-well capacity | FWC | 50 000 e⁻ |
| Read noise | σ_r | 5 e⁻ RMS |
| Dark current | j_d | 100 e⁻/s/pixel |
| Quantum efficiency | QE | 0.6 |
| Bit depth | — | 12 bit |

---

## 4. CameraFrame

```python
@dataclass
class CameraFrame:
    data: np.ndarray           # float32 [H × W], normalised 0–1
    timestamp_s: float         # simulation time of frame centre
    frame_index: int           # monotonically increasing
    exposure_s: float          # integration time
    gain: float                # sensor gain
    metadata: dict             # auxiliary info (ptz_pose at capture, etc.)
```

> **Boundary rule**: `CameraFrame.metadata` may contain local PTZ pose but **never** contains any field from the remote terminal.

---

## 5. OpticalMeasurement

For every candidate blob detected in a frame, the `FrameProcessor` + `DetectionEngine` produce an `OpticalMeasurement`:

```python
@dataclass
class OpticalMeasurement:
    # Spatial
    centroid_x: float           # sub-pixel centroid, image coordinates
    centroid_y: float
    bounding_box: BBox          # (x, y, w, h)
    area_px: float              # blob area in pixels
    apparent_diameter_px: float # estimated point-spread diameter

    # Radiometric
    peak_intensity: float       # peak pixel DN (normalised)
    integrated_intensity: float # sum over bounding box
    background_level: float     # local background estimate
    snr: float                  # signal / noise estimate

    # Shape
    shape_metrics: ShapeMetrics # eccentricity, solidity, roundness

    # Spectral
    spectral_estimate: float    # estimated wavelength [nm] from spectral model
                                # — NOT fabricated from payload data

    # Temporal
    timestamp_s: float
    frame_index: int
```

### Background Estimation

Background is estimated using a local annular region around the candidate:

```python
background = median(pixels in annulus(cx, cy, r_inner, r_outer))
snr = (peak_intensity - background) / noise_std
```

### Spectral Estimate

The spectral estimate uses the sensor's spectral response curve and the measured relative intensities across any available spectral channels (or a single-band estimate from colour ratio if a Bayer pattern is simulated):

```
spectral_estimate_nm = sensor_spectral_response.invert(
    measured_spectral_shape
)
```

> **Critical**: `spectral_estimate` must **not** be derived from `signature_score × 1550`. It must come from genuine optical measurement.

---

## 6. Frame Rate and Timing

### Camera Rate

```
camera_fps = 30 Hz  (configurable)
camera_period_s = 1.0 / camera_fps
```

### Temporal History Requirement

The temporal signal extractor needs enough history to cover at least two full beacon frames:

```
frame_duration_s = n_frame_bits / chip_rate_hz
required_history_s = 2 × frame_duration_s × safety_factor
required_camera_samples = ceil(required_history_s × camera_fps)
```

Example with defaults:
```
chip_rate_hz = 12.0
compact_payload ≈ 16 bytes = 128 bits
frame_overhead ≈ 40 bits (preamble + sync + header + CRC)
total_bits ≈ 168
frame_duration_s ≈ 14 s   ← with 12 chips/s and 1 bit/chip (NRZ)
```

> **Note**: If chip_rate_hz is too low for a given camera fps, the validator rejects the config and recommends adjustments.

---

## 7. PTZ Pose at Frame Capture

Each `CameraFrame` is tagged with the PTZ pose at the time of exposure:

```python
ptz_pose = PTZPose(
    azimuth_rad=...,
    elevation_rad=...,
    fov_h_rad=...,
    fov_v_rad=...,
)
frame.metadata["ptz_pose"] = ptz_pose
```

This allows pixel centroids to be converted to world angular coordinates during tracking and search.

---

## 8. Configuration (`environment/config.py`)

```python
@dataclass
class CameraConfig:
    width_px: int = 1280
    height_px: int = 1024
    fps: float = 30.0
    focal_length_mm: float = 200.0
    pixel_pitch_um: float = 5.0
    fov_h_deg: float = 1.83     # derived from focal length + sensor size
    fov_v_deg: float = 1.47
    bit_depth: int = 12
    full_well_e: float = 50000.0
    read_noise_e: float = 5.0
    dark_current_e_per_s: float = 100.0
    quantum_efficiency: float = 0.60
    enable_shot_noise: bool = True
    enable_read_noise: bool = True
    enable_dark_current: bool = True
    enable_prnu: bool = False
```

---

## 9. Key Properties

| Property | Value |
|----------|-------|
| Camera provides | pixel array + timestamp |
| Camera does NOT provide | RT identity, RT position, transmitted bits |
| Spectral channels | 1 (monochrome) or 3 (colour — Bayer) |
| Dynamic range | 12 bit (4096 levels) |
| Noise model | Shot + read + dark current |
| Frame timestamp accuracy | ±0.5 × camera_period |
