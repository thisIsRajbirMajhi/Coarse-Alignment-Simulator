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
    ARC = "arc"
    GRID = "grid"
    RECTANGLE = "rectangle"
    V_FORMATION = "v_formation"


class MotionProfile(str, Enum):
    REST = "rest"
    CONSTANT_VELOCITY = "constant_velocity"
    LINEAR = "linear"
    CIRCULAR = "circular"
    SINUSOIDAL = "sinusoidal"
    FIGURE_8 = "figure_8"
    RANDOM = "random"


class OperationalState(str, Enum):
    OFF = "off"
    STANDBY = "standby"
    BEACONING = "beaconing"
    LINKED = "linked"
    FAULT = "fault"


class ModulationType(str, Enum):
    CW = "cw"
    OOK = "ook"
    PPM = "ppm"


FORMATION_SHAPE_LABELS: dict[str, str] = {
    FormationShape.SINGLE.value: "Single",
    FormationShape.LINE.value: "Line",
    FormationShape.CIRCLE.value: "Circle",
    FormationShape.ARC.value: "Arc",
    FormationShape.GRID.value: "Grid",
    FormationShape.RECTANGLE.value: "Rectangle",
    FormationShape.V_FORMATION.value: "V Formation",
}

MOTION_PROFILE_LABELS: dict[str, str] = {
    MotionProfile.REST.value: "Rest",
    MotionProfile.CONSTANT_VELOCITY.value: "Constant Velocity",
    MotionProfile.LINEAR.value: "Linear",
    MotionProfile.CIRCULAR.value: "Circular",
    MotionProfile.SINUSOIDAL.value: "Sinusoidal",
    MotionProfile.FIGURE_8.value: "Figure-8",
    MotionProfile.RANDOM.value: "Random",
}

OPERATIONAL_STATE_LABELS: dict[str, str] = {
    OperationalState.OFF.value: "OFF",
    OperationalState.STANDBY.value: "STANDBY",
    OperationalState.BEACONING.value: "BEACONING",
    OperationalState.LINKED.value: "LINKED",
    OperationalState.FAULT.value: "FAULT",
}

MODULATION_LABELS: dict[str, str] = {
    ModulationType.CW.value: "CW",
    ModulationType.OOK.value: "OOK",
    ModulationType.PPM.value: "PPM",
}

# Simulator-supported wavelength window (nm). The optical chain is
# characterised for near-infrared FSOC bands; values outside are rejected.
SUPPORTED_WAVELENGTH_MIN_NM: float = 800.0
SUPPORTED_WAVELENGTH_MAX_NM: float = 1700.0

# UI/simultaneous-terminal cap (documented; validation enforces it).
MAX_TERMINALS: int = 8


def coerce_enum(enum_cls: type[Enum], value: Any, field_name: str) -> Enum:
    """Map a member, exact value, or display label to ``enum_cls`` (explicit).

    Raises ValueError listing the allowed values for anything else.
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
    """Per-terminal configuration (RemoteTerminal.md §11)."""

    terminal_id: str = "RT-001"
    power_enabled: bool = True
    beacon_enabled: bool = True
    operational_state: OperationalState = OperationalState.BEACONING
    optical_power_w: float = 0.5
    wavelength_nm: float = 1550.0
    modulation: ModulationType = ModulationType.OOK
    spot_size_mrad: float = 1.0

    def validate(self) -> RemoteTerminalConfig:
        tid = str(self.terminal_id or "").strip()
        if not tid:
            raise ValueError("Terminal ID must be a non-empty string.")
        if not isinstance(self.operational_state, OperationalState):
            raise ValueError(
                f"Operational state must be an OperationalState member, "
                f"got {self.operational_state!r}."
            )
        if not isinstance(self.modulation, ModulationType):
            raise ValueError(
                f"Modulation must be a ModulationType member, got {self.modulation!r}."
            )
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
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteTerminalConfig:
        try:
            return cls(
                terminal_id=str(data.get("terminal_id", "RT-001")),
                power_enabled=bool(data.get("power_enabled", True)),
                beacon_enabled=bool(data.get("beacon_enabled", True)),
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
            ).validate()
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Invalid terminal configuration: {e}") from e


@dataclass
class RemoteScenarioConfig:
    """Complete remote-terminal scenario (RemoteTerminal.md §12)."""

    formation: RemoteFormationConfig = field(default_factory=RemoteFormationConfig)
    terminals: list[RemoteTerminalConfig] = field(default_factory=list)

    def validate(self) -> RemoteScenarioConfig:
        formation = self.formation.validate()
        validated = [t.validate() for t in self.terminals]
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
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Invalid scenario configuration: {e}") from e
        return cls(formation=formation, terminals=terminals).validate()


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


# GUI field metadata (RemoteTerminal.md §57): label, control type, unit,
# minimum, maximum, step, group, description. The formation/motion card is
# built from this schema instead of hard-coding the structure.
FIELD_METADATA: dict[str, dict[str, Any]] = {
    "terminal_count": {
        "label": "Terminal Count", "control": "int", "unit": "",
        "min": 1, "max": MAX_TERMINALS, "step": 1, "group": "Formation",
        "description": "Number of remote terminals in the scenario.",
    },
    "formation_shape": {
        "label": "Formation Shape", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Formation",
        "description": "Geometric arrangement of the terminals around the formation center.",
    },
    "terminal_spacing_m": {
        "label": "Terminal Spacing", "control": "float", "unit": "m",
        "min": 0.0, "max": 5000.0, "step": 1.0, "group": "Formation",
        "description": "Nominal separation between neighbouring terminals.",
    },
    "motion_profile": {
        "label": "Motion Profile", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Motion",
        "description": "Trajectory followed by the formation center.",
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
    "power_enabled": {
        "label": "Power", "control": "bool", "unit": "",
        "min": None, "max": None, "step": None, "group": "Emission",
        "description": "Master optical power switch (ON/OFF).",
    },
    "beacon_enabled": {
        "label": "Beacon", "control": "bool", "unit": "",
        "min": None, "max": None, "step": None, "group": "Emission",
        "description": "Beacon emission switch (ON/OFF).",
    },
    "operational_state": {
        "label": "Operational State", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Emission",
        "description": "BEACONING/LINKED allow emission; OFF/STANDBY/FAULT inhibit it.",
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
    "modulation": {
        "label": "Modulation", "control": "dropdown", "unit": "",
        "min": None, "max": None, "step": None, "group": "Optical",
        "description": "Beacon modulation format (default OOK).",
    },
    "spot_size_mrad": {
        "label": "Spot Size", "control": "float", "unit": "mrad",
        "min": 0.01, "max": 50.0, "step": 0.05, "group": "Optical",
        "description": "Full angular beam width/divergence (not FWHM, radius, or half-angle).",
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
