# local_terminal/config.py - Local Terminal data models and validation per LocalTerminal.md
from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any


def _filter_dataclass_fields(cls: Any, data: dict[str, Any] | None) -> dict[str, Any]:
    """Extract valid fields from dict, supporting camelCase and ignoring extra keys."""
    if not isinstance(data, dict):
        return {}
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    cleaned = {}
    for k, v in data.items():
        if k in valid_fields:
            cleaned[k] = v
        else:
            snake_k = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
            if snake_k in valid_fields:
                cleaned[snake_k] = v
    return cleaned


# =====================================================================
# 1. IDENTITY CONFIG
# =====================================================================
@dataclass
class IdentityConfig:
    """Identity and platform association for the Local Terminal."""
    id: str = "LT-001"
    name: str = "Local PTZ Camera 01"
    type: str = "LOCAL_OPTICAL_TERMINAL"
    platform_id: str = "PLATFORM-001"

    def validate(self) -> IdentityConfig:
        self.id = str(self.id or "LT-001").strip()
        self.name = str(self.name or "Local PTZ Camera 01").strip()
        self.type = str(self.type or "LOCAL_OPTICAL_TERMINAL").strip()
        self.platform_id = str(self.platform_id or "PLATFORM-001").strip()
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IdentityConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 2. RUNTIME STATE CONFIG
# =====================================================================
@dataclass
class LocalStateConfig:
    """Runtime operational and link states (monitored/derived, not user config)."""
    operational_state: str = "STANDBY"   # OFF | INITIALIZING | STANDBY | ACTIVE | FAULT
    power_state: str = "ON"             # OFF | ON
    ptz_state: str = "IDLE"             # IDLE | MOVING | AT_POSITION | LIMIT_REACHED | FAULT
    acquisition_state: str = "IDLE"     # IDLE | SEARCHING | ACQUIRING | ACQUIRED
    detection_state: str = "NO_TARGET"  # NO_TARGET | DETECTING | DISCRIMINATING | TARGET_CONFIRMED
    tracking_state: str = "OFF"         # OFF | TRACKING | LOST | REACQUIRING
    link_state: str = "NO_LINK"         # NO_LINK | OPTICAL_LOCK | HANDSHAKE | CONNECTED

    def validate(self) -> LocalStateConfig:
        valid_ops = {"OFF", "INITIALIZING", "STANDBY", "ACTIVE", "FAULT"}
        valid_pws = {"OFF", "ON"}
        valid_ptz = {"IDLE", "MOVING", "AT_POSITION", "LIMIT_REACHED", "FAULT"}
        valid_acq = {"IDLE", "SEARCHING", "ACQUIRING", "ACQUIRED"}
        valid_det = {"NO_TARGET", "DETECTING", "DISCRIMINATING", "TARGET_CONFIRMED"}
        valid_trk = {"OFF", "TRACKING", "LOST", "REACQUIRING"}
        valid_lnk = {"NO_LINK", "OPTICAL_LOCK", "HANDSHAKE", "CONNECTED"}

        if self.operational_state not in valid_ops:
            self.operational_state = "STANDBY"
        if self.power_state not in valid_pws:
            self.power_state = "ON"
        if self.ptz_state not in valid_ptz:
            self.ptz_state = "IDLE"
        if self.acquisition_state not in valid_acq:
            self.acquisition_state = "IDLE"
        if self.detection_state not in valid_det:
            self.detection_state = "NO_TARGET"
        if self.tracking_state not in valid_trk:
            self.tracking_state = "OFF"
        if self.link_state not in valid_lnk:
            self.link_state = "NO_LINK"
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LocalStateConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 3. POSITION CONFIG
# =====================================================================
@dataclass
class PositionConfig:
    """Physical platform location (2D)."""
    x: float = 0.0
    y: float = 0.0

    def validate(self) -> PositionConfig:
        self.x = float(self.x if self.x is not None else 0.0)
        self.y = float(self.y if self.y is not None else 0.0)
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PositionConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 4. PTZ CAMERA CONFIG
# =====================================================================
@dataclass
class PTZCameraConfig:
    """PTZ Camera Configuration (2D)."""
    resolution_width: int = 640
    resolution_height: int = 480
    fov_x: float = 4.0  # degrees
    fov_y: float = 3.0  # degrees
    pan_speed: float = 8.0   # deg/s
    tilt_speed: float = 8.0  # deg/s
    pan_min: float = 0.0
    pan_max: float = 0.0
    tilt_min: float = 0.0
    tilt_max: float = 0.0
    home_pan: float = 1000.0 # px
    home_tilt: float = 1000.0 # px
    resolution: float = 0.10  # actuator quantization step (px)
    latency: int = 12         # command queue delay (ms)
    update_rate: int = 30     # actuator refresh frequency (Hz)

    def validate(self, scene_bounds: tuple[int, int] = (2000, 2000)) -> PTZCameraConfig:
        sw, sh = scene_bounds
        self.resolution_width = int(max(20, min(self.resolution_width if self.resolution_width is not None else 640, max(sw, 5000))))
        self.resolution_height = int(max(20, min(self.resolution_height if self.resolution_height is not None else 480, max(sh, 5000))))
        self.fov_x = float(max(0.5, min(self.fov_x if self.fov_x is not None else 4.0, 30.0)))
        self.fov_y = float(max(0.5, min(self.fov_y if self.fov_y is not None else 3.0, 30.0)))
        
        self.pan_min = float(self.pan_min if self.pan_min is not None else 0.0)
        self.pan_max = float(self.pan_max if self.pan_max is not None else 0.0)
        self.tilt_min = float(self.tilt_min if self.tilt_min is not None else 0.0)
        self.tilt_max = float(self.tilt_max if self.tilt_max is not None else 0.0)

        if self.home_pan is None or self.home_pan <= 0.0 or self.home_pan > sw:
            self.home_pan = float(sw / 2.0)
        if self.home_tilt is None or self.home_tilt <= 0.0 or self.home_tilt > sh:
            self.home_tilt = float(sh / 2.0)

        self.pan_speed = float(max(1.0, min(self.pan_speed if self.pan_speed is not None else 8.0, 60.0)))
        self.tilt_speed = float(max(1.0, min(self.tilt_speed if self.tilt_speed is not None else 8.0, 60.0)))
        self.resolution = float(max(0.0, min(self.resolution if self.resolution is not None else 0.10, 10.0)))
        self.latency = int(max(0, min(self.latency if self.latency is not None else 12, 2000)))
        self.update_rate = int(max(1, min(self.update_rate if self.update_rate is not None else 30, 1000)))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PTZCameraConfig:
        if isinstance(data, dict):
            d = dict(data)
            # handle nested dicts from legacy
            if "resolution" in d and isinstance(d["resolution"], dict):
                if "width" in d["resolution"]: d["resolution_width"] = d["resolution"]["width"]
                if "height" in d["resolution"]: d["resolution_height"] = d["resolution"]["height"]
            if "fieldOfView" in d and isinstance(d["fieldOfView"], dict):
                if "x" in d["fieldOfView"]: d["fov_x"] = d["fieldOfView"]["x"]
                if "y" in d["fieldOfView"]: d["fov_y"] = d["fieldOfView"]["y"]
            if "pan" in d and isinstance(d["pan"], dict):
                if "min" in d["pan"]: d["pan_min"] = d["pan"]["min"]
                if "max" in d["pan"]: d["pan_max"] = d["pan"]["max"]
                if "home" in d["pan"]: d["home_pan"] = d["pan"]["home"]
                if "speed" in d["pan"]: d["pan_speed"] = d["pan"]["speed"]
            if "tilt" in d and isinstance(d["tilt"], dict):
                if "min" in d["tilt"]: d["tilt_min"] = d["tilt"]["min"]
                if "max" in d["tilt"]: d["tilt_max"] = d["tilt"]["max"]
                if "home" in d["tilt"]: d["home_tilt"] = d["tilt"]["home"]
                if "speed" in d["tilt"]: d["tilt_speed"] = d["tilt"]["speed"]
            return cls(**_filter_dataclass_fields(cls, d)).validate()
        return cls().validate()


# =====================================================================
# 6. DISPLAY CONFIG
# =====================================================================
@dataclass
class DisplayConfig:
    """Display screens, god view canvas, and world size."""
    camera_screen_width: int = 2000
    camera_screen_height: int = 2000
    god_view_width: int = 2000
    god_view_height: int = 2000
    world_size: float = 2000.0

    def validate(self, scene_bounds: tuple[int, int] = (2000, 2000)) -> DisplayConfig:
        sw, sh = scene_bounds
        self.camera_screen_width = int(max(500, min(self.camera_screen_width if self.camera_screen_width is not None else 2000, 10000)))
        self.camera_screen_height = int(max(500, min(self.camera_screen_height if self.camera_screen_height is not None else 2000, 10000)))
        self.god_view_width = int(sw)
        self.god_view_height = int(sh)
        self.world_size = float(max(sw, sh))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DisplayConfig:
        if isinstance(data, dict):
            d = dict(data)
            cs = d.get("cameraScreen") or d.get("camera_screen")
            if isinstance(cs, dict):
                if "width" in cs: d["camera_screen_width"] = cs["width"]
                if "height" in cs: d["camera_screen_height"] = cs["height"]
            gv = d.get("godView") or d.get("god_view")
            if isinstance(gv, dict):
                if "width" in gv: d["god_view_width"] = gv["width"]
                if "height" in gv: d["god_view_height"] = gv["height"]
            if "worldSize" in d:
                d["world_size"] = d["worldSize"]
            return cls(**_filter_dataclass_fields(cls, d)).validate()
        return cls().validate()


# =====================================================================
# 7. ANGULAR MODEL CONFIG (DERIVED)
# =====================================================================
@dataclass
class AngularModelConfig:
    """
    Derived physical angular model calculated directly from FOV and Sensor Resolution.
    Not arbitrary: 4.0 deg / 640 px = 109.083 urad/px.
    """
    pixel_to_angle_x: float = 109.083  # urad/pixel
    pixel_to_angle_y: float = 109.083  # urad/pixel
    angle_to_pixel_x: float = 0.009167 # pixel/urad
    angle_to_pixel_y: float = 0.009167 # pixel/urad
    unit: str = "urad_per_pixel"

    def recalculate(self, fov_x_deg: float, fov_y_deg: float, width_px: int, height_px: int) -> AngularModelConfig:
        """Derive exact pixel-to-angle parameters from optics geometry."""
        w = max(1, int(width_px))
        h = max(1, int(height_px))
        # FOV (deg) -> radians -> microradians
        x_urad_total = math.radians(float(fov_x_deg)) * 1e6
        y_urad_total = math.radians(float(fov_y_deg)) * 1e6

        self.pixel_to_angle_x = float(x_urad_total / w)
        self.pixel_to_angle_y = float(y_urad_total / h)
        self.angle_to_pixel_x = float(1.0 / self.pixel_to_angle_x if self.pixel_to_angle_x > 0 else 0.0)
        self.angle_to_pixel_y = float(1.0 / self.pixel_to_angle_y if self.pixel_to_angle_y > 0 else 0.0)
        self.unit = "urad_per_pixel"
        return self

    def validate(self) -> AngularModelConfig:
        self.pixel_to_angle_x = float(max(1e-4, self.pixel_to_angle_x))
        self.pixel_to_angle_y = float(max(1e-4, self.pixel_to_angle_y))
        self.angle_to_pixel_x = float(1.0 / self.pixel_to_angle_x)
        self.angle_to_pixel_y = float(1.0 / self.pixel_to_angle_y)
        self.unit = "urad_per_pixel"
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AngularModelConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 8. REALISM / MECHANICAL ERRORS CONFIG
# =====================================================================
@dataclass
class RealismConfig:
    """Mechanical imperfection models: acceleration, backlash, encoder noise, latency jitter."""
    max_acceleration: float = 20.0  # deg/s^2
    backlash: float = 0.25          # px
    encoder_sigma: float = 0.040    # px
    latency_jitter: float = 1.2     # ms

    def validate(self) -> RealismConfig:
        self.max_acceleration = float(max(0.1, min(self.max_acceleration, 500.0)))
        self.backlash = float(max(0.0, min(self.backlash, 10.0)))
        self.encoder_sigma = float(max(0.0, min(self.encoder_sigma, 2.0)))
        self.latency_jitter = float(max(0.0, min(self.latency_jitter, 100.0)))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RealismConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 9. ACQUISITION CONFIG
# =====================================================================
def normalize_search_pattern(pattern: object) -> str:
    """Canonicalize acquisition pattern names incl. common aliases.

    Figure-8: "FIGURE-8" | "FIGURE 8" | "FIG8" -> "FIGURE_8".
    """
    p = str(pattern or "").strip()
    if p.upper().replace("-", "_").replace(" ", "_") in ("FIGURE_8", "FIG8"):
        return "FIGURE_8"
    for canonical in ("RANDOM", "RASTER", "SPIRAL", "SECTOR", "GRID", "CUSTOM", "FIGURE_8"):
        if p.upper() == canonical:
            return canonical
    return p


@dataclass
class AcquisitionConfig:
    """Target search mode, scanning patterns, search boundaries, and speed."""
    mode: str = "AUTO"                    # MANUAL | SEARCH | AUTO | AUTO_ACQUISITION | TARGET_POINTING
    search_pattern: str = "RANDOM"        # RANDOM | RASTER | SPIRAL | SECTOR | GRID | CUSTOM | FIGURE_8
    search_region_pan_min: float = -20.0  # deg
    search_region_pan_max: float = 20.0   # deg
    search_region_tilt_min: float = -10.0 # deg
    search_region_tilt_max: float = 10.0  # deg
    search_speed: float = 15.0            # deg/s
    timeout: float = 30.0                 # s
    reacquisition_timeout: float = 1.5    # s — REACQ coast budget before LOST

    def validate(self) -> AcquisitionConfig:
        modes = {"MANUAL", "SEARCH", "AUTO", "AUTO_ACQUISITION", "TARGET_POINTING"}
        patterns = {"RANDOM", "RASTER", "SPIRAL", "SECTOR", "GRID", "CUSTOM", "FIGURE_8"}
        if self.mode not in modes:
            self.mode = "AUTO"
        self.search_pattern = normalize_search_pattern(self.search_pattern)
        if self.search_pattern not in patterns:
            self.search_pattern = "RANDOM"
        self.search_region_pan_min = float(self.search_region_pan_min)
        self.search_region_pan_max = float(self.search_region_pan_max)
        if self.search_region_pan_min > self.search_region_pan_max:
            self.search_region_pan_min, self.search_region_pan_max = self.search_region_pan_max, self.search_region_pan_min
        self.search_region_tilt_min = float(self.search_region_tilt_min)
        self.search_region_tilt_max = float(self.search_region_tilt_max)
        if self.search_region_tilt_min > self.search_region_tilt_max:
            self.search_region_tilt_min, self.search_region_tilt_max = self.search_region_tilt_max, self.search_region_tilt_min
        self.search_speed = float(max(0.1, min(self.search_speed, 60.0)))
        self.timeout = float(max(1.0, min(self.timeout, 300.0)))
        self.reacquisition_timeout = float(max(0.5, min(float(self.reacquisition_timeout or 1.5), 30.0)))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AcquisitionConfig:
        if isinstance(data, dict):
            d = dict(data)
            sr = d.get("searchRegion") or d.get("search_region")
            if isinstance(sr, dict):
                if "panMin" in sr: d["search_region_pan_min"] = sr["panMin"]
                if "pan_min" in sr: d["search_region_pan_min"] = sr["pan_min"]
                if "panMax" in sr: d["search_region_pan_max"] = sr["panMax"]
                if "pan_max" in sr: d["search_region_pan_max"] = sr["pan_max"]
                if "tiltMin" in sr: d["search_region_tilt_min"] = sr["tiltMin"]
                if "tilt_min" in sr: d["search_region_tilt_min"] = sr["tilt_min"]
                if "tiltMax" in sr: d["search_region_tilt_max"] = sr["tiltMax"]
                if "tilt_max" in sr: d["search_region_tilt_max"] = sr["tilt_max"]
            return cls(**_filter_dataclass_fields(cls, d)).validate()
        return cls().validate()


# =====================================================================
# 10. DETECTION CONFIG
# =====================================================================
@dataclass
class DetectionConfig:
    """Optical detection parameters."""
    wavelength: float = 1550.0            # nm
    bandwidth: float = 10.0               # nm
    intensity_threshold: float = 0.0      # DN / power threshold
    minimum_snr: float = 8.0              # dB
    min_detection_area: int = 2           # px — hot-pixel floor (1 = long-range)
    expected_spot_size: float = 1.0       # mrad
    expected_spot_tolerance: float = 1.5  # mrad
    expected_spot_unit: str = "mrad"
    modulation_type: str = "AM"           # AM | OOK | NONE
    modulation_frequency: float = 10.0    # kHz
    modulation_unit: str = "kHz"

    def validate(self) -> DetectionConfig:
        self.wavelength = float(max(400.0, min(self.wavelength, 2000.0)))
        self.bandwidth = float(max(0.1, min(self.bandwidth, 200.0)))
        self.intensity_threshold = float(max(0.0, self.intensity_threshold))
        self.minimum_snr = float(max(0.0, min(self.minimum_snr, 100.0)))
        self.min_detection_area = int(max(1, min(int(self.min_detection_area or 2), 16)))
        self.expected_spot_size = float(max(0.01, min(self.expected_spot_size, 50.0)))
        self.expected_spot_tolerance = float(max(0.0, min(self.expected_spot_tolerance, 20.0)))
        self.expected_spot_unit = str(self.expected_spot_unit or "mrad").strip()
        self.modulation_type = str(self.modulation_type or "AM").strip().upper()
        if self.modulation_type not in {"AM", "OOK", "NONE"}:
            self.modulation_type = "AM"
        self.modulation_frequency = float(max(0.0, min(self.modulation_frequency, 1000.0)))
        self.modulation_unit = str(self.modulation_unit or "kHz").strip()
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DetectionConfig:
        if isinstance(data, dict):
            d = dict(data)
            ss = d.get("expectedSpotSize") or d.get("expected_spot_size")
            if isinstance(ss, dict):
                if "value" in ss: d["expected_spot_size"] = ss["value"]
                if "tolerance" in ss: d["expected_spot_tolerance"] = ss["tolerance"]
                if "unit" in ss: d["expected_spot_unit"] = ss["unit"]
            mod = d.get("modulation")
            if isinstance(mod, dict):
                if "type" in mod: d["modulation_type"] = mod["type"]
                if "frequency" in mod: d["modulation_frequency"] = mod["frequency"]
                if "unit" in mod: d["modulation_unit"] = mod["unit"]
            return cls(**_filter_dataclass_fields(cls, d)).validate()
        return cls().validate()


# =====================================================================
# 10b. TARGET PROFILE (Phase-2 identity configuration)
# =====================================================================
@dataclass
class ReceivingPayloadConfig:
    """Receiving Payload Configuration (matches RT BeaconPayload)."""
    expected_terminal_id: str = "RT-001"
    expected_token: str = "ALPHA-7"
    expected_wavelength_nm: float = 1550.0
    expected_network_id: int = 0
    required_capabilities: int = 0
    expected_protocol_version: int = 1
    expected_message_type: int = 1
    chip_rate_hz: float = 12.0
    min_decode_confidence: float = 0.40
    min_consecutive_valid: int = 3
    
    # Tracking identity retention
    max_sequence_gap: int = 0
    identity_timeout_s: float = 5.0
    max_identity_fail_streak: int = 10
    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = True
    allow_wavelength_override: bool = False

    def validate(self) -> ReceivingPayloadConfig:
        self.expected_terminal_id = str(self.expected_terminal_id or "").strip()
        self.expected_token = str(self.expected_token or "").strip()
        self.expected_wavelength_nm = float(self.expected_wavelength_nm if self.expected_wavelength_nm is not None else 1550.0)
        self.expected_network_id = int(self.expected_network_id or 0)
        self.required_capabilities = int(self.required_capabilities or 0)
        self.expected_protocol_version = int(self.expected_protocol_version if self.expected_protocol_version is not None else 1)
        self.expected_message_type = int(self.expected_message_type if self.expected_message_type is not None else 1)
        self.chip_rate_hz = float(max(0.5, min(float(self.chip_rate_hz or 12.0), 60.0)))
        self.min_decode_confidence = float(max(0.0, min(float(self.min_decode_confidence or 0.4), 1.0)))
        self.min_consecutive_valid = int(max(1, self.min_consecutive_valid or 3))
        self.max_identity_fail_streak = int(max(1, self.max_identity_fail_streak if self.max_identity_fail_streak is not None else 10))
        self.identity_timeout_s = float(max(0.1, float(self.identity_timeout_s or 5.0)))
        self.sequence_validation_enabled = bool(self.sequence_validation_enabled)
        self.wavelength_validation_enabled = bool(self.wavelength_validation_enabled)
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReceivingPayloadConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# 11. TRACKING CONFIG
# =====================================================================
@dataclass
class TrackingConfig:
    """Target tracking loop, estimation algorithm, and prediction filter."""
    mode: str = "AUTO"                    # OFF | TRACKING | AUTO
    algorithm: str = "CENTROID"           # CENTROID | PEAK | KALMAN
    update_rate: int = 30                 # Hz
    prediction: bool = True
    prediction_horizon: float = 0.15      # s (0.5s overshoots with noisy vel estimates)
    smoothing: float = 0.2  # 0..1 EMA factor: LARGER = slower/smoother, smaller = responsive
    lost_target_behavior: str = "RESUME_SEARCH"  # RESUME_SEARCH | HOLD_POSITION | RETURN_HOME
    kp: float = 0.25                      # Proportional gain
    ki: float = 0.05                      # Integral gain
    kd: float = 0.02                      # Derivative gain
    derivative_alpha: float = 0.3         # low-pass alpha for D term (0..1)
    dead_zone: float = 0.5                # px deadband
    output_clamp: float = 500.0           # max correction clamp

    def validate(self) -> TrackingConfig:
        modes = {"OFF", "TRACKING", "AUTO"}
        algos = {"CENTROID", "PEAK", "KALMAN"}
        losts = {"RESUME_SEARCH", "HOLD_POSITION", "RETURN_HOME"}
        if self.mode not in modes:
            self.mode = "AUTO"
        if self.algorithm not in algos:
            self.algorithm = "CENTROID"
        self.update_rate = int(max(1, min(self.update_rate, 240)))
        self.prediction = bool(self.prediction)
        self.prediction_horizon = float(max(0.0, min(self.prediction_horizon, 5.0)))
        self.smoothing = float(max(0.0, min(self.smoothing, 1.0)))
        if self.lost_target_behavior not in losts:
            self.lost_target_behavior = "RESUME_SEARCH"
        self.kp = float(max(0.0, min(self.kp, 10.0)))
        self.ki = float(max(0.0, min(self.ki, 10.0)))
        self.kd = float(max(0.0, min(self.kd, 10.0)))
        self.derivative_alpha = float(max(0.01, min(float(self.derivative_alpha or 0.3), 1.0)))
        self.dead_zone = float(max(0.0, min(self.dead_zone, 50.0)))
        self.output_clamp = float(max(1.0, min(self.output_clamp, 5000.0)))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TrackingConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


# =====================================================================
# TOP-LEVEL LOCAL TERMINAL CONFIG
# =====================================================================
@dataclass
class LocalTerminalConfig:
    """Complete configuration container for the Local Terminal (2D-minimal)."""
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    state: LocalStateConfig = field(default_factory=LocalStateConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    ptz_camera: PTZCameraConfig = field(default_factory=PTZCameraConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    angular_model: AngularModelConfig = field(default_factory=AngularModelConfig)
    realism: RealismConfig = field(default_factory=RealismConfig)
    acquisition: AcquisitionConfig = field(default_factory=AcquisitionConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    receiving_payload: ReceivingPayloadConfig = field(default_factory=ReceivingPayloadConfig)
    vignetting: float = 0.0

    def validate(self, scene_bounds: tuple[int, int] = (2000, 2000)) -> LocalTerminalConfig:
        sw, sh = scene_bounds
        self.identity.validate()
        self.state.validate()
        self.position.validate()
        self.ptz_camera.validate(scene_bounds)
        self.display.validate(scene_bounds)
        self.angular_model.recalculate(
            self.ptz_camera.fov_x, self.ptz_camera.fov_y,
            self.ptz_camera.resolution_width, self.ptz_camera.resolution_height,
        )
        self.realism.validate()
        self.acquisition.validate()
        self.detection.validate()
        self.tracking.validate()
        self.receiving_payload.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LocalTerminalConfig:
        if not isinstance(data, dict):
            return cls().validate()

        root = data.get("localTerminal") or data.get("local_terminal") or data

        cfg = cls()
        if "identity" in root: cfg.identity = IdentityConfig.from_dict(root["identity"])
        if "state" in root: cfg.state = LocalStateConfig.from_dict(root["state"])
        if "position" in root: cfg.position = PositionConfig.from_dict(root["position"])
        
        # Backward compatibility for PTZ and Camera splits
        if "ptz_camera" in root:
            cfg.ptz_camera = PTZCameraConfig.from_dict(root["ptz_camera"])
        else:
            cam_data = root.get("camera", {})
            ptz_data = root.get("ptz", {})
            merged = {**cam_data, **ptz_data}
            if merged: cfg.ptz_camera = PTZCameraConfig.from_dict(merged)
            
        if "display" in root: cfg.display = DisplayConfig.from_dict(root["display"])
        if "angularModel" in root or "angular_model" in root:
            cfg.angular_model = AngularModelConfig.from_dict(root.get("angularModel") or root.get("angular_model"))
        if "realism" in root: cfg.realism = RealismConfig.from_dict(root["realism"])
        if "acquisition" in root: cfg.acquisition = AcquisitionConfig.from_dict(root["acquisition"])
        if "detection" in root: cfg.detection = DetectionConfig.from_dict(root["detection"])
        if "tracking" in root: cfg.tracking = TrackingConfig.from_dict(root["tracking"])
        
        # Backward compat for payload names
        if "receiving_payload" in root:
            cfg.receiving_payload = ReceivingPayloadConfig.from_dict(root["receiving_payload"])
        elif "target_payload" in root or "targetPayload" in root:
            cfg.receiving_payload = ReceivingPayloadConfig.from_dict(root.get("target_payload") or root.get("targetPayload"))
        elif "target_profile" in root or "targetProfile" in root:
            cfg.receiving_payload = ReceivingPayloadConfig.from_dict(root.get("target_profile") or root.get("targetProfile"))

        # Also support legacy flat properties if supplied
        for k in ("fov_width", "fov_height", "pan_min", "pan_max", "tilt_min", "tilt_max",
                  "home_pan", "home_tilt", "max_pan_speed_deg", "max_tilt_speed_deg",
                  "max_slew_rate", "resolution", "latency_ms", "update_rate_hz",
                  "viewport_width", "viewport_height", "god_width", "god_height",
                  "pixel_scale_mrad", "max_accel_deg", "backlash_px", "encoder_sigma_px",
                  "latency_jitter_ms", "vignetting"):
            if k in root:
                try:
                    setattr(cfg, k, root[k])
                except (AttributeError, TypeError, ValueError):
                    pass

        return cfg.validate()

    @property
    def camera(self): return self.ptz_camera
    @camera.setter
    def camera(self, val): self.ptz_camera = val
    @property
    def ptz(self): return self.ptz_camera
    @ptz.setter
    def ptz(self, val): self.ptz_camera = val
    @property
    def target_payload(self): return self.receiving_payload
    @target_payload.setter
    def target_payload(self, val): self.receiving_payload = val
    @property
    def target_profile(self): return self.receiving_payload
    @target_profile.setter
    def target_profile(self, val): self.receiving_payload = val

# --- Convenience flat attribute accessors ---
    @property
    def fov_width(self) -> int:
        return self.ptz_camera.resolution_width

    @fov_width.setter
    def fov_width(self, val: int) -> None:
        self.ptz_camera.resolution_width = int(val)
        self.angular_model.recalculate(self.ptz_camera.fov_x, self.ptz_camera.fov_y, self.ptz_camera.resolution_width, self.ptz_camera.resolution_height)

    @property
    def fov_height(self) -> int:
        return self.ptz_camera.resolution_height

    @fov_height.setter
    def fov_height(self, val: int) -> None:
        self.ptz_camera.resolution_height = int(val)
        self.angular_model.recalculate(self.ptz_camera.fov_x, self.ptz_camera.fov_y, self.ptz_camera.resolution_width, self.ptz_camera.resolution_height)

    @property
    def pan_min(self) -> float:
        return self.ptz_camera.pan_min

    @pan_min.setter
    def pan_min(self, val: float) -> None:
        self.ptz_camera.pan_min = float(val)

    @property
    def pan_max(self) -> float:
        return self.ptz_camera.pan_max

    @pan_max.setter
    def pan_max(self, val: float) -> None:
        self.ptz_camera.pan_max = float(val)

    @property
    def tilt_min(self) -> float:
        return self.ptz_camera.tilt_min

    @tilt_min.setter
    def tilt_min(self, val: float) -> None:
        self.ptz_camera.tilt_min = float(val)

    @property
    def tilt_max(self) -> float:
        return self.ptz_camera.tilt_max

    @tilt_max.setter
    def tilt_max(self, val: float) -> None:
        self.ptz_camera.tilt_max = float(val)

    @property
    def home_pan(self) -> float:
        return self.ptz_camera.home_pan

    @home_pan.setter
    def home_pan(self, val: float) -> None:
        self.ptz_camera.home_pan = float(val)

    @property
    def home_tilt(self) -> float:
        return self.ptz_camera.home_tilt

    @home_tilt.setter
    def home_tilt(self, val: float) -> None:
        self.ptz_camera.home_tilt = float(val)

    @property
    def max_pan_speed_deg(self) -> float:
        return self.ptz_camera.pan_speed

    @max_pan_speed_deg.setter
    def max_pan_speed_deg(self, val: float) -> None:
        self.ptz_camera.pan_speed = float(val)

    @property
    def max_tilt_speed_deg(self) -> float:
        return self.ptz_camera.tilt_speed

    @max_tilt_speed_deg.setter
    def max_tilt_speed_deg(self, val: float) -> None:
        self.ptz_camera.tilt_speed = float(val)

    @property
    def max_slew_rate(self) -> float:
        # Convert deg/s to pixels/s via angular model
        deg_per_px = self.ptz_camera.fov_x / max(1, self.ptz_camera.resolution_width)
        return float(self.ptz_camera.pan_speed / deg_per_px) if deg_per_px > 0 else 800.0

    @max_slew_rate.setter
    def max_slew_rate(self, val: float) -> None:
        deg_per_px = self.ptz_camera.fov_x / max(1, self.ptz_camera.resolution_width)
        if deg_per_px > 0:
            self.ptz_camera.pan_speed = float(val) * deg_per_px

    @property
    def resolution(self) -> float:
        return self.ptz_camera.resolution

    @resolution.setter
    def resolution(self, val: float) -> None:
        self.ptz_camera.resolution = float(val)

    @property
    def latency_ms(self) -> int:
        return self.ptz_camera.latency

    @latency_ms.setter
    def latency_ms(self, val: int) -> None:
        self.ptz_camera.latency = int(val)

    @property
    def update_rate_hz(self) -> int:
        return self.ptz_camera.update_rate

    @update_rate_hz.setter
    def update_rate_hz(self, val: int) -> None:
        self.ptz_camera.update_rate = int(val)

    @property
    def viewport_width(self) -> int:
        return self.display.camera_screen_width

    @viewport_width.setter
    def viewport_width(self, val: int) -> None:
        self.display.camera_screen_width = int(val)

    @property
    def viewport_height(self) -> int:
        return self.display.camera_screen_height

    @viewport_height.setter
    def viewport_height(self, val: int) -> None:
        self.display.camera_screen_height = int(val)

    @property
    def god_width(self) -> int:
        return self.display.god_view_width

    @god_width.setter
    def god_width(self, val: int) -> None:
        self.display.god_view_width = int(val)

    @property
    def god_height(self) -> int:
        return self.display.god_view_height

    @god_height.setter
    def god_height(self, val: int) -> None:
        self.display.god_view_height = int(val)

    @property
    def pixel_scale_mrad(self) -> float:
        # urad/px -> mrad/px
        return float(self.angular_model.pixel_to_angle_x * 0.001)

    @pixel_scale_mrad.setter
    def pixel_scale_mrad(self, val: float) -> None:
        self.angular_model.pixel_to_angle_x = float(val) * 1000.0
        self.angular_model.pixel_to_angle_y = float(val) * 1000.0
        self.angular_model.angle_to_pixel_x = float(1.0 / self.angular_model.pixel_to_angle_x)
        self.angular_model.angle_to_pixel_y = float(1.0 / self.angular_model.pixel_to_angle_y)

    @property
    def max_accel_deg(self) -> float:
        return self.realism.max_acceleration

    @max_accel_deg.setter
    def max_accel_deg(self, val: float) -> None:
        self.realism.max_acceleration = float(val)

    @property
    def backlash_px(self) -> float:
        return self.realism.backlash

    @backlash_px.setter
    def backlash_px(self, val: float) -> None:
        self.realism.backlash = float(val)

    @property
    def encoder_sigma_px(self) -> float:
        return self.realism.encoder_sigma

    @encoder_sigma_px.setter
    def encoder_sigma_px(self, val: float) -> None:
        self.realism.encoder_sigma = float(val)

    @property
    def latency_jitter_ms(self) -> float:
        return self.realism.latency_jitter

    @latency_jitter_ms.setter
    def latency_jitter_ms(self, val: float) -> None:
        self.realism.latency_jitter = float(val)

    @property
    def controller_config(self) -> TrackingConfig:
        """Compatibility property forwarding to tracking configuration."""
        return self.tracking

    @classmethod
    def from_camera_config(cls, cam: Any) -> LocalTerminalConfig:
        cfg = cls()
        if hasattr(cam, "fov_width"): cfg.ptz_camera.resolution_width = int(cam.fov_width)
        if hasattr(cam, "fov_height"): cfg.ptz_camera.resolution_height = int(cam.fov_height)
        if hasattr(cam, "fov_deg_x"): cfg.ptz_camera.fov_x = float(cam.fov_deg_x)
        if hasattr(cam, "fov_deg_y"): cfg.ptz_camera.fov_y = float(cam.fov_deg_y)
        if hasattr(cam, "pan_min") and cam.pan_min is not None: cfg.ptz_camera.pan_min = float(cam.pan_min)
        if hasattr(cam, "pan_max") and cam.pan_max is not None: cfg.ptz_camera.pan_max = float(cam.pan_max)
        if hasattr(cam, "tilt_min") and cam.tilt_min is not None: cfg.ptz_camera.tilt_min = float(cam.tilt_min)
        if hasattr(cam, "tilt_max") and cam.tilt_max is not None: cfg.ptz_camera.tilt_max = float(cam.tilt_max)
        if hasattr(cam, "home_pan") and cam.home_pan is not None: cfg.ptz_camera.home_pan = float(cam.home_pan)
        if hasattr(cam, "home_tilt") and cam.home_tilt is not None: cfg.ptz_camera.home_tilt = float(cam.home_tilt)
        if hasattr(cam, "max_pan_speed_deg"): cfg.ptz_camera.pan_speed = float(cam.max_pan_speed_deg)
        if hasattr(cam, "max_tilt_speed_deg"): cfg.ptz_camera.tilt_speed = float(cam.max_tilt_speed_deg)
        if hasattr(cam, "resolution"): cfg.ptz_camera.resolution = float(cam.resolution)
        if hasattr(cam, "latency_ms"): cfg.ptz_camera.latency = int(cam.latency_ms)
        if hasattr(cam, "update_rate_hz"): cfg.ptz_camera.update_rate = int(cam.update_rate_hz)
        if hasattr(cam, "viewport_width"): cfg.display.camera_screen_width = int(cam.viewport_width)
        if hasattr(cam, "viewport_height"): cfg.display.camera_screen_height = int(cam.viewport_height)
        if hasattr(cam, "god_width"): cfg.display.god_view_width = int(cam.god_width)
        if hasattr(cam, "god_height"): cfg.display.god_view_height = int(cam.god_height)
        if hasattr(cam, "max_accel_deg"): cfg.realism.max_acceleration = float(cam.max_accel_deg)
        if hasattr(cam, "backlash_px"): cfg.realism.backlash = float(cam.backlash_px)
        if hasattr(cam, "encoder_sigma_px"): cfg.realism.encoder_sigma = float(cam.encoder_sigma_px)
        if hasattr(cam, "latency_jitter_ms"): cfg.realism.latency_jitter = float(cam.latency_jitter_ms)
        if hasattr(cam, "vignetting"): cfg.vignetting = float(cam.vignetting)
        return cfg.validate()
# Aliases for backward compatibility
TargetPayloadConfig = ReceivingPayloadConfig
TargetProfile = ReceivingPayloadConfig
LocalCameraConfig = PTZCameraConfig
PTZConfig = PTZCameraConfig
