# Detection and Searching

> **Scope**: Search manager, scan patterns, frame processing, and candidate detection — the front end of the receiver pipeline.

---

## 1. Overview

Detection and searching convert a raw `CameraFrame` into a set of **candidate blobs** that feed the rest of the receiver pipeline.

```
CameraFrame
    │
    ▼
FrameProcessor          pre-processing, background subtraction
    │
    ▼
CandidateDetector       blob finding, thresholding, centroid extraction
    │
    ▼
DetectionEngine         quality filtering, false-alarm suppression
    │
    ▼
CandidateAssociation    match to existing tracks
    │
    ▼ (new)             (updated)
New candidate tracks    Existing track measurements
```

The **SearchManager** drives PTZ scan patterns during the SEARCH phase, before any candidate is being actively tracked.

---

## 2. SearchManager (`search_manager.py`)

### Purpose

The `SearchManager` commands PTZ scan patterns to sweep the field of regard until a candidate is detected.

### Search States

```
IDLE
  │  start_search()
  ▼
SEARCHING
  │  candidate detected above threshold
  ▼
CANDIDATE_FOUND
  │  candidate qualifies for track creation
  ▼
HANDOFF (to lifecycle)
```

### Scan Patterns

| Pattern | Description |
|---------|-------------|
| Raster | Left-to-right, top-to-bottom sweep |
| Spiral | Expanding outward from centre |
| Rose | Lemniscate/rose curve for coverage |
| Sector | Constrained angular sector sweep |
| Targeted | Directed at predicted position (used in reacquisition) |

### Search Rate

```python
scan_rate_deg_s = fov_h_deg × fps / overlap_fraction
```

The scan rate is set so that a target at any point in the search volume will fall within the FOV for at least `min_dwell_frames` frames — enough to detect and start temporal signal extraction.

### Configuration

```python
@dataclass
class SearchConfig:
    pattern: str = "raster"           # "raster" | "spiral" | "sector"
    scan_rate_deg_s: float = 2.0
    min_dwell_frames: int = 5
    search_fov_h_deg: float = 30.0
    search_fov_v_deg: float = 20.0
    overlap_fraction: float = 0.2     # FOV overlap between passes
    return_to_centre_on_complete: bool = True
```

---

## 3. FrameProcessor (`frame_processor.py`)

### Purpose

The `FrameProcessor` prepares each `CameraFrame` for blob detection by reducing noise and estimating background.

### Processing Steps

```
CameraFrame.data  (float32 H×W)
    │
    ▼  1. Temporal frame averaging (rolling average over N frames)
    │       reduces uncorrelated read noise
    │
    ▼  2. Spatial background estimation
    │       large-kernel median or morphological open operation
    │
    ▼  3. Background subtraction
    │       processed = raw - background
    │
    ▼  4. Noise floor estimation
    │       σ = MAD(processed) × 1.4826
    │
    ▼  5. Normalisation
    │       normalised = processed / σ   (SNR map)
    │
    ▼
ProcessedFrame
    ├── data_raw: np.ndarray
    ├── data_background: np.ndarray
    ├── data_subtracted: np.ndarray
    ├── data_snr: np.ndarray
    ├── noise_floor: float
    └── timestamp_s: float
```

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `temporal_avg_frames` | 3 | Number of frames for temporal averaging |
| `background_kernel_px` | 51 | Kernel size for background estimation |
| `snr_threshold` | 5.0 | Minimum SNR to declare a detection |

---

## 4. CandidateDetector (`candidate_detector.py`)

### Purpose

Find blobs in the processed frame that are plausible beacon candidates.

### Detection Pipeline

```
ProcessedFrame.data_snr
    │
    ▼  Threshold at snr_threshold
    │
    ▼  Connected component labelling (scipy.ndimage.label or cv2.connectedComponents)
    │
    ▼  Per-component feature extraction:
    │      - centroid (x, y)  ← sub-pixel: intensity-weighted centroid
    │      - bounding box
    │      - area (pixels)
    │      - peak SNR
    │      - integrated SNR
    │      - eccentricity / roundness
    │
    ▼  Quality filter:
    │      - min_area_px ≤ area ≤ max_area_px
    │      - peak_snr ≥ min_snr
    │      - roundness ≥ min_roundness    (rejects streaks / artefacts)
    │
    ▼
List[DetectedBlob]
```

### Sub-Pixel Centroid

```python
cx = sum(I[r,c] × c for r,c in blob) / sum(I[r,c] for r,c in blob)
cy = sum(I[r,c] × r for r,c in blob) / sum(I[r,c] for r,c in blob)
```

### False Alarm Suppression

The detector applies several rejection criteria:

| Criterion | Purpose |
|-----------|---------|
| Area bounds | Rejects single hot pixels and extended objects |
| Roundness | Rejects cosmic ray streaks, edge artefacts |
| Temporal persistence | A blob appearing only in one frame is marked `TRANSIENT` |
| Peak / integrated SNR ratio | Rejects diffuse low-contrast regions |

### Configuration

```python
@dataclass
class DetectorConfig:
    snr_threshold: float = 5.0
    min_area_px: float = 0.5
    max_area_px: float = 50.0
    min_roundness: float = 0.6
    min_peak_snr: float = 4.0
    min_persistence_frames: int = 2
    max_candidates_per_frame: int = 32
```

---

## 5. DetectionEngine (`detection.py`)

### Purpose

The `DetectionEngine` wraps `FrameProcessor` + `CandidateDetector` and applies higher-level filtering using historical knowledge:

- **Star rejection**: known star positions (from a built-in catalogue or learned from stable frames) are masked.
- **Clutter map**: regions with persistent high false-alarm rate are de-weighted.
- **Motion consistency**: candidates moving faster than physically plausible are rejected.

### OpticalSignatureAnalyzer (`signature.py`)

After blob detection, the signature analyser extracts photometric and morphological features:

```python
@dataclass
class OpticalSignature:
    peak_intensity: float
    integrated_intensity: float
    background_level: float
    snr: float
    area_px: float
    apparent_diameter_px: float
    eccentricity: float
    solidity: float
    spectral_estimate_nm: float
    modulation_depth: float       # temporal — estimated from last N frames
    modulation_frequency_hz: float
```

The optical signature is used for:
- Candidate quality scoring
- Search prioritisation
- False alarm rejection
- Association confidence
- Tracking quality

> **Not used for identity** — a high-quality optical signature does not identify the RT.

---

## 6. CandidateAssociation (`association.py`)

### Purpose

Match newly detected blobs to existing candidate tracks (or create new ones).

### Association Algorithm

```
For each detected blob B:
    candidates = existing_tracks sorted by predicted_position_distance(B)
    for track T in candidates:
        if spatial_gate(B, T) and appearance_similarity(B, T):
            associate B → T
            break
    else:
        create new track from B
```

### Spatial Gate

```python
gate_radius_px = max(
    min_gate_px,
    k_sigma × position_uncertainty_px,   # Kalman uncertainty
)

distance = euclidean(blob.centroid, track.predicted_centroid)
accepted = distance < gate_radius_px
```

### Appearance Similarity

```
similarity = w_snr × ΔSNR + w_area × ΔArea + w_sig × ΔSignature
```

A low similarity score causes a new track to be created rather than forcing an association.

### Track Lifecycle Interaction

- Blobs that match an existing track → update that track's `OpticalMeasurement`.
- Unmatched tracks → increment `missed_frame_count`.
- Unmatched blobs → spawn new `CandidateTrack` in `SEEN` state.

### Configuration

```python
@dataclass
class AssociationConfig:
    max_gate_px: float = 30.0
    min_gate_px: float = 3.0
    k_sigma: float = 3.0
    min_appearance_similarity: float = 0.3
    max_missed_frames_before_drop: int = 10
```

---

## 7. Interaction with Reacquisition Search

During **reacquisition**, the `SearchManager` switches to a targeted search pattern:

```
predicted_position (from Kalman or last known)
    │
    ▼  Stage 1: ±2° window  (raster / spiral)
    ▼  Stage 2: ±5° window
    ▼  Stage 3: ±10° window
```

Candidates found during reacquisition still pass through the full detection pipeline and are handed to the reacquisition engine for identity gating.

---

## 8. Data Flow Summary

```
tick(camera_frame):
    processed = frame_processor.process(camera_frame)
    blobs = candidate_detector.detect(processed)
    blobs = detection_engine.filter(blobs, history)
    associations = candidate_association.update(blobs, tracks)
    for new_blob in associations.new:
        create_candidate_track(new_blob)
    for (blob, track) in associations.matched:
        track.update_optical_measurement(blob)
    for track in associations.missed:
        track.increment_missed_frames()
```
