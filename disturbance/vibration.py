# disturbance/vibration.py - Harmonic platform vibration — jitter PSD + OU micro-vibration, well-commented

import math

import numpy as np

from common.rng import get_rng

from disturbance.constants import VIBRATION_BASE_AMPS, VIBRATION_FREQS, VIBRATION_OU_TAU
from disturbance.dt_provider import DtProvider
from disturbance.state import _vib_state

def apply_platform_vibration(
    pan: float,
    tilt: float,
    intensity: float,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    Harmonic vibration model — dt-aware, wall-clock fallback.

    Model:
      θ(t)= Σ A_i(I)·sin(2π f_i t+φ_i) + η_OU(t)
      f=[7,18,35,72,150] Hz, ζ≈0.06, OU τ=22 ms, σ=0.18·I

    Args:
      pan, tilt: world pixels (pre-vibration)
      intensity: 0..10
      dt: seconds, sim-speed-scaled. If None, derives from wall time.

    Returns (pan_jittered, tilt_jittered).
    """
    if intensity <= 0:
        return pan, tilt
    dt = DtProvider.resolve(_vib_state, dt)

    freqs = np.array(VIBRATION_FREQS, dtype=float)
    base_amps = np.array(VIBRATION_BASE_AMPS, dtype=float)
    scale = (float(intensity) / 5.0) ** 0.9 if float(intensity) > 0 else 0.0
    amps = base_amps * float(scale)

    _rng = get_rng(rng)
    if _vib_state.get("phases") is None or len(_vib_state["phases"]) != len(freqs):
        _vib_state["phases"] = _rng.uniform(0, 2*math.pi, size=len(freqs))
        _vib_state["t"] = 0.0
        _vib_state["ou_pan"] = 0.0
        _vib_state["ou_tilt"] = 0.0

    t = float(_vib_state.get("t", 0.0) + float(dt))
    _vib_state["t"] = t
    phases = _vib_state["phases"]
    phases = phases + 2 * math.pi * freqs * float(dt)
    _vib_state["phases"] = phases

    jitter_pan_h = float(np.sum(amps * np.sin(phases)))
    jitter_tilt_h = float(np.sum(amps * np.sin(phases + 0.9)))

    tau_ou = float(VIBRATION_OU_TAU)
    sigma_ou = 0.18 * float(intensity)
    alpha_ou = math.exp(-float(dt) / float(tau_ou))
    ou_scale = float(sigma_ou) * math.sqrt(max(0.0, 1 - alpha_ou**2))
    ou_pan = float(_vib_state.get("ou_pan", 0.0) * alpha_ou + _rng.normal(0, 1) * ou_scale)
    ou_tilt = float(_vib_state.get("ou_tilt", 0.0) * alpha_ou + _rng.normal(0, 1) * ou_scale)
    _vib_state["ou_pan"] = ou_pan
    _vib_state["ou_tilt"] = ou_tilt

    if float(intensity) > 7:
        jitter_pan_h += float(_rng.normal(0, 0.18 * (float(intensity)-7)))
        jitter_tilt_h += float(_rng.normal(0, 0.18 * (float(intensity)-7)))

    return pan + jitter_pan_h + ou_pan, tilt + jitter_tilt_h + ou_tilt