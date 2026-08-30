"""
Module: disturbance.disturbances
Purpose: Shim + facade for modular FSOC impairments — re-exports from submodules.
Public API: apply_sensor_noise, apply_turbulence, apply_platform_vibration,
           apply_camera_motion, apply_camera_motion_with_state, reset_disturbance_state,
           plus state dicts for backward compat.
Architecture (modular rebuild):
  - constants.py : physical constants (wavelength, r0, freqs, etc.)
  - state.py     : global temporal state + _elapsed_dt + reset_disturbance_state
  - helpers.py   : r0_from_intensity, rytov_variance (pure)
  - sensor_noise.py : apply_sensor_noise (stateless)
  - turbulence.py   : _kolmogorov_displacement + apply_turbulence (dt-aware)
  - vibration.py    : apply_platform_vibration (dt-aware)
  - camera_motion.py: apply_camera_motion / apply_camera_motion_with_state (dt-aware)
  - disturbances.py : this facade — well-commented sections, re-exports, backward compat

Fixes applied (per spec):
  - apply_turbulence(dt=None) now accepts sim-speed-scaled dt, falls back to wall-clock
  - apply_camera_motion_with_state(dt=None) same, threaded through wrapper
  - reset_disturbance_state() clears all three global dicts + per-instance drift
  - GUI tick now passes dt=dt_eff to all four disturbances for lockstep evolution

Notes: `from disturbance import disturbances as dist` still works.
       Prefer `from disturbance.state import reset_disturbance_state` for reset.
"""

# ============================================================
# SECTION: Re-exports — modular submodules
# ============================================================

from disturbance.camera_motion import apply_camera_motion, apply_camera_motion_with_state
from disturbance.constants import *  # noqa: F401,F403 re-export for introspection
from disturbance.helpers import r0_from_intensity as _r0_from_intensity  # noqa: F401
from disturbance.helpers import rytov_variance as _rytov_variance  # noqa: F401
from disturbance.sensor_noise import apply_sensor_noise
from disturbance.state import (
    _cam_motion_state_global,
    _elapsed_dt,
    _turb_state,
    _vib_state,
    reset_camera_motion_state,
    reset_disturbance_state,
    reset_turbulence_state,
    reset_vibration_state,
)
from disturbance.turbulence import _kolmogorov_displacement, apply_turbulence
from disturbance.vibration import apply_platform_vibration

# Backward compat aliases — old helpers were named _r0_from_intensity / _rytov_variance
# Keep them exposed for any external test that might import them
__all__ = [
    "apply_sensor_noise",
    "apply_turbulence",
    "apply_platform_vibration",
    "apply_camera_motion",
    "apply_camera_motion_with_state",
    "reset_disturbance_state",
    "reset_turbulence_state",
    "reset_vibration_state",
    "reset_camera_motion_state",
    "_turb_state",
    "_vib_state",
    "_cam_motion_state_global",
    "_elapsed_dt",
    "_kolmogorov_displacement",
    "_r0_from_intensity",
    "_rytov_variance",
]
