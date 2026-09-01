# disturbance/state.py - Temporal state + reset for reproducible, wall-clock-decoupled simulation

import time
from contextlib import contextmanager

import numpy as np

from disturbance.dt_provider import DtProvider

class DisturbanceState:
    """
    Isolated disturbance state — per-simulation or per-test instance.

    Holds turbulence, vibration, camera drift, platform motion, and jitter dicts without global leakage.
    Use isolated_state() context for test isolation:

      with DisturbanceState.isolated():
          apply_turbulence(frame, intensity, dt=0.033)
    """

    def __init__(self):
        self.turb: dict = {"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None}
        self.vib: dict = {"t": 0.0, "last_wall": None, "phases": None}
        self.cam_global: dict = {}
        self.platform: dict = {"t": 0.0, "_pm_last_wall": None}
        self.jitter: dict = {"_last_wall": None}

    def reset(self) -> None:
        self.turb.clear(); self.turb.update({"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None})
        self.vib.clear(); self.vib.update({"t": 0.0, "last_wall": None, "phases": None})
        self.vib.pop("ou_pan", None); self.vib.pop("ou_tilt", None)
        self.cam_global.clear()
        self.platform.clear(); self.platform.update({"t": 0.0, "_pm_last_wall": None})
        self.jitter.clear()

    @contextmanager
    def isolated(self):
        # Context that temporarily swaps module globals with this instance's dicts
        import disturbance.state as _mod
        old_turb, old_vib, old_cam = _mod._turb_state, _mod._vib_state, _mod._cam_motion_state_global
        old_platform, old_jitter = _mod._platform_state_global, _mod._jitter_state_global
        _mod._turb_state, _mod._vib_state, _mod._cam_motion_state_global = self.turb, self.vib, self.cam_global
        _mod._platform_state_global, _mod._jitter_state_global = self.platform, self.jitter
        try:
            yield self
        finally:
            _mod._turb_state, _mod._vib_state, _mod._cam_motion_state_global = old_turb, old_vib, old_cam
            _mod._platform_state_global, _mod._jitter_state_global = old_platform, old_jitter

    @classmethod
    @contextmanager
    def isolated_state(cls):
        inst = cls()
        with inst.isolated():
            yield inst

# Module globals — singleton for backward compat (points to default instance)
_default_state = DisturbanceState()
_turb_state: dict = _default_state.turb
_vib_state: dict = _default_state.vib
_cam_motion_state_global: dict = _default_state.cam_global
_platform_state_global: dict = _default_state.platform
_jitter_state_global: dict = _default_state.jitter

def _elapsed_dt(state: dict, fallback: float = 0.033) -> float:
    """
    Derive dt from wall time when explicit dt not supplied — delegates to DtProvider.
    """
    # Use DtProvider for single-source clipping; fallback via clip
    dt = DtProvider.resolve(state, None, clip=(0.005, 0.08))
    # First call fallback: DtProvider returns 0.005 on first, but we want 0.033
    if state.get("_first_call_done") is None:
        # Detect first call: if dx/dy etc were None previously, DtProvider already set last_wall
        # For backward compat, return fallback on first if state was fresh
        # Heuristic: if t == 0.0 and phases is None, it's first call — return fallback
        if state.get("t", 0.0) == 0.0 and state.get("phases") is None:
            return float(fallback)
    return dt

def reset_disturbance_state() -> None:
    """
    Clear all module-level temporal state.

    - Turbulence: clears dx/dy/phase/last_wall/t
    - Vibration: clears phases/t/last_wall/ou_pan/ou_tilt
    - Camera drift: clears global vx/vy/bias/last_wall
    - Platform motion: clears trajectory state
    - Jitter: clears jitter wall tracking

    Call from GUI _reset() so a "fresh" run doesn't inherit stale phase/velocity.
    Idempotent; safe to call even if states already empty.
    """
    _turb_state.clear()
    _turb_state.update({"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None})

    _vib_state.clear()
    _vib_state.update({"t": 0.0, "last_wall": None, "phases": None})
    # Also clear OU state if present
    _vib_state.pop("ou_pan", None)
    _vib_state.pop("ou_tilt", None)

    _cam_motion_state_global.clear()
    _platform_state_global.clear()
    _platform_state_global.update({"t": 0.0, "_pm_last_wall": None})
    _jitter_state_global.clear()

# Also clear per-call camera Motion state dicts passed explicitly:
# Caller should pass a fresh dict or call reset_disturbance_state() which clears global;
# per-instance dicts (e.g., MainWindow._camera_drift_state) should be cleared by caller:
#   self._camera_drift_state.clear()

def reset_vibration_state() -> None:
    """Reset only vibration state (granular)."""
    _vib_state.clear()
    _vib_state.update({"t": 0.0, "last_wall": None, "phases": None})

def reset_turbulence_state() -> None:
    """Reset only turbulence state."""
    _turb_state.clear()
    _turb_state.update({"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None})

def reset_camera_motion_state() -> None:
    """Reset only global camera drift state."""
    _cam_motion_state_global.clear()

def reset_platform_motion_state() -> None:
    """Reset only platform motion state."""
    _platform_state_global.clear()
    _platform_state_global.update({"t": 0.0, "_pm_last_wall": None})

def reset_jitter_state() -> None:
    """Reset only jitter state."""
    _jitter_state_global.clear()