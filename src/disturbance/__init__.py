"""
Package: disturbance
Purpose: FSOC channel impairments — sensor, turbulence, vibration, drift (modular).
Public API: disturbances (module), reset_disturbance_state, Sensor/Turbulence/Vibration/CameraMotion
Notes: Re-exports from submodules for backward compat.
  - `from src.disturbance import disturbances as dist` still works (disturbances.py shim)
  - `from src.disturbance.state import reset_disturbance_state` for GUI reset
  - `from src.disturbance import sensor_noise, turbulence, vibration, camera_motion` for direct use
"""

import sys as _sys

from src.disturbance import disturbances  # noqa: F401
from src.disturbance.core import DisturbanceContext, DisturbancePipeline, DisturbanceRng, DisturbanceState
from src.disturbance.core.config import DisturbanceConfig

# Strict-compat flat-module aliases: `from src.disturbance.image_noise import ...`,
# `from src.disturbance.config import ...` must keep working (tests + GUI).
# Eager sys.modules registration is one-time import cost (not per-frame),
# so keep it; __getattr__ below is a safety net for anything missed.
from src.disturbance.core import config as _config, constants as _constants, dt_provider as _dt_provider, helpers as _helpers, state as _state
from src.disturbance.camera import drift as _drift, jitter as _jitter, platform as _platform, vibration as _vibration
from src.disturbance.environment import atmospheric as _atmospheric
from src.disturbance.optical import turbulence as _turbulence
from src.disturbance.sensor import image_noise as _image_noise, sensor_noise as _sensor_noise
for _name, _module in {
  "config": _config, "constants": _constants, "dt_provider": _dt_provider,
  "helpers": _helpers, "state": _state, "atmospheric": _atmospheric, "camera_jitter": _jitter,
  "camera_motion": _drift, "platform_motion": _platform, "vibration": _vibration,
  "turbulence": _turbulence, "image_noise": _image_noise, "sensor_noise": _sensor_noise,
}.items():
  _sys.modules.setdefault(f"{__name__}.{_name}", _module)


def __getattr__(name: str):
    target = _LAZY_ALIASES.get(name)
    if target is not None:
        import importlib as _il
        mod = _il.import_module(target)
        globals()[name] = mod
        _sys.modules.setdefault(f"{__name__}.{name}", mod)
        return mod
    if name == "reset_disturbance_state":
        from src.disturbance.core.state import reset_disturbance_state as _r
        globals()[name] = _r
        return _r
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
  "disturbances", "legacy", "DisturbanceConfig", "DisturbanceContext",
  "DisturbancePipeline", "DisturbanceRng", "DisturbanceState",
  "reset_disturbance_state",
]