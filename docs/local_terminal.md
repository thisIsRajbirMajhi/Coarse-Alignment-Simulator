# Local Terminal

> **Scope**: Local terminal top-level architecture, `LocalSystem` orchestrator, module responsibilities, data flow, and configuration.

---

## 1. Overview

The **Local Terminal (LT)** is the receiver side of the FSO link. It accepts only:
- `CameraFrame` — the sole observation of the external world.
- Local PTZ pose and velocity.
- Local configuration.

It must never read any field from the `RemoteTerminal` object, remote position, remote ID, or transmitted bitstream.

---

## 2. Module Responsibilities

```
local_terminal/
│
├── terminal.py          LocalTerminal — top-level entry point
├── system.py            LocalSystem — orchestrates all subsystems per tick
├── config.py            LocalTerminalConfig, TargetPayloadConfig, all sub-configs
│
├── frame_processor.py   FrameProcessor — pre-processing, background subtraction
├── candidate_detector.py CandidateDetector — blob detection, sub-pixel centroid
├── association.py       CandidateAssociation — track-to-blob matching
│
├── models.py            CandidateTrack, OpticalMeasurement, all data classes
├── states.py            CandidateState, IdentityState enums
│
├── detection.py         DetectionEngine — clutter filter, star rejection
├── signature.py         OpticalSignatureAnalyzer — photometric features
├── estimator.py         StateEstimator — Kalman filter for track kinematics
│
├── signal_analyzer.py   TemporalSignalExtractor, SignalSynchronizer, OOKDemodulator
├── frame_decoder.py     FrameDecoder — streaming stateful beacon decoder
├── identity_matcher.py  IdentityValidator, IdentityDecision
│
├── lifecycle.py         CandidateLifecycle — state machine transitions
├── acquisition.py       AcquisitionEngine — dual-lock acquisition logic
├── acquisition_mgr.py   AcquisitionManager — orchestration, centering
├── tracking.py          TrackingEngine — PID, Kalman-based PTZ control
├── tracking_controller.py TrackingController — mode dispatcher
├── reacquisition.py     ReacquisitionEngine — identity-gated staged search
│
├── ptz_actuator.py      PTZActuator — rate limiting, backlash, position limits
├── search_manager.py    SearchManager — scan pattern generation
├── state_machine.py     SystemStateMachine — top-level SEARCH/TRACK states
│
├── telemetry_mgr.py     TelemetryManager — per-candidate and global telemetry
├── metrics.py           PerformanceMetrics — statistics, rms error
└── beacon_frame.py      (legacy shim — imports from common.protocol.beacon)
```

---

## 3. LocalTerminal (`terminal.py`)

Entry point for external code:

```python
class LocalTerminal:
    def __init__(self, config: LocalTerminalConfig):
        self.system = LocalSystem(config)

    def step(self, camera_frame: CameraFrame) -> LocalTerminalOutput:
        """Process one camera frame. Returns telemetry and PTZ commands."""
        return self.system.step(camera_frame)

    @property
    def telemetry(self) -> SystemTelemetry: ...

    @property
    def active_candidate(self) -> CandidateTrack | None: ...
```

---

## 4. LocalSystem Orchestrator (`system.py`)

`LocalSystem.step()` is called once per camera frame and drives the entire pipeline:

```python
def step(self, frame: CameraFrame) -> LocalTerminalOutput:

    # 1. Pre-process frame
    processed = self.frame_processor.process(frame)

    # 2. Detect blobs
    blobs = self.candidate_detector.detect(processed)
    blobs = self.detection_engine.filter(blobs)

    # 3. Associate blobs to existing tracks
    associations = self.association.update(blobs, self.tracks)

    # 4. Update each existing track
    for track, blob in associations.matched:
        measurement = build_optical_measurement(blob, frame)
        track.update_optical(measurement)
        self.state_estimator.update(track, measurement)
        self.signal_extractor.update(track, measurement)
        decode_result = self.frame_decoder.update(track.observation_id,
                                                   track.extracted_signal)
        if decode_result.frame_detected:
            payload = self.payload_decoder.decode(decode_result.payload_bytes)
            decision = self.identity_validator.validate(
                decode_result, payload, track, self.config.target_payload
            )
            self.lifecycle.apply_identity_decision(track, decision)
        self.lifecycle.update(track, frame.timestamp_s)

    # 5. Handle new blobs → new tracks
    for blob in associations.new:
        track = self._create_candidate(blob, frame)
        self.tracks.append(track)

    # 6. Handle missed tracks
    for track in associations.missed:
        track.missed_frame_count += 1
        self.lifecycle.on_missed_frame(track, frame.timestamp_s)

    # 7. System state machine + selection
    self.state_machine.update(self.tracks)
    if self.state_machine.state == SystemState.SEARCHING:
        self.search_manager.update()
        ptz_cmd = self.search_manager.get_ptz_command()
    elif self.state_machine.state == SystemState.ACQUIRING:
        ptz_cmd = self.acquisition_mgr.update(self.active_candidate, frame)
    elif self.state_machine.state in (SystemState.TRACKING,
                                       SystemState.DEGRADED,
                                       SystemState.REACQUIRING):
        ptz_cmd = self.tracking_controller.update(self.active_candidate, frame)
    else:
        ptz_cmd = PTZCommand.hold()

    # 8. Actuate PTZ
    self.ptz_actuator.execute(ptz_cmd)

    # 9. Collect telemetry
    telemetry = self.telemetry_mgr.collect(self.tracks, self.state_machine.state)

    return LocalTerminalOutput(ptz_command=ptz_cmd, telemetry=telemetry)
```

---

## 5. LocalTerminalConfig (`config.py`)

```python
@dataclass
class LocalTerminalConfig:
    # Sub-configs
    camera: CameraConfig
    detector: DetectorConfig
    association: AssociationConfig
    signal_processing: SignalProcessingConfig
    target_payload: TargetPayloadConfig          # first-class field
    acquisition: AcquisitionConfig
    tracking: TrackingConfig
    reacquisition: ReacquisitionConfig
    ptz: PTZConfig
    search: SearchConfig
    estimator: EstimatorConfig

    # Legacy
    legacy_optical_identification_enabled: bool = False

    def validate(self): ...      # raises ConfigError on invalid combinations
    def from_dict(cls, d: dict): ...
    def to_dict(self) -> dict: ...
```

`TargetPayloadConfig` is a **first-class field** — it is present at construction time, participates in validation, serialisation, and deserialisation. It is never attached dynamically at runtime.

---

## 6. System State Machine (`state_machine.py`)

```python
class SystemState(Enum):
    IDLE         = "IDLE"
    SEARCHING    = "SEARCHING"
    ACQUIRING    = "ACQUIRING"
    TRACKING     = "TRACKING"
    DEGRADED     = "DEGRADED"
    REACQUIRING  = "REACQUIRING"
    FAULT        = "FAULT"
```

```
IDLE
  │ start()
  ▼
SEARCHING
  │ identified candidate available
  ▼
ACQUIRING
  │ dual lock
  ▼
TRACKING ◄─────────────────────┐
  │ quality drops              │
  ▼                            │
DEGRADED                       │
  │ persistent failure         │
  ▼                            │
REACQUIRING ───────────────────┘ (on success)
  │ timeout
  ▼
SEARCHING (restart)
```

---

## 7. Data Boundary Enforcement

The local terminal enforces the image-only boundary at every layer:

| Layer | Enforcement |
|-------|------------|
| `LocalTerminal.step()` | Accepts only `CameraFrame`, not `RemoteTerminal` |
| `CameraFrame` | Contains no RT fields |
| `LocalTerminalConfig` | Contains no RT-specific truth values |
| `IdentityValidator` | Reads only `DecodedPayload` (from camera-derived signal) |
| `TrackingEngine` | Commands PTZ from centroid only — no payload fields |
| `ReacquisitionEngine` | Matches identity from decoded signal — no RT truth |

Any import of `remote_terminal.*` inside `local_terminal.*` is a hard architectural violation.

---

## 8. LocalTerminalOutput

```python
@dataclass
class LocalTerminalOutput:
    ptz_command: PTZCommand
    telemetry: SystemTelemetry
    active_candidate: CandidateTrack | None
    all_candidates: list[CandidateTrack]
    frame_index: int
    timestamp_s: float
```

---

## 9. Configuration Round-Trip

`LocalTerminalConfig` must support:

```python
# Create
config = LocalTerminalConfig(
    target_payload=TargetPayloadConfig(
        expected_terminal_id="RT-001",
        expected_token="ALPHA-7",
    ),
    ...
)

# Serialise
d = config.to_dict()

# Deserialise
config2 = LocalTerminalConfig.from_dict(d)

# Validate
config2.validate()   # raises ConfigError if timing is incoherent, etc.
```

This round-trip must work through GUI configuration panels, headless simulation YAML files, and programmatic construction.
