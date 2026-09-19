# local_terminal/models.py - Pipeline data contracts per Plan.md §§2,3,6-9,13-15,18-20,29,30.
#
# Architectural rule: the Local Terminal only ever receives CameraFrame +
# PTZ pose/velocity + local configuration. It must NEVER receive remote
# position/velocity/ID/beaconState/signature/world coordinates.
#
# Phase-2 additions: BeamProfile, SignalState, DecodedFrameSummary,
# IdentityDecisionSummary embedded in CandidateTrack.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from local_terminal.core.states import CandidateState, LocalTerminalState
from local_terminal.signal.beacon_frame import (
    BeaconDecodeResult,
    BeaconFrame,
    DecodedPayload,
)
from local_terminal.signal.signal_analyzer import (
    OpticalMeasurement,
    SignalMeasurement,
)
from local_terminal.signal.identity_matcher import (
    IdentityDecision,
    TargetPayloadConfig,
    TargetProfile,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf guard (§36)
        return float(default)
    return out


# ---------------------------------------------------------------------
# §2 Primary input
# ---------------------------------------------------------------------
@dataclass
class CameraFrame:
    frame_id: int = 0
    timestamp: float = 0.0
    width: int = 0
    height: int = 0
    image: np.ndarray | None = None  # HxWx3 uint8 (monochrome rendered as tinted gray)
    exposure: float = 1.0
    gain: float = 1.0

    @classmethod
    def from_image(cls, image: np.ndarray | None, frame_id: int = 0,
                   timestamp: float = 0.0, exposure: float = 1.0,
                   gain: float = 1.0) -> CameraFrame:
        if image is None:
            return cls(frame_id=int(frame_id), timestamp=float(timestamp),
                       width=0, height=0, image=None, exposure=exposure, gain=gain)
        arr = np.asarray(image)
        h, w = (arr.shape[0], arr.shape[1]) if arr.ndim >= 2 else (0, 0)
        return cls(frame_id=int(frame_id), timestamp=float(timestamp),
                   width=int(w), height=int(h), image=arr,
                   exposure=float(exposure), gain=float(gain))

    def valid(self) -> bool:
        return (self.image is not None and self.width > 0 and self.height > 0
                and getattr(self.image, "size", 0) > 0)


# ---------------------------------------------------------------------
# §6 Frame processor output
# ---------------------------------------------------------------------
@dataclass
class ProcessedFrame:
    timestamp: float = 0.0
    raw_image: np.ndarray | None = None
    background_estimate: float = 0.0
    processed_image: np.ndarray | None = None  # float32 gray, bg-subtracted
    noise_estimate: float = 1.0


# ---------------------------------------------------------------------
# §8 Spectral / §9 Temporal observations
# ---------------------------------------------------------------------
@dataclass
class SpectralObservation:
    sensor_response: tuple[float, float, float] = (0.0, 0.0, 0.0)
    estimated_spectral_class: float = 1550.0  # nm class estimate
    estimated_center: float = 1550.0
    confidence: float = 0.0
    bandwidth_estimate: float = 10.0


@dataclass
class TemporalObservation:
    timestamps: list[float] = field(default_factory=list)
    intensity_history: list[float] = field(default_factory=list)
    centroid_history: list[tuple[float, float]] = field(default_factory=list)
    estimated_frequency: float = 0.0  # Hz carrier estimate
    frequency_confidence: float = 0.0
    pulse_width: float = 0.0
    repetition_rate: float = 0.0
    modulation_confidence: float = 0.0


# ---------------------------------------------------------------------
# §7 Detection candidate (NOT a target — just C1, C2, ... measurement)
# ---------------------------------------------------------------------
@dataclass
class DetectionCandidate:
    candidate_measurement_id: str = ""  # e.g. M-12 (per-frame measurement)
    centroid_x: float = 0.0
    centroid_y: float = 0.0
    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    area: float = 0.0
    peak_intensity: float = 0.0
    integrated_intensity: float = 0.0
    background_intensity: float = 0.0
    local_snr: float = 0.0  # dB
    apparent_diameter: float = 0.0  # px
    shape_metrics: dict[str, Any] = field(default_factory=dict)
    spectral_observation: SpectralObservation = field(default_factory=SpectralObservation)
    timestamp: float = 0.0


# ---------------------------------------------------------------------
# §14 Local identification signature (receiver configuration, never
# fetched from a RemoteTerminal object during perception)
# ---------------------------------------------------------------------
@dataclass
class TargetIdentificationSignature:
    spectral_center_nm: float = 1550.0
    spectral_tolerance_nm: float = 10.0
    spectral_weight: float = 0.30
    temporal_type: str = "AM"
    temporal_freq_khz: float = 10.0
    temporal_freq_tol_khz: float = 3.0
    temporal_weight: float = 0.25
    expected_spot_mrad: float = 3.0
    expected_spot_tol_mrad: float = 1.5
    spatial_weight: float = 0.20
    identification_code: str = ""
    code_chip_rate_hz: float = 8.0
    code_threshold: float = 0.75
    code_weight: float = 0.15
    minimum_snr_db: float = 8.0
    quality_weight: float = 0.10
    minimum_score: float = 0.85
    minimum_confirmations: int = 3

    @classmethod
    def from_detection_config(cls, cfg: Any) -> TargetIdentificationSignature:
        try:
            return cls(
                spectral_center_nm=_safe_float(getattr(cfg, "wavelength", 1550.0), 1550.0),
                spectral_tolerance_nm=_safe_float(getattr(cfg, "bandwidth", 10.0), 10.0),
                temporal_type=str(getattr(cfg, "modulation_type", "AM") or "AM").upper(),
                temporal_freq_khz=_safe_float(getattr(cfg, "modulation_frequency", 10.0), 10.0),
                expected_spot_mrad=_safe_float(getattr(cfg, "expected_spot_size", 3.0), 3.0),
                expected_spot_tol_mrad=_safe_float(getattr(cfg, "expected_spot_tolerance", 1.5), 1.5),
                identification_code=str(getattr(cfg, "identification_code", "") or ""),
                code_chip_rate_hz=_safe_float(getattr(cfg, "identification_code_chip_rate_hz", 8.0), 8.0),
                code_threshold=_safe_float(getattr(cfg, "code_correlation_threshold", 0.75), 0.75),
                minimum_snr_db=_safe_float(getattr(cfg, "minimum_snr", 8.0), 8.0),
                minimum_score=_safe_float(getattr(cfg, "confidence_threshold", 0.85), 0.85),
                minimum_confirmations=int(getattr(cfg, "code_persistence", 2) or 2),
            )
        except Exception:
            return cls()

    def overall(self, spectral: float, temporal: float, spatial: float,
                code: float | None, quality: float) -> float:
        code_v = 1.0 if code is None and not self.identification_code else (code if code is not None else 0.0)
        total_w = (self.spectral_weight + self.temporal_weight + self.spatial_weight
                   + self.code_weight + self.quality_weight)
        total_w = total_w if total_w > 1e-9 else 1.0
        return float((self.spectral_weight * spectral + self.temporal_weight * temporal
                      + self.spatial_weight * spatial + self.code_weight * code_v
                      + self.quality_weight * quality) / total_w)


@dataclass
class SignatureScores:
    spectral_score: float = 0.0
    temporal_score: float = 0.0
    spatial_score: float = 0.0
    code_score: float | None = None
    quality_score: float = 0.0
    overall_score: float = 0.0


# ---------------------------------------------------------------------
# Phase-2: Beam + Signal + Identity data contracts (image-only boundary preserved)
# ---------------------------------------------------------------------
@dataclass
class BeamProfile:
    """Optical characterisation of a candidate beacon from image measurements."""
    wavelength_nm:    float = 0.0   # estimated wavelength (nm)
    power_dn:         float = 0.0   # integrated peak DN in the spot aperture
    spot_mrad:        float = 0.0   # spot angular diameter in mrad
    modulation_depth: float = 0.0   # (peak-floor)/peak ratio [0..1]
    mod_freq_hz:      float = 0.0   # estimated video-rate modulation freq (Hz)
    snr_db:           float = 0.0   # local SNR at the spot (dB)


@dataclass
class SignalState:
    """Communication-path state for a candidate track."""
    # High-level decode state
    state: str = "IDLE"             # IDLE | SAMPLING | SYNCED | DECODING | VALID | LOST
    chip_rate_hz: float = 0.0
    modulation_depth: float = 0.0
    chip_snr_db: float = 0.0
    bit_error_estimate: float = 1.0
    num_chip_samples: int = 0
    # Latest frame (from FrameDecoder)
    frame_valid: bool = False
    decoded_terminal_id_byte: int = 0
    decoded_network_id: int = 0
    decoded_sequence: int = -1
    decoded_capabilities: int = 0
    decode_confidence: float = 0.0
    consecutive_valid: int = 0
    total_attempts: int = 0
    total_successes: int = 0
    # Identity decision (from IdentityMatcher)
    identity_matched: bool = False
    identity_reason: str = "NO_DATA"   # OK | ID_MISMATCH | NET_MISMATCH | REPLAY | LOW_CONF | CRC_FAIL | NO_DATA
    identity_confidence: float = 0.0
    # Continuous-tracking identity check
    identity_fail_streak: int = 0   # consecutive frames where matched dropped to False during TRACKING


# ---------------------------------------------------------------------
# §13 Candidate track data model (local BEACON-N identity only)
# ---------------------------------------------------------------------
# Optical consistency score alias (§16)
OpticalConsistencyScore = SignatureScores


@dataclass
class CandidateTrack:
    observation_id: str = ""  # BEACON-N, local only — never an RT- ID
    lifecycle_state: CandidateState = CandidateState.SEEN
    first_seen_timestamp: float = 0.0
    last_seen_timestamp: float = 0.0
    age: float = 0.0
    hit_count: int = 0
    miss_count: int = 0
    # measurement (latest, pixels/DN/dB)
    meas_x: float = 0.0
    meas_y: float = 0.0
    meas_intensity: float = 0.0
    meas_snr: float = 0.0
    meas_spot_px: float = 0.0
    meas_wavelength_nm: float = 0.0
    wavelength_confidence: float = 0.0
    meas_modulation_depth: float = 0.0
    temporal_match_score: float = 0.0
    # state estimate (pixels + velocity/accel)
    est_x: float = 0.0
    est_y: float = 0.0
    est_vx: float = 0.0
    est_vy: float = 0.0
    est_ax: float = 0.0
    est_ay: float = 0.0
    uncertainty: float = 1.0
    feature_history: list[dict[str, Any]] = field(default_factory=list)
    signature: SignatureScores = field(default_factory=SignatureScores)
    temporal: TemporalObservation = field(default_factory=TemporalObservation)
    confidence: float = 0.0
    confirm_count: int = 0  # consecutive signature confirmations
    timestamps: list[float] = field(default_factory=list)
    # ── Upgrade.md §27: structured pipeline fields ─────────────────────────
    optical_measurement: OpticalMeasurement = field(default_factory=OpticalMeasurement)
    signal_measurement: SignalMeasurement = field(default_factory=SignalMeasurement)
    synchronization_state: dict[str, Any] = field(default_factory=dict)
    decode_state: str = "IDLE"
    latest_frame: BeaconFrame | None = None
    decoded_terminal_id: str = ""
    decoded_token: str = ""
    decoded_wavelength_nm: float = 0.0
    sequence_number: int = -1
    identity_state: str = "UNKNOWN"
    identity_confidence: float = 0.0
    valid_frame_count: int = 0
    invalid_frame_count: int = 0
    last_valid_frame_time: float = 0.0
    last_valid_sequence: int = -1
    filtered_position: tuple[float, float] = (0.0, 0.0)
    predicted_position: tuple[float, float] = (0.0, 0.0)
    velocity: tuple[float, float] = (0.0, 0.0)
    acceleration: tuple[float, float] = (0.0, 0.0)
    optical_quality: float = 0.0
    signal_quality: float = 0.0
    # ── Backward compatibility communication path ──────────────────────────
    beam_profile: BeamProfile = field(default_factory=BeamProfile)
    signal_state: SignalState = field(default_factory=SignalState)
    # Cached FrameDecoder + IdentityMatcher outputs (set by system.py)
    _decoded_frame: Any = field(default=None, repr=False, compare=False)
    _identity_decision: Any = field(default=None, repr=False, compare=False)

    def touch(self, ts: float) -> None:
        ts = float(ts)
        if self.hit_count == 0:
            self.first_seen_timestamp = ts
        self.last_seen_timestamp = ts
        self.age = max(0.0, ts - self.first_seen_timestamp)

    @property
    def identity_matched(self) -> bool:
        """Shortcut: True when the identity path confirmed this track."""
        return bool(self.signal_state.identity_matched)

    @identity_matched.setter
    def identity_matched(self, val: bool) -> None:
        self.signal_state.identity_matched = bool(val)

    @property
    def is_impostor(self) -> bool:
        """Decoded a valid frame but ID or network does not match profile."""
        return (self.signal_state.identity_reason in ("ID_MISMATCH", "NET_MISMATCH", "WRONG_TERMINAL", "WRONG_TOKEN")
                or bool(getattr(self.signal_state, "is_impostor", False)))

    @is_impostor.setter
    def is_impostor(self, val: bool) -> None:
        self.signal_state.is_impostor = bool(val)
        if val:
            self.signal_state.identity_reason = "ID_MISMATCH"


# ---------------------------------------------------------------------
# Commands / results
# ---------------------------------------------------------------------
@dataclass
class SearchCommand:
    desired_pan: float = 0.0  # deg offset from home
    desired_tilt: float = 0.0
    desired_pan_velocity: float = 0.0
    desired_tilt_velocity: float = 0.0


@dataclass
class PTZCommand:
    target_pan: float = 0.0  # absolute px pose request
    target_tilt: float = 0.0
    pan_velocity: float = 0.0  # px/s feed-forward
    tilt_velocity: float = 0.0


@dataclass
class AcquisitionResult:
    acquired: bool = False
    observation_id: str | None = None
    confidence: float = 0.0
    timestamp: float = 0.0


# ---------------------------------------------------------------------
# §19 Track state estimation (measured / filtered / predicted distinct)
# ---------------------------------------------------------------------
@dataclass
class TargetState:
    valid: bool = False
    observation_id: str | None = None
    measured_x: float = 0.0
    measured_y: float = 0.0
    filtered_x: float = 0.0
    filtered_y: float = 0.0
    predicted_x: float = 0.0
    predicted_y: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    acceleration_x: float = 0.0
    acceleration_y: float = 0.0
    confidence: float = 0.0
    snr: float = 0.0
    signature_score: float = 0.0
    centroid_x: float = 0.0  # alias of filtered_x for Plan §3 compat
    centroid_y: float = 0.0
    timestamp: float = 0.0


@dataclass
class TrackingStatus:
    target_visible: bool = False
    target_identified: bool = False
    target_acquired: bool = False
    target_centered: bool = False
    confidence: float = 0.0
    snr: float = 0.0
    tracking_error_x: float = 0.0
    tracking_error_y: float = 0.0
    state: LocalTerminalState = LocalTerminalState.SEARCHING


# ---------------------------------------------------------------------
# §29 main input / §30 main output (strict no-cheat boundary)
# ---------------------------------------------------------------------
@dataclass
class UpdateInput:
    timestamp: float = 0.0
    delta_time: float = 0.033
    camera_frame: CameraFrame | None = None
    current_ptz_pose: tuple[float, float] = (0.0, 0.0)  # (pan, tilt) px
    current_ptz_velocity: tuple[float, float] = (0.0, 0.0)
    local_configuration: Any = None  # LocalTerminalConfig


@dataclass
class UpdateOutput:
    local_terminal_state: LocalTerminalState = LocalTerminalState.SEARCHING
    search_command: SearchCommand | None = None
    candidate_tracks: list[CandidateTrack] = field(default_factory=list)
    active_observation_id: str | None = None
    target_state: TargetState = field(default_factory=TargetState)
    ptz_command: PTZCommand | None = None
    tracking_status: TrackingStatus = field(default_factory=TrackingStatus)
    telemetry: dict[str, Any] = field(default_factory=dict)
