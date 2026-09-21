# remote_terminal/models.py - Runtime data models (RemoteTerminal.md §§14-15, §49).
#
# Configuration lives in config.py; this module holds MUTABLE RUNTIME STATE
# only. GUI configuration objects are never written here.
from __future__ import annotations

from dataclasses import dataclass, field

from common.protocol.beacon.navigation import NavigationState2D
from remote_terminal.config import ModulationType, OperationalState


@dataclass
class Vector2:
    """2D vector in metres (position) or derived units (velocity m/s)."""

    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: Vector2) -> Vector2:
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2) -> Vector2:
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vector2:
        return Vector2(self.x * float(scalar), self.y * float(scalar))

    __rmul__ = __mul__

    def length(self) -> float:
        return (self.x**2 + self.y**2) ** 0.5

    def rotated(self, heading_deg: float) -> Vector2:
        """Rotate by ``heading_deg`` (0° = +X, 90° = +Y, degrees in GUI)."""
        import math

        rad = math.radians(float(heading_deg))
        c, s = math.cos(rad), math.sin(rad)
        return Vector2(self.x * c - self.y * s, self.x * s + self.y * c)

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass
class RemoteTerminalRuntime:
    """Live per-terminal simulation state (RemoteTerminal.md §14)."""

    terminal_id: str = "RT-001"
    position_m: Vector2 = field(default_factory=Vector2)
    velocity_mps: Vector2 = field(default_factory=Vector2)
    range_m: float = 0.0
    los_angle_deg: float = 0.0
    beam_angle_deg: float = 0.0
    pointing_error_deg: float = 0.0
    beam_width_rad: float = 0.001
    beam_diameter_m: float = 0.0
    effective_emission_enabled: bool = False
    instantaneous_power_w: float = 0.0
    pointing_coupling: float = 1.0
    beacon_sequence: int = 0
    operational_state: OperationalState = OperationalState.BEACONING


@dataclass
class RemoteScenarioRuntime:
    """Live scenario state: formation center + terminal runtimes (§15)."""

    simulation_time_s: float = 0.0
    formation_center_m: Vector2 = field(default_factory=Vector2)
    terminals: list[RemoteTerminalRuntime] = field(default_factory=list)


@dataclass
class OpticalEmission:
    """What the environment/propagation layer consumes (§49).

    ``beam_width_rad`` is the FULL angular beam width
    (``spot_size_mrad * 1e-3``) — never FWHM, radius, or half-angle.
    """

    active: bool = False
    wavelength_nm: float = 1550.0
    instantaneous_power_w: float = 0.0
    pointing_coupling: float = 1.0
    modulation: ModulationType = ModulationType.OOK
    beam_center_angle_deg: float = 0.0
    beam_width_rad: float = 0.001


__all__ = [
    "Vector2",
    "NavigationState2D",
    "RemoteTerminalRuntime",
    "RemoteScenarioRuntime",
    "OpticalEmission",
]
