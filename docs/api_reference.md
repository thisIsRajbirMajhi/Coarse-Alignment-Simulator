# API Reference

> **Scope**: Public interfaces, class signatures, method signatures, and data model types for all major modules.

---

## 1. `common/protocol/beacon/`

### `BeaconPayload`

```python
@dataclass
class BeaconPayload:
    terminal_id: str           # Remote terminal ID string, e.g. "RT-001"
    token: str                 # Authentication token, e.g. "ALPHA-7"
    wavelength_nm: float       # Beacon wavelength in nanometres, e.g. 1550.0
    sequence_number: int       # Frame sequence counter, monotonically increasing
```

### `DecodedPayload`

```python
@dataclass
class DecodedPayload:
    terminal_id: str
    token: str
    wavelength_nm: float
    sequence_number: int
```

### `PayloadCodec`

```python
class PayloadCodec:
    def encode(self, payload: BeaconPayload) -> bytes:
        """Serialise to compact binary wire format. Raises PayloadEncodeError."""

    def decode(self, data: bytes) -> DecodedPayload:
        """Parse compact binary bytes. Raises PayloadDecodeError on any failure."""
```

### `BeaconDecodeResult`

```python
@dataclass
class BeaconDecodeResult:
    frame_detected: bool           # True if a complete frame structure was found
    synchronized: bool             # True if preamble and sync word were located
    valid_crc: bool                # True if CRC-8 passed
    protocol_version: int | None   # Parsed protocol version byte
    message_type: int | None       # Parsed message type byte
    payload_length: int | None     # Parsed payload length byte
    payload_bytes: bytes | None    # Raw payload bytes (if CRC passed)
    decode_confidence: float       # 0.0–1.0 aggregate confidence
    reason: str                    # Human-readable outcome or failure reason
    is_new_frame: bool             # True only if sequence_number > last_valid_sequence
```

### `BeaconFrameEncoder`

```python
class BeaconFrameEncoder:
    def encode(self, payload: BeaconPayload, codec: PayloadCodec) -> bytes:
        """
        Assemble a complete wire frame:
        PREAMBLE + SYNC + VERSION + MSG_TYPE + LEN + PAYLOAD + CRC-8
        Returns raw bytes ready for OOK encoding.
        """
```

### `BeaconFrameParser`

```python
class BeaconFrameParser:
    def parse(self, recovered_bytes: bytes) -> BeaconDecodeResult:
        """
        Parse a recovered byte sequence from the OOK demodulator.
        Validates: preamble pattern, sync word, protocol version,
        message type, payload length, CRC-8, payload structure.
        Returns a fully populated BeaconDecodeResult.
        """
```

### `SynchronizationResult`

```python
@dataclass
class SynchronizationResult:
    synchronized: bool
    frame_start_sample: int        # Index in signal array where frame begins
    estimated_chip_rate_hz: float  # Estimated chip rate from preamble autocorrelation
    confidence: float              # 0.0–1.0 match quality
    reason: str                    # e.g. "OK", "LOW_CONFIDENCE", "NO_PREAMBLE"
```

### `OOKEncoder`

```python
class OOKEncoder:
    def encode_frame(self, frame_bytes: bytes) -> list[int]:
        """Convert bytes to NRZ chip sequence {0, 1}."""

    def chips_to_intensity(
        self,
        chips: list[int],
        on_intensity: float,
        off_intensity: float,
    ) -> list[float]:
        """Map chip values to optical intensity levels."""
```

### `CRC8`

```python
class CRC8:
    def compute(self, data: bytes) -> int:
        """CRC-8/MAXIM. Returns single byte checksum."""

class CRCValidator:
    def validate(self, frame_bytes_including_crc: bytes) -> bool:
        """True if the last byte of frame_bytes is the correct CRC of the preceding bytes."""
```

---

## 2. `local_terminal/terminal.py`

### `LocalTerminal`

```python
class LocalTerminal:
    def __init__(self, config: LocalTerminalConfig): ...

    def step(self, camera_frame: CameraFrame) -> LocalTerminalOutput:
        """
        Process one camera frame through the complete receiver pipeline.
        Must be called once per camera frame. Not thread-safe.

        Parameters:
            camera_frame: CameraFrame — the current sensor image

        Returns:
            LocalTerminalOutput — PTZ command, telemetry, candidate list
        """

    @property
    def telemetry(self) -> SystemTelemetry: ...

    @property
    def active_candidate(self) -> CandidateTrack | None: ...

    @property
    def all_candidates(self) -> list[CandidateTrack]: ...

    @property
    def ptz_pose(self) -> PTZPose: ...

    def reset(self) -> None:
        """Reset all internal state. PTZ returns to home position."""
```

### `LocalTerminalOutput`

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

## 3. `local_terminal/models.py`

### `CameraFrame`

```python
@dataclass
class CameraFrame:
    data: np.ndarray           # float32 [H, W], normalised 0–1
    timestamp_s: float         # simulation wall-clock time at frame centre
    frame_index: int           # monotonically increasing from 0
    exposure_s: float          # integration time in seconds
    gain: float                # sensor gain multiplier
    metadata: dict             # local PTZ pose and other diagnostics
                               # NEVER contains RemoteTerminal data
```

### `OpticalMeasurement`

```python
@dataclass
class OpticalMeasurement:
    centroid_x: float           # sub-pixel centroid, pixels, image coordinates
    centroid_y: float
    bounding_box: tuple         # (x, y, width, height) in pixels
    area_px: float              # blob area in pixels
    apparent_diameter_px: float # estimated spot diameter in pixels
    peak_intensity: float       # peak pixel value (normalised 0–1)
    integrated_intensity: float # sum of pixel values over bounding box
    background_level: float     # local background estimate
    snr: float                  # signal-to-noise ratio (linear)
    shape_metrics: ShapeMetrics # eccentricity, solidity, roundness
    spectral_estimate_nm: float # wavelength estimate from spectral model
    timestamp_s: float
    frame_index: int
```

### `CandidateTrack`

```python
@dataclass
class CandidateTrack:
    # Identity
    observation_id: str                  # "BEACON-001" — locally generated
    decoded_terminal_id: str | None      # from payload, e.g. "RT-001"
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    last_valid_sequence: int | None
    identity_state: IdentityState
    identity_reason: str
    identity_confidence: float           # 0–1
    identity_matched: bool               # True if identity_lock held
    valid_frame_count: int
    invalid_frame_count: int
    identity_fail_streak: int

    # Lifecycle
    lifecycle_state: CandidateState
    created_at_s: float
    last_updated_s: float
    missed_frame_count: int

    # Optical
    latest_measurement: OpticalMeasurement | None
    centroid_history: deque
    timestamp_history: deque
    intensity_history: deque

    # Signal / Decode
    signal_quality: float
    modulation_detected: bool
    sync_state: str
    sync_confidence: float
    decode_state: str
    decode_reason: str
    last_valid_frame: BeaconDecodeResult | None
    last_valid_frame_time: float | None

    # Spatial
    position_estimate: np.ndarray    # [cx, cy] pixels, Kalman-filtered
    velocity_estimate: np.ndarray    # [vx, vy] pixels/frame
    position_uncertainty: np.ndarray # Kalman covariance diagonal
    predicted_position: np.ndarray   # next-frame prediction

    # Locks
    spatial_lock: bool
    identity_lock: bool
    acquisition_quality: float

    # Wavelength
    measured_wavelength_nm: float | None
    wavelength_consistency: float | None
```

---

## 4. `local_terminal/identity_matcher.py`

### `IdentityValidator`

```python
class IdentityValidator:
    def validate(
        self,
        decode_result: BeaconDecodeResult,
        payload: DecodedPayload | None,
        track: CandidateTrack,
        config: TargetPayloadConfig,
    ) -> IdentityDecision:
        """
        Runs the 12-step identity validation chain.
        Returns IdentityDecision — never raises on invalid data.
        """
```

### `IdentityDecision`

```python
@dataclass
class IdentityDecision:
    identity_state: IdentityState
    reason_code: IdentityReasonCode
    confidence: float
    is_new_liveness: bool          # True only if new unique valid sequence
    decoded_terminal_id: str | None
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    decoded_sequence: int | None
```

### `IdentityState` (Enum)

```python
class IdentityState(str, Enum):
    VALID_TARGET        = "VALID_TARGET"        # all checks passed
    WRONG_TERMINAL      = "WRONG_TERMINAL"      # terminal_id mismatch
    WRONG_TOKEN         = "WRONG_TOKEN"         # token mismatch
    WRONG_PROTOCOL      = "WRONG_PROTOCOL"      # version or msg_type mismatch
    WAVELENGTH_MISMATCH = "WAVELENGTH_MISMATCH" # wavelength outside tolerance
    INVALID_SEQUENCE    = "INVALID_SEQUENCE"    # duplicate, old, or jump
    UNKNOWN             = "UNKNOWN"             # no data, CRC fail, low confidence
```

### `IdentityReasonCode` (Enum)

```python
class IdentityReasonCode(str, Enum):
    OK                     = "OK"
    NO_DATA                = "NO_DATA"
    CRC_FAILURE            = "CRC_FAILURE"
    PROTOCOL_MISMATCH      = "PROTOCOL_MISMATCH"
    MALFORMED_PAYLOAD      = "MALFORMED_PAYLOAD"
    TID_MISMATCH           = "TID_MISMATCH"
    TOKEN_MISMATCH         = "TOKEN_MISMATCH"
    WAVELENGTH_MISMATCH    = "WAVELENGTH_MISMATCH"
    DUPLICATE_SEQUENCE     = "DUPLICATE_SEQUENCE"
    OLD_SEQUENCE           = "OLD_SEQUENCE"
    SEQUENCE_DISCONTINUITY = "SEQUENCE_DISCONTINUITY"
    LOW_CONFIDENCE         = "LOW_CONFIDENCE"
    INSUFFICIENT_FRAMES    = "INSUFFICIENT_FRAMES"
```

---

## 5. `local_terminal/states.py`

### `LocalTerminalState` (Enum)

```python
class LocalTerminalState(str, Enum):
    IDLE        = "IDLE"
    SEARCHING   = "SEARCHING"
    DETECTING   = "DETECTING"
    DECODING    = "DECODING"       # beacon signal actively being decoded
    VERIFYING   = "VERIFYING"      # identity verified, spatial lock pending
    ACQUIRED    = "ACQUIRED"
    TRACKING    = "TRACKING"
    DEGRADED    = "DEGRADED"
    REACQUIRING = "REACQUIRING"
    LOST        = "LOST"
    FAULT       = "FAULT"

    @classmethod
    def coerce(cls, value, default=None) -> LocalTerminalState: ...
```

### `CandidateState` (Enum)

```python
class CandidateState(str, Enum):
    SEEN             = "SEEN"
    TENTATIVE        = "TENTATIVE"
    VALIDATING       = "VALIDATING"
    SIGNAL_DETECTED  = "SIGNAL_DETECTED"
    DECODING         = "DECODING"
    IDENTITY_UNKNOWN = "IDENTITY_UNKNOWN"
    IDENTIFIED       = "IDENTIFIED"
    SELECTED         = "SELECTED"
    ACQUIRING        = "ACQUIRING"
    ACQUIRED         = "ACQUIRED"
    TRACKING         = "TRACKING"
    DEGRADED         = "DEGRADED"
    REACQUIRING      = "REACQUIRING"
    REJECTED         = "REJECTED"
    LOST             = "LOST"
    EXPIRED          = "EXPIRED"

    @classmethod
    def coerce(cls, value, default=None) -> CandidateState: ...
```

---

## 6. `local_terminal/telemetry_mgr.py`

### `CandidateTelemetry`

```python
@dataclass
class CandidateTelemetry:
    observation_id: str
    lifecycle_state: str
    decoded_terminal_id: str | None
    decoded_token: str | None
    decoded_wavelength_nm: float | None
    sequence_number: int | None
    last_valid_sequence: int | None
    identity_state: str
    identity_reason: str
    identity_confidence: float
    valid_frame_count: int
    invalid_frame_count: int
    frame_sync_state: str
    frame_sync_confidence: float
    decode_state: str
    decode_reason: str
    estimated_chip_rate_hz: float | None
    signal_quality: float
    optical_quality: float
    snr: float
    centroid_x: float | None
    centroid_y: float | None
    missed_frames: int
```

### `SystemTelemetry`

```python
@dataclass
class SystemTelemetry:
    system_state: str
    active_observation_id: str | None
    active_decoded_terminal_id: str | None
    identity_state: str
    identity_confidence: float
    frame_sync_state: str
    last_sequence_number: int | None
    acquisition_state: str
    tracking_state: str
    reacquisition_state: str
    candidate_count: int
    active_candidate_count: int
    rejected_candidate_count: int
    candidates: list[CandidateTelemetry]
```

---

## 7. `local_terminal/reacquisition.py`

### `can_merge_reacquisition`

```python
def can_merge_reacquisition(
    old_track: CandidateTrack,
    new_candidate: CandidateTrack,
    reacquisition_spatial_gate_px: float,
) -> bool:
    """
    Returns True if new_candidate is a valid reacquisition of old_track.

    All five conditions must hold:
    1. old_track.decoded_terminal_id is not None
    2. new_candidate.identity_matched is True
    3. old_track.decoded_terminal_id == new_candidate.decoded_terminal_id
    4. new_candidate.last_valid_sequence > old_track.last_valid_sequence
    5. distance(new_candidate.position, old_track.predicted_position) <= gate

    Returns False if any condition fails.
    """
```

### `ReacquisitionResult`

```python
@dataclass
class ReacquisitionResult:
    success: bool
    searching: bool = False
    timed_out: bool = False
    merged_candidate: CandidateTrack | None = None
    current_stage: int = 0
    stage_radius_deg: float = 0.0
```

---

## 8. `local_terminal/config.py`

### `LocalTerminalConfig`

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
    vignetting:    float

    def validate(self, scene_bounds=(2000, 2000)) -> LocalTerminalConfig: ...
    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> LocalTerminalConfig: ...
```

### `TargetPayloadConfig`

```python
@dataclass
class TargetPayloadConfig:
    expected_terminal_id: str = "RT-001"
    expected_token: str = "ALPHA-7"
    expected_wavelength_nm: float = 1550.0
    wavelength_tolerance_nm: float = 20.0
    expected_protocol_version: int = 1
    expected_message_type: int = 1
    chip_rate_hz: float = 12.0
    min_decode_confidence: float = 0.40
    min_consecutive_valid: int = 3
    required_valid_frames: int = 3
    require_sequence_advance: bool = True
    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = True
    max_sequence_gap: int = 0
    identity_timeout_s: float = 5.0
    max_identity_fail_streak: int = 10
    legacy_optical_identification_enabled: bool = False

    def validate(self) -> TargetPayloadConfig: ...

    @classmethod
    def from_dict(cls, data: dict) -> TargetPayloadConfig: ...

    @classmethod
    def from_detection_config(cls, cfg: DetectionConfig) -> TargetPayloadConfig:
        """Construct from legacy DetectionConfig for backward compatibility."""
```

---

## 9. `simulation/headless.py`

### `HeadlessSimulation`

```python
class HeadlessSimulation:
    def __init__(self, config: SimulationConfig): ...

    def run(
        self,
        duration_s: float,
        callback: Callable[[float, LocalTerminalOutput], None] | None = None,
    ) -> SimulationResult:
        """
        Run the simulation for duration_s seconds.
        callback(t, output) called every frame if provided.
        """

    def run_until(
        self,
        condition: Callable[[LocalTerminalOutput], bool],
        timeout_s: float = 300.0,
        callback: Callable[[float, LocalTerminalOutput], None] | None = None,
    ) -> SimulationResult:
        """
        Run until condition(output) returns True or timeout_s elapses.
        result.success = True if condition was met.
        """

    def run_for(self, s: float) -> None:
        """Run for exactly s seconds."""

    @property
    def local_terminal(self) -> LocalTerminal: ...

    @property
    def scenario(self) -> Scenario: ...
```

### `SimulationResult`

```python
@dataclass
class SimulationResult:
    success: bool
    final_state: str
    elapsed_s: float
    frame_count: int
    active_candidate: CandidateTrack | None
    final_telemetry: SystemTelemetry
```
