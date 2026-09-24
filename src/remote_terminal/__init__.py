# remote_terminal/__init__.py - Remote Terminal subsystem (Plan/RemoteTerminal.md).
#
# 2D FSOC remote terminal: formation → motion → position → geometry → beam →
# beacon (with last-known-location navigation payload) → optical emission.
# Qt-free: safe for headless simulation, tests, and training wrappers.
from __future__ import annotations

from src.remote_terminal.beacon_encoder import BeaconGenerator, GeneratedBeacon
from src.remote_terminal.config import (
    FIELD_METADATA,
    MAX_TERMINALS,
    SUPPORTED_WAVELENGTH_MAX_NM,
    SUPPORTED_WAVELENGTH_MIN_NM,
    FORMATION_SHAPE_LABELS,
    MODULATION_LABELS,
    MOTION_PROFILE_LABELS,
    OPERATIONAL_STATE_LABELS,
    FormationShape,
    ModulationType,
    MotionProfile,
    OperationalState,
    RemoteFormationConfig,
    RemoteScenarioConfig,
    RemoteTerminalConfig,
    coerce_enum,
    make_default_scenario,
)
from src.remote_terminal.formation import FormationManager
from src.remote_terminal.geometry import GeometryEngine
from src.remote_terminal.models import (
    NavigationState2D,
    OpticalEmission,
    RemoteScenarioRuntime,
    RemoteTerminalRuntime,
    Vector2,
)
from src.remote_terminal.motion import MotionModel
from src.remote_terminal.optics import BeamModel, beam_diameter_m, beam_width_rad, is_emitting
from src.remote_terminal.pointing import PointingModel
from src.remote_terminal.scenario import RemoteTerminalManager
from src.remote_terminal.terminal import RemoteTerminal

__all__ = [
    # Config (§§8-13)
    "FormationShape",
    "MotionProfile",
    "OperationalState",
    "ModulationType",
    "RemoteFormationConfig",
    "RemoteTerminalConfig",
    "RemoteScenarioConfig",
    "FIELD_METADATA",
    "FORMATION_SHAPE_LABELS",
    "MOTION_PROFILE_LABELS",
    "OPERATIONAL_STATE_LABELS",
    "MODULATION_LABELS",
    "SUPPORTED_WAVELENGTH_MIN_NM",
    "SUPPORTED_WAVELENGTH_MAX_NM",
    "MAX_TERMINALS",
    "coerce_enum",
    "make_default_scenario",
    # Models (§§14-15, §49)
    "Vector2",
    "NavigationState2D",
    "RemoteTerminalRuntime",
    "RemoteScenarioRuntime",
    "OpticalEmission",
    # Subsystems (§§35, 27, 46, 47, 48, 51)
    "FormationManager",
    "MotionModel",
    "GeometryEngine",
    "PointingModel",
    "BeamModel",
    "BeaconGenerator",
    "GeneratedBeacon",
    "is_emitting",
    "beam_width_rad",
    "beam_diameter_m",
    # Orchestration (§§68-70)
    "RemoteTerminal",
    "RemoteTerminalManager",
]
