# remote_terminal/config.py - Remote Terminal data models (2D only).
#
# Every parameter here exists because the Local Terminal reads it during
# one or more operational phases (Search → Detection → Identification →
# Acquisition → Tracking → Reacquisition).  See implementation_plan.md
# for the full parameter-to-phase traceability matrix.

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
    """Identity of the remote terminal.

    Feeds LT: Identification (Gate 3), Reacquisition (merge), GUI display.
    """
    id: str = "RT-001"
    name: str = "Remote Optical Terminal 001"

    def validate(self) -> IdentityConfig:
        self.id = str(self.id or "RT-001").strip()
        self.name = str(self.name or f"Remote Terminal {self.id}").strip()
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IdentityConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class StateConfig:
    """Operational state of the remote terminal.

    Feeds LT: ``is_emitting`` gate (all phases), link FSM dwell (Acquisition/Tracking).
    """
    operational_state: str = "ACTIVE"    # ACTIVE | STANDBY | OFF
    power_state: str = "ON"              # ON | OFF
    beacon_state: str = "EMITTING"       # OFF | READY | EMITTING
    communication_state: str = "NO_LINK" # NO_LINK | DETECTING | OPTICAL_LOCK | HANDSHAKE | CONNECTED | ERROR

    def validate(self) -> StateConfig:
        if self.operational_state not in {"ACTIVE", "STANDBY", "OFF"}:
            self.operational_state = "ACTIVE"
        if self.power_state not in {"ON", "OFF"}:
            self.power_state = "ON"
        if self.beacon_state not in {"OFF", "READY", "EMITTING"}:
            self.beacon_state = "EMITTING"
        cms = {"NO_LINK", "DETECTING", "OPTICAL_LOCK", "HANDSHAKE", "CONNECTED", "ERROR"}
        if self.communication_state not in cms:
            self.communication_state = "NO_LINK"
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StateConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class PositionConfig:
    """2D position in world-space pixels.

    Feeds LT: Search (spot placement), Detection (FOV check),
    Tracking (centroid source), Reacquisition (predicted position).
    """
    x: float = 1000.0
    y: float = 1000.0

    def validate(self) -> PositionConfig:
        self.x = float(self.x)
        self.y = float(self.y)
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PositionConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class BeaconConfig:
    """Optical beacon emission characteristics.

    Optical layer (Search + Detection):
        enabled, power_w, wavelength_nm, div_h/v_mrad, profile_type,
        mod_type/freq/depth/phase.
    Identity layer (Identification):
        identification_code_enabled/code, chip_rate_hz, token,
        network_id, capabilities, protocol_version, message_type, payload_codec.
    """
    # ── Optical Layer (Search + Detection) ──
    enabled: bool = True
    power_w: float = 1.0              # Watts (0.01 – 10.0)
    wavelength_nm: float = 1550.0     # nm (center)
    div_h_mrad: float = 1.0           # mrad
    div_v_mrad: float = 1.0           # mrad
    divergence_symmetric: bool = True
    profile_type: str = "GAUSSIAN"    # GAUSSIAN | TOP_HAT | CUSTOM
    mod_type: str = "AM"              # AM | OOK | NONE
    mod_freq_khz: float = 10.0        # kHz
    mod_depth: float = 1.0            # 0.0 – 1.0
    mod_phase_deg: float = 0.0        # deg
    # ── Identity Layer (Identification) ──
    identification_code_enabled: bool = True
    identification_code: str = "RT001"
    chip_rate_hz: float = 12.0
    token: str = "ALPHA-7"
    network_id: int = 0
    capabilities: int = 0
    protocol_version: int = 1
    message_type: int = 1
    payload_codec: str = "COMPACT"    # COMPACT | JSON

    def validate(self) -> BeaconConfig:
        self.enabled = bool(self.enabled)
        self.power_w = float(max(0.001, min(float(self.power_w), 100.0)))
        self.wavelength_nm = float(max(400.0, min(float(self.wavelength_nm), 2000.0)))
        self.div_h_mrad = float(max(0.05, min(float(self.div_h_mrad), 50.0)))
        if self.divergence_symmetric:
            self.div_v_mrad = self.div_h_mrad
        else:
            self.div_v_mrad = float(max(0.05, min(float(self.div_v_mrad), 50.0)))
        if self.profile_type not in {"GAUSSIAN", "TOP_HAT", "CUSTOM"}:
            self.profile_type = "GAUSSIAN"
        if self.mod_type not in {"AM", "OOK", "NONE"}:
            self.mod_type = "AM"
        self.mod_freq_khz = float(max(0.001, min(float(self.mod_freq_khz), 1000.0)))
        self.mod_depth = float(max(0.0, min(float(self.mod_depth), 1.0)))
        self.mod_phase_deg = float(self.mod_phase_deg) % 360.0
        self.identification_code_enabled = bool(self.identification_code_enabled)
        self.identification_code = str(self.identification_code or "").strip()[:32]
        self.protocol_version = int(self.protocol_version if self.protocol_version is not None else 1)
        self.message_type = int(self.message_type if self.message_type is not None else 1)
        self.payload_codec = str(self.payload_codec or "COMPACT").upper()
        if self.payload_codec not in {"COMPACT", "JSON"}:
            self.payload_codec = "COMPACT"
        self.chip_rate_hz = float(max(0.5, min(float(self.chip_rate_hz or 12.0), 60.0)))
        self.network_id = int(getattr(self, "network_id", 0) or 0) & 0xFF
        self.capabilities = int(getattr(self, "capabilities", 0) or 0) & 0xFFFF
        return self

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BeaconConfig:
        return cls(**_filter_dataclass_fields(cls, data)).validate()


@dataclass
class RemoteTerminalConfig:
    """Full data model for an individual Remote Terminal (2D)."""
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    state: StateConfig = field(default_factory=StateConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    beacon: BeaconConfig = field(default_factory=BeaconConfig)

    def validate(self) -> RemoteTerminalConfig:
        self.identity.validate()
        self.state.validate()
        self.position.validate()
        self.beacon.validate()
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
    """Scenario-level motion kinematics (2D)."""
    profile: str = "Constant Velocity"  # Stationary | Constant Velocity | Linear | Circular | Sinusoidal | Waypoint | Custom
    speed_mps: float = 10.0  # m/s (0 – 200)
    direction_deg: float = 45.0  # heading deg (0 – 360)
    acceleration_mps2: float = 2.0  # m/s² (0 – 50)
    start_x: float = 1000.0
    start_y: float = 1000.0

    def validate(self) -> MotionConfig:
        profiles = {"Stationary", "Constant Velocity", "Linear", "Circular", "Sinusoidal", "Figure-8", "Random Walk", "Waypoint", "Custom"}
        self.profile = normalize_motion_profile(self.profile)
        if self.profile not in profiles:
            self.profile = "Constant Velocity"
        self.speed_mps = float(max(0.0, min(float(self.speed_mps), 500.0)))
        self.direction_deg = float(self.direction_deg) % 360.0
        self.acceleration_mps2 = float(max(0.0, min(float(self.acceleration_mps2), 100.0)))
        self.start_x = float(self.start_x)
        self.start_y = float(self.start_y)
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
                beacon=BeaconConfig(identification_code=f"RT{idx:03d}"),
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


# ── 2D-minimal facade (payload-ready) ──────────────────────────────────
@dataclass
class RemoteBeacon:
    """Minimal 2D beacon: the only fields the sim physics + payload need.

    Converts to the full ``RemoteTerminalConfig`` via ``to_terminal_config()``
    so all existing pipelines keep working unchanged.
    """

    id: str = "RT-001"
    x: float = 1000.0
    y: float = 1000.0
    enabled: bool = True
    power_w: float = 1.0
    wavelength_nm: float = 1550.0
    spot_px: float = 9.0
    token: str = "ALPHA-7"
    chip_rate_hz: float = 12.0
    network_id: int = 0

    def to_terminal_config(self) -> "RemoteTerminalConfig":
        Spot = float(max(3.0, min(float(self.spot_px), 45.0)))
        # spot_px -> divergence mrad at default 0.109 mrad/px scale
        div = Spot * 0.109083 * 4.0
        return RemoteTerminalConfig(
            identity=IdentityConfig(id=self.id, name=f"Remote {self.id}"),
            state=StateConfig(
                operational_state="ACTIVE" if self.enabled else "OFF",
                power_state="ON" if self.enabled else "OFF",
                beacon_state="EMITTING" if self.enabled else "OFF",
            ),
            position=PositionConfig(x=float(self.x), y=float(self.y)),
            beacon=BeaconConfig(
                enabled=bool(self.enabled),
                power_w=float(self.power_w),
                wavelength_nm=float(self.wavelength_nm),
                div_h_mrad=float(div),
                div_v_mrad=float(div),
                token=str(self.token),
                chip_rate_hz=float(self.chip_rate_hz),
                network_id=int(self.network_id),
            ),
        )


def make_2d_terminal(
    terminal_id: str = "RT-001",
    x: float = 1000.0,
    y: float = 1000.0,
    wavelength_nm: float = 1550.0,
    power_w: float = 1.0,
    enabled: bool = True,
    **kwargs: Any,
) -> "RemoteTerminalConfig":
    """One-line 2D terminal constructor (payload-ready defaults)."""
    return RemoteBeacon(
        id=terminal_id, x=x, y=y, enabled=enabled,
        power_w=power_w, wavelength_nm=wavelength_nm,
        spot_px=float(kwargs.get("spot_px", 9.0)),
        token=str(kwargs.get("token", "ALPHA-7")),
        chip_rate_hz=float(kwargs.get("chip_rate_hz", 12.0)),
        network_id=int(kwargs.get("network_id", 0)),
    ).to_terminal_config()


def make_2d_scenario(
    terminals: list[RemoteBeacon] | None = None,
    motion_profile: str = "Stationary",
    speed: float = 0.0,
    anchor_x: float = 1000.0,
    anchor_y: float = 1000.0,
    formation: str = "Single",
    spacing: float = 50.0,
) -> RemoteTerminalScenarioConfig:
    """One-line 2D scenario: N beacons + shared anchor motion."""
    terms = list(terminals or [RemoteBeacon()])
    cfgs = [t.to_terminal_config() for t in terms]
    return RemoteTerminalScenarioConfig(
        terminal_count=len(cfgs),
        formation=FormationConfig(shape=formation, spacing_m=float(spacing)),
        motion=MotionConfig(profile=motion_profile, speed_mps=float(speed),
                            start_x=float(anchor_x), start_y=float(anchor_y)),
        terminals=cfgs,
    ).validate()
