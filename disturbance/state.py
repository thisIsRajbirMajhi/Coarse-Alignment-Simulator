"""
Module: disturbance.state
Purpose: Global temporal state + reset for reproducible, wall-clock-decoupled simulation.
Public API: _turb_state, _vib_state, _cam_motion_state_global, _elapsed_dt, reset_disturbance_state
Notes: Extracted from disturbances.py monolith — centralizes wall-clock fallback
       and provides explicit reset for GUI _reset() handler.
"""

import time

import numpy as np

# ============================================================
# SECTION: Global state — temporal correlation
# ============================================================

# Turbulence — displacement fields + phase + wall time
_turb_state: dict = {"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None}

# Vibration — harmonic phases + OU state + wall time
_vib_state: dict = {"t": 0.0, "last_wall": None, "phases": None}

# Camera drift — global OU state (used by apply_camera_motion wrapper)
_cam_motion_state_global: dict = {}

# ============================================================
# SECTION: Wall-clock fallback — dt inference
# ============================================================

def _elapsed_dt(state: dict, fallback: float = 0.033) -> float:
    """
    Derive dt from wall time when explicit dt not supplied.

    - Updates state["last_wall"] to now.
    - Returns clipped dt in [0.005, 0.08] s.
    - Falls back to 0.033 s on first call.
    """
    now = time.time()
    last = state.get("last_wall")
    state["last_wall"] = now
    if last is None:
        return float(fallback)
    dt = now - last
    return float(np.clip(dt, 0.005, 0.08))

# ============================================================
# SECTION: Explicit reset — for GUI reproducibility
# ============================================================

def reset_disturbance_state() -> None:
    """
    Clear all module-level temporal state.

    - Turbulence: clears dx/dy/phase/last_wall/t
    - Vibration: clears phases/t/last_wall/ou_pan/ou_tilt
    - Camera drift: clears global vx/vy/bias/last_wall

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
