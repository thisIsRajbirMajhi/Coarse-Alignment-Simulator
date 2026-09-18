# remote_terminal/config.py - Remote Terminal data models and validation per RemoteTerminal.md
from __future__ import annotations

import copy
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


@dataclass
class IdentityConfig:
    """Identity and classification of the remote terminal."""
    id: str = "RT-001"
    name: str = "Remote Optical Terminal 001"
    terminal_type: str = "REMOTE_TERMINAL"  # REMOTE_TERMINAL | OPTICAL_TERMINAL | GROUND_TERMINAL | AIRBORNE_TERMINAL | SPACE_TERMINAL
    platform_id: str = "PLATFORM-001"
    platform_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    platform_orient: tuple[float, float, float] = (0.0, 0.0, 0.0)  # roll, pitch, yaw deg

    def validate(self) -> IdentityConfig:
        self.id = str(self.id or "RT-001").strip()
        self.name = str(self.name or f"Remote Terminal {self.id}").strip()
        self.terminal_type = str(self.terminal_type or "REMOTE_TERMINAL").strip()
        self.platform_id = str(self.platform_id or "PLATFORM-001").strip()
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IdentityConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class StateConfig:
    """Operational and physical state of the remote terminal."""
    operational_state: str = "ACTIVE"  # OFF | INITIALIZING | STANDBY | ACTIVE | FAULT | MAINTENANCE
    power_state: str = "ON"  # OFF | ON | LOW_POWER | FAULT
    beacon_state: str = "EMITTING"  # OFF | READY | EMITTING | FAULT
    communication_state: str = "NO_LINK"  # NO_LINK | DETECTING | OPTICAL_LOCK | HANDSHAKE | CONNECTED | ERROR
    fault: str = "NONE"  # NONE | DEGRADED | HARDWARE_FAULT

    def validate(self) -> StateConfig:
        ops = {"OFF", "INITIALIZING", "STANDBY", "ACTIVE", "FAULT", "MAINTENANCE"}
        pws = {"OFF", "ON", "LOW_POWER", "FAULT"}
        bcs = {"OFF", "READY", "EMITTING", "FAULT"}
        cms = {"NO_LINK", "DETECTING", "OPTICAL_LOCK", "HANDSHAKE", "CONNECTED", "ERROR"}
        if self.operational_state not in ops:
            self.operational_state = "ACTIVE"
        if self.power_state not in pws:
            self.power_state = "ON"
        if self.beacon_state not in bcs:
            self.beacon_state = "EMITTING"
        if self.communication_state not in cms:
            self.communication_state = "NO_LINK"
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StateConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class PositionConfig:
    """Position and orientation in scene/reference frame."""
    x: float = 1000.0
    y: float = 1000.0
    z: float = 0.0
    reference_frame: str = "LOCAL"  # LOCAL | PLATFORM | ECI | ECEF | ENU | NED
    roll: float = 0.0  # deg
    pitch: float = 0.0  # deg
    yaw: float = 0.0  # deg

    def validate(self) -> PositionConfig:
        self.x = float(self.x)
        self.y = float(self.y)
        self.z = float(self.z)
        self.reference_frame = str(self.reference_frame or "LOCAL")
        self.roll = float(self.roll)
        self.pitch = float(self.pitch)
        self.yaw = float(self.yaw) % 360.0
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PositionConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class BeaconConfig:
    """Optical beacon emission characteristics."""
    enabled: bool = True
    power_w: float = 1.0  # Watts (0.01 - 10.0 W)
    power_unit: str = "W"
    wavelength_nm: float = 1550.0  # nm (center)
    bandwidth_nm: float = 1.0  # nm
    wavelength_unit: str = "nm"
    azimuth_deg: float = 0.0  # deg relative to platform / boresight
    elevation_deg: float = 0.0  # deg
    direction_ref: str = "PLATFORM"
    div_h_mrad: float = 1.0  # mrad
    div_v_mrad: float = 1.0  # mrad
    divergence_symmetric: bool = True
    divergence_unit: str = "mrad"
    profile_type: str = "GAUSSIAN"  # GAUSSIAN | TOP_HAT | CUSTOM
    profile_w: float = 1.0  # mrad
    profile_h: float = 1.0  # mrad
    mod_type: str = "AM"  # NONE | AM | PM | OOK | PPM | CUSTOM
    mod_freq_khz: float = 10.0  # kHz
    mod_depth: float = 1.0  # 0.0 - 1.0 (100%)
    mod_phase_deg: float = 0.0  # deg
    pulse_enabled: bool = False
    pulse_rate_khz: float = 10.0  # kHz
    pulse_width_us: float = 50.0  # us
    duty_cycle: float = 0.5  # fraction 0..1 (calculated or explicit)
    polarization_type: str = "UNPOLARIZED"  # UNPOLARIZED | LINEAR | CIRCULAR | ELLIPTICAL
    polarization_angle_deg: float = 0.0

    def validate(self) -> BeaconConfig:
        self.enabled = bool(self.enabled)
        self.power_w = float(max(0.001, min(float(self.power_w), 100.0)))
        self.wavelength_nm = float(max(400.0, min(float(self.wavelength_nm), 2000.0)))
        self.bandwidth_nm = float(max(0.01, min(float(self.bandwidth_nm), 100.0)))
        self.azimuth_deg = float(self.azimuth_deg)
        self.elevation_deg = float(max(-90.0, min(float(self.elevation_deg), 90.0)))
        self.div_h_mrad = float(max(0.05, min(float(self.div_h_mrad), 50.0)))
        if self.divergence_symmetric:
            self.div_v_mrad = self.div_h_mrad
        else:
            self.div_v_mrad = float(max(0.05, min(float(self.div_v_mrad), 50.0)))
        if self.profile_type not in {"GAUSSIAN", "TOP_HAT", "CUSTOM"}:
            self.profile_type = "GAUSSIAN"
        if self.mod_type not in {"NONE", "AM", "PM", "OOK", "PPM", "CUSTOM"}:
            self.mod_type = "AM"
        self.mod_freq_khz = float(max(0.001, min(float(self.mod_freq_khz), 1000.0)))
        self.mod_depth = float(max(0.0, min(float(self.mod_depth), 1.0)))
        self.mod_phase_deg = float(self.mod_phase_deg) % 360.0
        self.pulse_enabled = bool(self.pulse_enabled)
        self.pulse_rate_khz = float(max(0.001, min(float(self.pulse_rate_khz), 1000.0)))
        self.pulse_width_us = float(max(0.01, min(float(self.pulse_width_us), 10000.0)))
        # Auto-calculate duty cycle D = f * tau if pulse enabled
        if self.pulse_enabled:
            calc_d = (self.pulse_rate_khz * self.pulse_width_us) * 1e-3
            self.duty_cycle = float(max(0.001, min(calc_d, 1.0)))
        else:
            self.duty_cycle = float(max(0.0, min(float(self.duty_cycle), 1.0)))
        if self.polarization_type not in {"UNPOLARIZED", "LINEAR", "CIRCULAR", "ELLIPTICAL"}:
            self.polarization_type = "UNPOLARIZED"
        self.polarization_angle_deg = float(self.polarization_angle_deg) % 180.0
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BeaconConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class CommunicationConfig:
    """Communication interface and capabilities."""
    terminal_id: str = "RT-001"
    terminal_type: str = "REMOTE_TERMINAL"
    capabilities: list[str] = field(default_factory=lambda: [
        "BEACON", "OPTICAL_RX", "OPTICAL_TX", "BIDIRECTIONAL_LINK", "TRACKING",
    ])
    protocol_name: str = "OPTICAL_LINK"
    protocol_version: str = "1.0"

    def validate(self) -> CommunicationConfig:
        self.terminal_id = str(self.terminal_id or "RT-001").strip()
        self.terminal_type = str(self.terminal_type or "REMOTE_TERMINAL").strip()
        self.protocol_name = str(self.protocol_name or "OPTICAL_LINK").strip()
        self.protocol_version = str(self.protocol_version or "1.0").strip()
        if not isinstance(self.capabilities, list):
            self.capabilities = ["BEACON", "OPTICAL_RX", "OPTICAL_TX"]
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CommunicationConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class TargetSignatureConfig:
    """Identification criteria for target discrimination."""
    wavelength_nm: float = 1550.0
    wavelength_tol_nm: float = 2.0
    mod_type: str = "AM"
    mod_freq_khz: float = 10.0
    duty_cycle: float = 0.5
    pulse_width_us: float = 50.0
    spatial_profile: str = "GAUSSIAN"
    expected_spot_size_mrad: float = 3.0
    expected_spot_size_tol_mrad: float = 0.5
    minimum_snr_db: float = 8.0
    polarization: str = "UNPOLARIZED"
    code: str | None = "RT001"

    def validate(self) -> TargetSignatureConfig:
        self.wavelength_nm = float(max(400.0, min(float(self.wavelength_nm), 2000.0)))
        self.wavelength_tol_nm = float(max(0.1, min(float(self.wavelength_tol_nm), 50.0)))
        self.mod_freq_khz = float(max(0.001, min(float(self.mod_freq_khz), 1000.0)))
        self.minimum_snr_db = float(max(0.0, min(float(self.minimum_snr_db), 50.0)))
        self.expected_spot_size_mrad = float(max(0.1, min(float(self.expected_spot_size_mrad), 50.0)))
        self.expected_spot_size_tol_mrad = float(max(0.05, min(float(self.expected_spot_size_tol_mrad), 20.0)))
        if self.code is not None:
            self.code = str(self.code).strip()
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TargetSignatureConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class RemoteTerminalConfig:
    """Full data model for an individual Remote Terminal."""
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    state: StateConfig = field(default_factory=StateConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    beacon: BeaconConfig = field(default_factory=BeaconConfig)
    communication: CommunicationConfig = field(default_factory=CommunicationConfig)
    target_signature: TargetSignatureConfig = field(default_factory=TargetSignatureConfig)

    def validate(self) -> RemoteTerminalConfig:
        self.identity.validate()
        self.state.validate()
        self.position.validate()
        self.beacon.validate()
        self.communication.validate()
        self.target_signature.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteTerminalConfig:
        if not isinstance(data, dict):
            return cls()
        inst = cls(
            identity=IdentityConfig.from_dict(data.get("identity")),
            state=StateConfig.from_dict(data.get("state")),
            position=PositionConfig.from_dict(data.get("position")),
            beacon=BeaconConfig.from_dict(data.get("beacon")),
            communication=CommunicationConfig.from_dict(data.get("communication")),
            target_signature=TargetSignatureConfig.from_dict(data.get("target_signature")),
        )
        return inst.validate()


@dataclass
class FormationConfig:
    """Spatial arrangement / geometry of multi-terminal formations."""
    shape: str = "Circle"  # Single | Line | Circle | Arc | Grid | Rectangle | V-Formation | Custom
    radius_m: float = 100.0  # m
    spacing_m: float = 50.0  # m
    rotation_deg: float = 0.0  # deg
    rows: int = 2
    columns: int = 2
    reference_frame: str = "LOCAL"

    def validate(self) -> FormationConfig:
        shapes = {"Single", "Line", "Circle", "Arc", "Grid", "Rectangle", "V-Formation", "Custom"}
        if self.shape not in shapes:
            self.shape = "Circle"
        self.radius_m = float(max(1.0, min(float(self.radius_m), 2500.0)))
        self.spacing_m = float(max(1.0, min(float(self.spacing_m), 1000.0)))
        self.rotation_deg = float(self.rotation_deg) % 360.0
        self.rows = max(1, min(int(self.rows), 8))
        self.columns = max(1, min(int(self.columns), 8))
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FormationConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


def normalize_motion_profile(profile: object) -> str:
    """Canonicalize motion profile names incl. common aliases.

    Figure-8: "Figure 8" | "FIGURE_8" | "FIG8" | "Fig-8" -> "Figure-8".
    Random: "Random" | "RANDOM" | "RandomWalk" | "RW" -> "Random Walk".
    """
    p = str(profile or "").strip()
    low = p.lower().replace("_", " ").replace("-", " ").strip()
    low_nospace = low.replace(" ", "")
    if low_nospace in ("figure8", "fig8", "figureeight"):
        return "Figure-8"
    if low_nospace in ("random", "randomwalk", "rw"):
        return "Random Walk"
    for canonical in ("Stationary", "Constant Velocity", "Linear", "Circular",
                      "Sinusoidal", "Figure-8", "Random Walk", "Waypoint", "Custom"):
        if p == canonical or low == canonical.lower():
            return canonical
    return p


@dataclass
class MotionConfig:
    """Scenario-level motion kinematics."""
    profile: str = "Constant Velocity"  # Stationary | Constant Velocity | Linear | Circular | Sinusoidal | Waypoint | Custom
    speed_mps: float = 10.0  # m/s (0 - 200 m/s)
    direction_deg: float = 45.0  # heading deg (0 - 360)
    elevation_deg: float = 0.0  # elevation deg (-90 to +90)
    acceleration_mps2: float = 2.0  # m/s^2 (0 - 50 m/s^2)
    trajectory: str = "Straight"  # Straight | Circular | Arc | Waypoint | Spline
    start_x: float = 1000.0
    start_y: float = 1000.0
    start_z: float = 0.0

    def validate(self) -> MotionConfig:
        profiles = {"Stationary", "Constant Velocity", "Linear", "Circular", "Sinusoidal", "Figure-8", "Random Walk", "Waypoint", "Custom"}
        self.profile = normalize_motion_profile(self.profile)
        if self.profile not in profiles:
            self.profile = "Constant Velocity"
        self.speed_mps = float(max(0.0, min(float(self.speed_mps), 500.0)))
        self.direction_deg = float(self.direction_deg) % 360.0
        self.elevation_deg = float(max(-90.0, min(float(self.elevation_deg), 90.0)))
        self.acceleration_mps2 = float(max(0.0, min(float(self.acceleration_mps2), 100.0)))
        self.start_x = float(self.start_x)
        self.start_y = float(self.start_y)
        self.start_z = float(self.start_z)
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MotionConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class RemoteTerminalScenarioConfig:
    """Top-level scenario configuration owning formation, motion, and terminals."""
    terminal_count: int = 1
    formation: FormationConfig = field(default_factory=FormationConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    terminals: list[RemoteTerminalConfig] = field(default_factory=list)

    def validate(self) -> RemoteTerminalScenarioConfig:
        self.terminal_count = max(1, min(int(self.terminal_count), 8))
        self.formation.validate()
        self.motion.validate()
        while len(self.terminals) < self.terminal_count:
            idx = len(self.terminals) + 1
            rt = RemoteTerminalConfig(
                identity=IdentityConfig(id=f"RT-{idx:03d}", name=f"Remote Optical Terminal {idx:03d}"),
                communication=CommunicationConfig(terminal_id=f"RT-{idx:03d}"),
                target_signature=TargetSignatureConfig(code=f"RT{idx:03d}"),
            )
            self.terminals.append(rt)
        if len(self.terminals) > self.terminal_count:
            self.terminals = self.terminals[:self.terminal_count]
        for t in self.terminals:
            t.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteTerminalScenarioConfig:
        if not isinstance(data, dict):
            return cls()
        terminals = [
            RemoteTerminalConfig.from_dict(t) for t in data.get("terminals", [])
        ]
        inst = cls(
            terminal_count=data.get("terminal_count", len(terminals) or 1),
            formation=FormationConfig.from_dict(data.get("formation")),
            motion=MotionConfig.from_dict(data.get("motion")),
            terminals=terminals,
        )
        return inst.validate()
