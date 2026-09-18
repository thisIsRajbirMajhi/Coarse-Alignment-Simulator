# Architecture Overview

> **Scope**: Top-level system design, primary data-flow boundaries, and the two-path model.

---

## 1. System Purpose

The **Coarse-Alignment-Simulator** models an end-to-end Free-Space Optical (FSO) communication link in which a **Remote Terminal (RT)** broadcasts a digitally-encoded beacon signal through an atmospheric channel, and a **Local Terminal (LT)** autonomously detects, identifies, acquires, tracks, and reacquires the remote terminal using only camera observations.

The simulation exercises the complete receiver pipeline — from raw photons on sensor to closed-loop PTZ pointing — without any ground-truth shortcuts.

---

## 2. Top-Level Signal Flow

```
REMOTE TERMINAL
│
│  BeaconPayload
│      └─ compact binary serialization
│            └─ BeaconFrame (PREAMBLE + SYNC + header + payload + CRC-8)
│                  └─ OOK encoding → chip sequence
│                         └─ intensity modulation of optical beam
│
▼
OPTICAL PROPAGATION
│  beam divergence, pointing offset, geometric losses
│
▼
DISTURBANCE / CHANNEL
│  atmospheric turbulence (scintillation), wander, haze, attenuation, noise
│
▼
CAMERA / SENSOR
│  photon arrival → sensor model → pixel rendering → CameraFrame
│
▼
LOCAL TERMINAL
│
│  FrameProcessor
│      └─ pre-processing, background subtraction, noise reduction
│
│  CandidateDetector
│      └─ blob detection, thresholding, centroid extraction
│
│  CandidateAssociation
│      └─ IoU / nearest-centroid matching, track management
│
│  OpticalMeasurement
│      └─ centroid, bounding box, area, SNR, spectral estimate
│
│  TemporalSignalExtractor
│      └─ intensity history, background estimate, normalized signal
│
│  SignalSynchronizer
│      └─ preamble/sync detection, chip-rate estimation, frame-start
│
│  OOKDemodulator
│      └─ adaptive threshold, bit recovery, chip quality
│
│  BeaconFrameParser
│      └─ frame validation, CRC check, BeaconDecodeResult
│
│  PayloadDecoder
│      └─ compact binary parse → DecodedPayload
│
│  IdentityValidator
│      └─ terminal_id, token, wavelength, sequence, persistence check
│
│  CandidateLifecycle
│      └─ state transitions: SEEN → … → TRACKING / LOST
│
│  Candidate Selection
│      └─ priority: digital identity > signal quality > optical quality
│
│  Dual-Lock Acquisition
│      └─ identity lock AND spatial lock → ACQUIRED
│
│  Image-Based Tracking
│      └─ centroid → PTZ controller (PID / predictive)
│
│  Identity / Liveness Monitoring
│      └─ continuous validation, degradation detection
│
│  Degradation
│      └─ quality metrics trending down → DEGRADED
│
│  Identity-Gated Reacquisition
│      └─ predicted search → candidate decode → identity gate → merge
│
▼
PTZ ACTUATOR (closed-loop)
```

---

## 3. The Two-Path Model

The architecture enforces a fundamental separation:

```
OPTICAL PATH                        DIGITAL BEACON PATH
─────────────────────────────────   ─────────────────────────────────
CameraFrame pixels                  temporal intensity modulation
     ↓                                       ↓
centroid extraction                 SignalSynchronizer
     ↓                                       ↓
bounding box / area / SNR           OOKDemodulator
     ↓                                       ↓
OpticalMeasurement                  BeaconFrameParser
     ↓                                       ↓
tracking error signal               PayloadDecoder
     ↓                                       ↓
PTZ control                         IdentityValidator
                                             ↓
                                    identity / liveness
```

**Where the two paths meet:**

```
CandidateLifecycle
       ↕
AcquisitionManager
       ↕
TrackingController
```

> **Rule**: The optical path answers **"where is the target?"**
> The digital path answers **"who is the target?"**
> Neither path substitutes for the other.

---

## 4. Module Map

```
Coarse-Alignment-Simulator/
│
├── common/
│   ├── config_base.py          # BaseConfig, validation helpers
│   ├── colors.py               # display colour constants
│   ├── rng.py                  # seeded random number generator
│   └── protocol/
│       └── beacon/
│           ├── __init__.py
│           ├── payload.py      # BeaconPayload, DecodedPayload, PayloadCodec
│           ├── frame.py        # BeaconFrame, BeaconFrameEncoder, BeaconFrameParser
│           ├── crc.py          # CRC8, CRCValidator
│           └── ook.py          # OOKEncoder, OOKDecodeResult
│
├── remote_terminal/
│   ├── config.py               # RemoteTerminalConfig, BeaconConfig
│   ├── terminal.py             # RemoteTerminal top-level class
│   ├── beacon_encoder.py       # runtime beacon pipeline
│   ├── optics.py               # beam model, divergence, intensity
│   ├── motion.py               # platform motion, angular kinematics
│   └── scenario.py             # scenario loader, multi-RT management
│
├── environment/
│   ├── config.py               # EnvironmentConfig
│   ├── scene.py                # SceneRenderer — composites all layers
│   ├── stars.py                # star field background
│   ├── haze.py                 # atmospheric haze layer
│   ├── gradient.py             # sky gradient
│   ├── vignetting.py           # sensor vignetting model
│   └── constants.py
│
├── disturbance/                # atmospheric channel models
│
├── local_terminal/
│   ├── config.py               # LocalTerminalConfig, TargetPayloadConfig
│   ├── terminal.py             # LocalTerminal top-level class
│   ├── system.py               # LocalSystem orchestrator
│   ├── frame_processor.py      # FrameProcessor
│   ├── candidate_detector.py   # CandidateDetector
│   ├── association.py          # CandidateAssociation
│   ├── models.py               # CandidateTrack, OpticalMeasurement, …
│   ├── states.py               # CandidateState enum
│   ├── detection.py            # DetectionEngine
│   ├── signature.py            # OpticalSignatureAnalyzer
│   ├── estimator.py            # StateEstimator (Kalman)
│   ├── signal_analyzer.py      # TemporalSignalExtractor, OOKDemodulator
│   ├── frame_decoder.py        # streaming FrameDecoder (sync + parse)
│   ├── identity_matcher.py     # IdentityValidator, IdentityDecision
│   ├── lifecycle.py            # CandidateLifecycle
│   ├── acquisition.py          # AcquisitionEngine, dual-lock logic
│   ├── acquisition_mgr.py      # AcquisitionManager
│   ├── tracking.py             # TrackingEngine, PID controller
│   ├── tracking_controller.py  # TrackingController wrapper
│   ├── reacquisition.py        # ReacquisitionEngine, staged search
│   ├── ptz_actuator.py         # PTZActuator, rate limiting, backlash
│   ├── search_manager.py       # SearchManager, scan pattern
│   ├── state_machine.py        # SystemStateMachine
│   ├── telemetry_mgr.py        # TelemetryManager, per-candidate telemetry
│   ├── beacon_frame.py         # (legacy shim — now imports from common)
│   └── metrics.py              # PerformanceMetrics, statistics
│
├── simulation/
│   ├── env.py                  # SimulationEnvironment
│   ├── fov_pipeline.py         # FOVPipeline — composites scene layers
│   └── headless.py             # HeadlessSimulation runner
│
├── gui/
│   ├── app.py
│   ├── main_window.py
│   ├── styles.py
│   ├── panels/                 # individual UI panels
│   ├── controllers/            # GUI ↔ sim bridge
│   ├── views/                  # plot views
│   └── windows/                # dialog windows
│
└── tests/
```

---

## 5. Configuration Hierarchy

```
RemoteTerminalConfig
    └── BeaconConfig
            ├── enabled
            ├── token
            ├── wavelength_nm
            ├── protocol_version
            ├── message_type
            ├── payload_codec      ("compact" | "json_debug")
            └── chip_rate_hz

LocalTerminalConfig
    └── TargetPayloadConfig
            ├── expected_terminal_id
            ├── expected_token
            ├── expected_wavelength_nm
            ├── expected_protocol_version
            ├── expected_message_type
            ├── required_valid_frames
            ├── sequence_validation_enabled
            ├── wavelength_validation_enabled
            ├── max_sequence_gap
            ├── identity_timeout_s
            └── max_identity_fail_streak
```

---

## 6. Boundary Rules (Non-Negotiable)

| Rule | Detail |
|------|--------|
| LT never reads RT object | `RemoteTerminal`, `RemoteTerminal.pose`, `RemoteTerminal.id` are all forbidden |
| LT never reads transmitted bits/chips | The original bitstream is inaccessible to the receiver |
| Optical identity is not authoritative | `IDENTIFIED` requires a decoded payload — no exceptions in normal mode |
| legacy_optical_identification_enabled = False | The legacy optical shortcut is permanently off by default |
| Payload parsing is centralized | No scattered payload logic in `system.py`, `telemetry_mgr.py`, etc. |
| Streaming decoder only | `FrameDecoder` tracks `last_processed_index` and only appends new samples |
