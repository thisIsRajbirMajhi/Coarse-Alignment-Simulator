# remote_terminal/config.py - GUI-facing configuration (RemoteTerminal.md §§8-13, §57).
#
# Enums, configuration models, explicit validation, and GUI field metadata.
# Validation NEVER silently corrects: invalid input raises ValueError with a
# useful message. Qt-free: safe to import from headless simulation and tests.
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FormationShape(str, Enum):
    SINGLE = "single"
    LINE = "line"
    CIRCLE = "circle"


class MotionProfile(str, Enum):
    REST = "rest"
    CONSTANT_VELOCITY = "constant_velocity"
    CIRCULAR = "circular"
    FIGURE_8 = "figure_8"
    RANDOM = "random"
    SPIRAL = "spiral"
    SINUSOIDAL = "sinusoidal"


class OperationalState(str, Enum):
    BEACONING = "beaconing"
    FAULT = "fault"


class ModulationType(str, Enum):
    OOK = "ook"


FORMATION_SHAPE_LABELS: dict[str, str] = {
    FormationShape.SINGLE.value: "Single",
    FormationShape.LINE.value: "Line",
    FormationShape.CIRCLE.value: "Circle",
}

MOTION_PROFILE_LABELS: dict[str, str] = {
    MotionProfile.REST.value: "Rest",
    MotionProfile.CONSTANT_VELOCITY.value: "Constant Velocity",
    MotionProfile.CIRCULAR.value: "Circular",
    MotionProfile.FIGURE_8.value: "Figure-8",
    MotionProfile.RANDOM.value: "Random",
    MotionProfile.SPIRAL.value: "Spiral",
    MotionProfile.SINUSOIDAL.value: "Sinusoidal",
}

OPERATIONAL_STATE_LABELS: dict[str, str] = {
    OperationalState.BEACONING.value: "BEACONING",
    OperationalState.FAULT.value: "FAULT",
}

MODULATION_LABELS: dict[str, str] = {
    ModulationType.OOK.value: "OOK",
}

# Simulator-supported wavelength window (nm). The optical chain is
# characterised for near-infrared FSOC bands; values outside are rejected.
SUPPORTED_WAVELENGTH_MIN_NM: float = 800.0
SUPPORTED_WAVELENGTH_MAX_NM: float = 1700.0

# UI/simultaneous-terminal cap (documented; validation enforces it).
MAX_TERMINALS: int = 8


def coerce_enum(enum_cls: type[Enum], value: Any, field_name: str) -> Enum:
    """Map a member, exact value, or display label to ``enum_cls`` (explicit).

    Legacy values map to canonical: LINEAR→CONSTANT_VELOCITY, SINUSOIDAL→FIGURE_8,
    GRID/RECTANGLE/V/ARC→LINE, CW/PPM→OOK, OFF/STANDBY/LINKED→BEACONING.
    """
    if isinstance(value, enum_cls):
        return value
    labels = {
        FormationShape: FORMATION_SHAPE_LABELS,
        MotionProfile: MOTION_PROFILE_LABELS,
        OperationalState: OPERATIONAL_STATE_LABELS,
        ModulationType: MODULATION_LABELS,
    }.get(enum_cls, {})
    text = str(value).strip()
    for member in enum_cls:
        if text == member.value or text.lower() == member.value.lower():
            return member
        label = labels.get(member.value, "")
        if label and text.lower() == label.lower():
            return member
    # Legacy mappings for backward compat (pruned enums)
    _legacy_map = {
        FormationShape: {"arc": "line", "grid": "line", "rectangle": "line", "v_formation": "line"},
        MotionProfile: {"linear": "constant_velocity"},
        OperationalState: {"off": "beaconing", "standby": "beaconing", "linked": "beaconing"},
        ModulationType: {"cw": "ook", "ppm": "ook"},
    }
    mapped = _legacy_map.get(enum_cls, {}).get(text.lower())
    if mapped:
        for member in enum_cls:
            if member.value == mapped:
                return member
    allowed = ", ".join(m.value for m in enum_cls)
    raise ValueError(f"Invalid {field_name} {value!r}. Allowed: {allowed}.")


def _require_number(name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be a number, got {value!r}.") from e


@dataclass
class RemoteFormationConfig:
    """Scenario-level formation + motion configuration (RemoteTerminal.md §10)."""

    terminal_count: int = 1
    formation_shape: FormationShape = FormationShape.SINGLE
    motion_profile: MotionProfile = MotionProfile.CONSTANT_VELOCITY
    terminal_spacing_m: float = 100.0
    speed_mps: float = 10.0
    heading_deg: float = 0.0
    # Custom starting position: formation-center offset (m) from the world
    # center. (0, 0) = scene center (legacy behavior). Clamped to world
    # bounds by the manager.
    start_offset_x_m: float = 0.0
    start_offset_y_m: float = 0.0

    def validate(self) -> RemoteFormationConfig:
        count = self.terminal_count
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError(f"Terminal count must be an integer, got {count!r}.")
        if count < 1:
            raise ValueError(f"Terminal count must be >= 1, got {count}.")
        if count > MAX_TERMINALS:
            raise ValueError(f"Terminal count must be <= {MAX_TERMINALS}, got {count}.")
        if not isinstance(self.formation_shape, FormationShape):
            allowed = ", ".join(m.value for m in FormationShape)
            raise ValueError(
                "Formation shape must be a FormationShape member, "
                f"got {self.formation_shape!r}. Allowed: {allowed}."
            )
        if not isinstance(self.motion_profile, MotionProfile):
            raise ValueError(
                f"Motion profile must be a MotionProfile member, got {self.motion_profile!r}."
            )
        spacing = _require_number("Terminal spacing", self.terminal_spacing_m)
        if spacing < 0:
            raise ValueError("Terminal spacing cannot be negative.")
        speed = _require_number("Speed", self.speed_mps)
        if speed < 0:
            raise ValueError("Speed cannot be negative.")
        heading = _require_number("Heading", self.heading_deg)
        if not -180.0 <= heading <= 180.0:
            raise ValueError(f"Heading {heading}° outside [-180, 180]°.")
        for _name, _val in (("Start offset X", self.start_offset_x_m),
                            ("Start offset Y", self.start_offset_y_m)):
            _v = _require_number(_name, _val)
            if not -5000.0 <= _v <= 5000.0:
                raise ValueError(f"{_name} {_v} m outside [-5000, 5000] m.")
        self.start_offset_x_m = float(self.start_offset_x_m)
        self.start_offset_y_m = float(self.start_offset_y_m)
        if self.formation_shape == FormationShape.SINGLE and count != 1:
            raise ValueError("SINGLE formation requires exactly one terminal.")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteFormationConfig:
        try:
            return cls(
                terminal_count=int(data.get("terminal_count", 1)),
                formation_shape=coerce_enum(
                    FormationShape, data.get("formation_shape", "single"), "formation shape"
                ),
                motion_profile=coerce_enum(
                    MotionProfile, data.get("motion_profile", "constant_velocity"),
                    "motion profile",
                ),
                terminal_spacing_m=float(data.get("terminal_spacing_m", 100.0)),
                speed_mps=float(data.get("speed_mps", 10.0)),
                heading_deg=float(data.get("heading_deg", 0.0)),
                start_offset_x_m=float(data.get("start_offset_x_m", 0.0)),
                start_offset_y_m=float(data.get("start_offset_y_m", 0.0)),
            ).validate()
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Invalid formation configuration: {e}") from e


@dataclass
class RemoteTerminalConfig:
    """Per-terminal configuration (Plan Hybrid-AI §1 — pruned to pixel/SNR/TID)."""

    terminal_id: str = "RT-001"
    # Single master emission switch — replaces triple power_enabled/beacon_enabled/operational_state
    emission_enabled: bool = True
    operational_state: OperationalState = OperationalState.BEACONING
    optical_power_w: float = 0.5
    wavelength_nm: float = 1550.0
    modulation: ModulationType = ModulationType.OOK  # locked to OOK
    spot_size_mrad: float = 1.0
    # Beacon payload identity (advanced, collapsed in GUI when count==1)
    token: str = ""
    network_id: int = 0
    enable_nav: bool = True
    # Pointing — bias is internal const (0.005), only jitter is user-visible
    pointing_jitter_sigma_deg: float = 0.002
    # Backward-compat shims (not GUI-exposed): power_enabled/beacon_enabled map to emission_enabled
    power_enabled: bool = True
    beacon_enabled: bool = True
    pointing_bias_deg: float = 0.005

    def validate(self) -> RemoteTerminalConfig:
        tid = str(self.terminal_id or "").strip()
        if not tid:
            raise ValueError("Terminal ID must be a non-empty string.")
        # Map legacy triple-switch to single emission_enabled (backward compat)
        if not isinstance(self.operational_state, OperationalState):
            # Coerce legacy strings like OFF/STANDBY/LINKED → BEACONING/FAULT
            try:
                legacy = str(self.operational_state).lower()
                if legacy in ("off", "standby", "linked"):
                    self.operational_state = OperationalState.BEACONING
                else:
                    self.operational_state = coerce_enum(OperationalState, self.operational_state, "operational_state")
            except Exception:
                self.operational_state = OperationalState.BEACONING
        if not isinstance(self.modulation, ModulationType):
            try:
                self.modulation = coerce_enum(ModulationType, self.modulation, "modulation")
            except ValueError:
                self.modulation = ModulationType.OOK
        # Sync emission_enabled with legacy power/beacon flags
        legacy_power = bool(getattr(self, "power_enabled", True))
        legacy_beacon = bool(getattr(self, "beacon_enabled", True))
        if not legacy_power or not legacy_beacon:
            self.emission_enabled = False
        if self.operational_state == OperationalState.FAULT:
            self.emission_enabled = False
        self.power_enabled = bool(self.emission_enabled)
        self.beacon_enabled = bool(self.emission_enabled)
        power = _require_number("Optical power", self.optical_power_w)
        if power < 0:
            raise ValueError("Optical power cannot be negative.")
        wl = _require_number("Wavelength", self.wavelength_nm)
        if not SUPPORTED_WAVELENGTH_MIN_NM <= wl <= SUPPORTED_WAVELENGTH_MAX_NM:
            raise ValueError(
                f"Wavelength {wl} nm outside supported range "
                f"[{SUPPORTED_WAVELENGTH_MIN_NM:.0f}, {SUPPORTED_WAVELENGTH_MAX_NM:.0f}] nm."
            )
        spot = _require_number("Spot size", self.spot_size_mrad)
        if spot <= 0:
            raise ValueError("Spot size must be greater than zero.")
        tok = str(self.token or "").strip()
        if len(tok.encode("utf-8")) > 255:
            raise ValueError("Token must be <= 255 bytes.")
        self.token = tok
        try:
            net = int(self.network_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Network ID must be an integer, got {self.network_id!r}.") from e
        if isinstance(self.network_id, bool) or not 0 <= net <= 255:
            raise ValueError(f"Network ID {self.network_id!r} outside [0, 255].")
        self.network_id = net
        self.enable_nav = bool(self.enable_nav)
        bias = _require_number("Pointing bias", self.pointing_bias_deg)
        if not -1.0 <= bias <= 1.0:
            raise ValueError(f"Pointing bias {bias}° outside [-1, 1]°.")
        jit = _require_number("Pointing jitter", self.pointing_jitter_sigma_deg)
        if not 0.0 <= jit <= 1.0:
            raise ValueError(f"Pointing jitter {jit}° outside [0, 1]°.")
        self.pointing_bias_deg = float(bias)
        self.pointing_jitter_sigma_deg = float(jit)
        return self

    def effective_token(self) -> str:
        """Wire token: explicit token or the TID when empty."""
        return str(self.token or "").strip() or str(self.terminal_id).strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteTerminalConfig:
        try:
            # emission_enabled is new master; fallback to legacy flags
            emission = data.get("emission_enabled", None)
            if emission is None:
                emission = bool(data.get("power_enabled", True)) and bool(data.get("beacon_enabled", True))
            return cls(
                terminal_id=str(data.get("terminal_id", "RT-001")),
                emission_enabled=bool(emission),
                operational_state=coerce_enum(
                    OperationalState, data.get("operational_state", "beaconing"),
                    "operational state",
                ),
                optical_power_w=float(data.get("optical_power_w", 0.5)),
                wavelength_nm=float(data.get("wavelength_nm", 1550.0)),
                modulation=coerce_enum(
                    ModulationType, data.get("modulation", "ook"), "modulation"
                ),
                spot_size_mrad=float(data.get("spot_size_mrad", 1.0)),
                token=str(data.get("token", "")),
                network_id=int(data.get("network_id", 0)),
                enable_nav=bool(data.get("enable_nav", True)),
                pointing_jitter_sigma_deg=float(data.get("pointing_jitter_sigma_deg", 0.002)),
            ).validate()
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Invalid terminal configuration: {e}") from e


@dataclass
class RemoteScenarioConfig:
    """Complete remote-terminal scenario (RemoteTerminal.md §12)."""

    formation: RemoteFormationConfig = field(default_factory=RemoteFormationConfig)
    terminals: list[RemoteTerminalConfig] = field(default_factory=list)
    # Simple mode: single 10px square beacon at center, bypass formation offsets
    single_beacon_mode: bool = False

    def validate(self) -> RemoteScenarioConfig:
        formation = self.formation.validate()
        self.single_beacon_mode = bool(self.single_beacon_mode)
        validated = [t.validate() for t in self.terminals]
        if bool(self.single_beacon_mode):
            # In single_beacon_mode formation is ignored — allow any count but terminal list controls rendering;
            # still enforce uniqueness
            seen: set[str] = set()
            for t in validated:
                tid = str(t.terminal_id).strip()
                if tid in seen:
                    raise ValueError(f"Terminal ID {tid!r} is duplicated.")
                seen.add(tid)
            return self
        if len(validated) != formation.terminal_count:
            raise ValueError(
                f"Terminal count is {formation.terminal_count} but "
                f"{len(validated)} terminal configurations exist."
            )
        seen: set[str] = set()
        for t in validated:
            tid = str(t.terminal_id).strip()
            if tid in seen:
                raise ValueError(f"Terminal ID {tid!r} is duplicated.")
            seen.add(tid)
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteScenarioConfig:
        try:
            formation = RemoteFormationConfig.from_dict(data.get("formation", {}))
            terminals = [
                RemoteTerminalConfig.from_dict(t) for t in data.get("terminals", [])
            ]
            single_beacon_mode = bool(data.get("single_beacon_mode", False))
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Invalid scenario configuration: {e}") from e
        return cls(formation=formation, terminals=terminals, single_beacon_mode=single_beacon_mode).validate()


def make_default_scenario(terminal_count: int = 1) -> RemoteScenarioConfig:
    """Build a validated default scenario with ``RT-001`` … ``RT-<n>`` IDs."""
    count = int(terminal_count)
    formation = RemoteFormationConfig(
        terminal_count=count,
        formation_shape=FormationShape.SINGLE if count == 1 else FormationShape.LINE,
    )
    cfg = RemoteScenarioConfig(
        formation=formation,
        terminals=[
            RemoteTerminalConfig(terminal_id=f"RT-{i + 1:03d}")
            for i in range(count)
        ],
    )
    return cfg.validate()


# GUI field metadata — pruned per Plan Hybrid-AI §1 (60% reduction).
# Only pixel/SNR/TID-relevant fields are GUI-exposed. Advanced payload
# (token/network_id/enable_nav) collapsed behind Advanced when count==1.
# Derived fields (range, los_angle, beam_diameter) removed from GUI.
FIELD_METADATA: dict[str, dict[str, Any]] = {
    "terminal_count": {
        "label": "Terminal Count", "control": "int", "unit": "",
        "min": 1, "max": MAX_TERMINALS, "step": 1, "group": "Formation",
        "description": "Number of remote terminals in the scenario.",
    },
    "formation_shape": {
        "label": "Formation Shape", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Formation",
        "description": "Geometric arrangement: Single / Line / Circle.",
    },
    "terminal_spacing_m": {
        "label": "Terminal Spacing", "control": "float", "unit": "m",
        "min": 0.0, "max": 5000.0, "step": 1.0, "group": "Formation",
        "description": "Nominal separation between neighbouring terminals (visible if count>1).",
    },
    "motion_profile": {
        "label": "Motion Profile", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Motion",
        "description": "Trajectory: Rest / Constant Velocity / Circular / Figure-8 / Random / Spiral / Sinusoidal.",
    },
    "speed_mps": {
        "label": "Speed", "control": "float", "unit": "m/s",
        "min": 0.0, "max": 10000.0, "step": 0.1, "group": "Motion",
        "description": "Formation-center speed (velocity is derived, not editable).",
    },
    "heading_deg": {
        "label": "Heading", "control": "float", "unit": "deg",
        "min": -180.0, "max": 180.0, "step": 0.5, "group": "Motion",
        "description": "0° = +X, 90° = +Y. Rotates the formation and sets travel direction.",
    },
    "start_offset_x_m": {
        "label": "Start Offset X", "control": "float", "unit": "m",
        "min": -5000.0, "max": 5000.0, "step": 10.0, "group": "Starting Position",
        "description": "Formation-center X offset from world center at build/reset.",
    },
    "start_offset_y_m": {
        "label": "Start Offset Y", "control": "float", "unit": "m",
        "min": -5000.0, "max": 5000.0, "step": 10.0, "group": "Starting Position",
        "description": "Formation-center Y offset from world center at build/reset.",
    },
    "terminal_id": {
        "label": "Terminal ID", "control": "text", "unit": "",
        "min": None, "max": None, "step": None, "group": "Identity",
        "description": "Unique identity transmitted in the beacon.",
    },
    "emission_enabled": {
        "label": "Emission", "control": "bool", "unit": "",
        "min": None, "max": None, "step": None, "group": "Emission",
        "description": "Master emission switch — ON=BEACONING, OFF=FAULT (replaces triple switch).",
    },
    "operational_state": {
        "label": "Operational State", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Emission",
        "description": "BEACONING (emit) or FAULT (inhibit).",
    },
    "optical_power_w": {
        "label": "Optical Power", "control": "float", "unit": "W",
        "min": 0.0, "max": 10.0, "step": 0.05, "group": "Optical",
        "description": "Emitted optical power in watts.",
    },
    "wavelength_nm": {
        "label": "Wavelength", "control": "float", "unit": "nm",
        "min": SUPPORTED_WAVELENGTH_MIN_NM, "max": SUPPORTED_WAVELENGTH_MAX_NM,
        "step": 1.0, "group": "Optical",
        "description": "Carrier wavelength within the supported simulator range.",
    },
    "spot_size_mrad": {
        "label": "Spot Size", "control": "float", "unit": "mrad",
        "min": 0.01, "max": 50.0, "step": 0.05, "group": "Optical",
        "description": "Full angular beam width/divergence (not FWHM, radius, or half-angle).",
    },
    "token": {
        "label": "Token", "control": "text", "unit": "",
        "min": None, "max": None, "step": None, "group": "Beacon Payload (Advanced)",
        "description": "Beacon auth token — Advanced, only when count>1.",
    },
    "network_id": {
        "label": "Network ID", "control": "int", "unit": "",
        "min": 0, "max": 255, "step": 1, "group": "Beacon Payload (Advanced)",
        "description": "Wire network ID — Advanced, only when count>1.",
    },
    "enable_nav": {
        "label": "NAV Extension", "control": "bool", "unit": "",
        "min": None, "max": None, "step": None, "group": "Beacon Payload (Advanced)",
        "description": "Attach NAV extension — Advanced, only when count>1.",
    },
    "pointing_jitter_sigma_deg": {
        "label": "Pointing Jitter", "control": "float", "unit": "deg",
        "min": 0.0, "max": 1.0, "step": 0.001, "group": "Pointing",
        "description": "1-sigma Gaussian beam-pointing jitter.",
    },
}


__all__ = [
    "FormationShape",
    "MotionProfile",
    "OperationalState",
    "ModulationType",
    "FORMATION_SHAPE_LABELS",
    "MOTION_PROFILE_LABELS",
    "OPERATIONAL_STATE_LABELS",
    "MODULATION_LABELS",
    "SUPPORTED_WAVELENGTH_MIN_NM",
    "SUPPORTED_WAVELENGTH_MAX_NM",
    "MAX_TERMINALS",
    "RemoteFormationConfig",
    "RemoteTerminalConfig",
    "RemoteScenarioConfig",
    "FIELD_METADATA",
    "coerce_enum",
    "make_default_scenario",
]
