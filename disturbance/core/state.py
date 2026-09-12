"""Typed temporal state for disturbance subsystems.

The legacy kernels use a tiny mapping protocol.  These classes implement that
protocol while keeping ownership and fields explicit for normal simulations.
"""

from contextlib import contextmanager
from dataclasses import MISSING, dataclass, field
from typing import Any

import numpy as np


class _StateFields:
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def clear(self) -> None:
        for key, value in self.__dataclass_fields__.items():
            setattr(self, key, value.default_factory() if value.default_factory is not MISSING else value.default)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            setattr(self, key, value)

    def pop(self, key: str, default: Any = None) -> Any:
        value = getattr(self, key, default)
        if hasattr(self, key):
            setattr(self, key, default)
        return value


@dataclass
class TurbulenceState(_StateFields):
    dx: np.ndarray | None = None
    dy: np.ndarray | None = None
    t: float = 0.0
    last_wall: float | None = None
    phase: Any = None


@dataclass
class VibrationState(_StateFields):
    t: float = 0.0
    last_wall: float | None = None
    phases: np.ndarray | None = None
    ou_pan: float = 0.0
    ou_tilt: float = 0.0


@dataclass
class CameraDriftState(_StateFields):
    vx: float = 0.0
    vy: float = 0.0
    bias_pan: float = 0.0
    bias_tilt: float = 0.0
    _last_wall: float | None = None


@dataclass
class PlatformMotionState(_StateFields):
    t: float = 0.0
    _pm_last_wall: float | None = None


@dataclass
class JitterState(_StateFields):
    jx: float = 0.0
    jy: float = 0.0
    _jit_last_wall: float | None = None


@dataclass
class SensorDefectState(_StateFields):
    hot_pixels: dict = field(default_factory=dict)

from disturbance.core.dt_provider import DtProvider


class DisturbanceState:
    """Compatibility aggregate for isolated legacy kernel calls."""

    def __init__(self):
        self.turb = {"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None}
        self.vib = {"t": 0.0, "last_wall": None, "phases": None}
        self.cam_global = {}
        self.platform = {"t": 0.0, "_pm_last_wall": None}
        self.jitter = {"_last_wall": None}

    def reset(self) -> None:
        self.turb.clear(); self.turb.update({"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None})
        self.vib.clear(); self.vib.update({"t": 0.0, "last_wall": None, "phases": None})
        self.cam_global.clear()
        self.platform.clear(); self.platform.update({"t": 0.0, "_pm_last_wall": None})
        self.jitter.clear()

    @contextmanager
    def isolated(self):
        import disturbance.core.state as module
        old = (module._turb_state, module._vib_state, module._cam_motion_state_global,
               module._platform_state_global, module._jitter_state_global)
        module._turb_state, module._vib_state, module._cam_motion_state_global = self.turb, self.vib, self.cam_global
        module._platform_state_global, module._jitter_state_global = self.platform, self.jitter
        try:
            yield self
        finally:
            (module._turb_state, module._vib_state, module._cam_motion_state_global,
             module._platform_state_global, module._jitter_state_global) = old

    @classmethod
    @contextmanager
    def isolated_state(cls):
        instance = cls()
        with instance.isolated():
            yield instance


_default_state = DisturbanceState()
_turb_state = _default_state.turb
_vib_state = _default_state.vib
_cam_motion_state_global = _default_state.cam_global
_platform_state_global = _default_state.platform
_jitter_state_global = _default_state.jitter


def _elapsed_dt(state: dict, fallback: float = 0.033) -> float:
    dt = DtProvider.resolve(state, None, clip=(0.005, 0.08))
    if state.get("_first_call_done") is None and state.get("t", 0.0) == 0.0 and state.get("phases") is None:
        return float(fallback)
    return dt


def reset_disturbance_state() -> None:
    _default_state.reset()
    try:
        from disturbance.sensor.image_noise import clear_hot_pixel_cache
        clear_hot_pixel_cache()
    except Exception:
        pass


def reset_vibration_state() -> None:
    _vib_state.clear(); _vib_state.update({"t": 0.0, "last_wall": None, "phases": None})


def reset_turbulence_state() -> None:
    _turb_state.clear(); _turb_state.update({"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None})


def reset_camera_motion_state() -> None:
    _cam_motion_state_global.clear()


def reset_platform_motion_state() -> None:
    _platform_state_global.clear(); _platform_state_global.update({"t": 0.0, "_pm_last_wall": None})


def reset_jitter_state() -> None:
    _jitter_state_global.clear()

__all__ = [
    "DisturbanceState",
    "reset_disturbance_state",
    "reset_turbulence_state",
    "reset_vibration_state",
    "reset_camera_motion_state",
    "reset_platform_motion_state",
    "reset_jitter_state",
    "TurbulenceState", "VibrationState", "CameraDriftState",
    "PlatformMotionState", "JitterState", "SensorDefectState",
]