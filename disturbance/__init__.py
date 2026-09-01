"""
Package: disturbance
Purpose: FSOC channel impairments — sensor, turbulence, vibration, drift (modular).
Public API: disturbances (module), reset_disturbance_state, Sensor/Turbulence/Vibration/CameraMotion
Notes: Re-exports from submodules for backward compat.
  - `from disturbance import disturbances as dist` still works (disturbances.py shim)
  - `from disturbance.state import reset_disturbance_state` for GUI reset
  - `from disturbance import sensor_noise, turbulence, vibration, camera_motion` for direct use
"""

from disturbance import disturbances  # noqa: F401
from disturbance.state import reset_disturbance_state  # noqa: F401

__all__ = ["disturbances", "reset_disturbance_state"]