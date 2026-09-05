# disturbance/camera_motion.py - Camera drift — Ornstein-Uhlenbeck thermal/mount, well-commented

import math

import numpy as np

from common.rng import get_rng

from disturbance.constants import CAMERA_TAU
from disturbance.dt_provider import DtProvider
from disturbance.state import _cam_motion_state_global

def apply_camera_motion(pan: float, tilt: float, intensity: float, dt: float | None = None, rng: np.random.Generator | None = None) -> tuple[float, float]:
    """
    Stateless wrapper — delegates to OU with global state, now dt-aware.

    Args:
      pan, tilt: pre-drift
      intensity: 0..10
      dt: seconds, sim-speed-scaled. If None, wall-clock fallback.

    Returns (pan_drifted, tilt_drifted).
    """
    return apply_camera_motion_with_state(pan, tilt, float(intensity), _cam_motion_state_global, dt=dt, rng=rng)

def apply_camera_motion_with_state(
    pan: float,
    tilt: float,
    intensity: float,
    state: dict | None = None,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    OU drift: dv = −v/τ dt + σ√(2/τ) dW,  dx = v dt

    Physics:
      τ=6.0 s (thermal), σ=0.42·I·(I/5)^{0.25} px/s, v clamped ±(2.2·I+1.5)
      bias RW ±0.012·I·√dt for slow thermal.

    Args:
      pan, tilt: pre-drift world pixels
      intensity: 0..10
      state: dict holding vx,vy,bias_pan/bias_tilt,_last_wall. If None, uses fresh dict.
      dt: seconds, sim-speed-scaled. If None, derives from wall time (fallback).

    Returns (pan+drift, tilt+drift).
    """
    if float(intensity) <= 0:
        return pan, tilt
    if state is None:
        state = {}
    dt = DtProvider.resolve(state, dt, key="_last_wall")

    _rng = get_rng(rng)
    tau = float(CAMERA_TAU)
    sigma_v = 0.42 * float(intensity) * (float(intensity)/5.0)**0.25
    vx = float(state.get("vx", 0.0))
    vy = float(state.get("vy", 0.0))
    alpha = math.exp(-float(dt) / float(tau))
    diff_scale = float(sigma_v) * math.sqrt(max(0.0, 1 - alpha**2))
    vx = vx * alpha + float(_rng.normal(0, 1)) * diff_scale
    vy = vy * alpha + float(_rng.normal(0, 1)) * diff_scale
    vmax = 2.2 * float(intensity) + 1.5
    vx = float(np.clip(vx, -vmax, vmax))
    vy = float(np.clip(vy, -vmax, vmax))
    state["vx"], state["vy"] = vx, vy
    dpan = vx * float(dt)
    dtilt = vy * float(dt)
    bias = float(state.get("bias_pan", 0.0) + float(_rng.normal(0, 0.012 * float(intensity) * math.sqrt(float(dt)))))
    bias2 = float(state.get("bias_tilt", 0.0) + float(_rng.normal(0, 0.012 * float(intensity) * math.sqrt(float(dt)))))
    bias = float(np.clip(bias, -0.4*float(intensity), 0.4*float(intensity)))
    bias2 = float(np.clip(bias2, -0.4*float(intensity), 0.4*float(intensity)))
    state["bias_pan"] = bias; state["bias_tilt"] = bias2
    dpan += bias * float(dt) * 0.3
    dtilt += bias2 * float(dt) * 0.3
    return pan + dpan, tilt + dtilt