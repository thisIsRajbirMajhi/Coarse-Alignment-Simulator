# disturbance/camera_jitter.py - Physical camera jitter — Gaussian with temporal correlation
# Robust-simple: jitter is now OU-filtered Gaussian (correlated, realistic shake) with
# amplitude mapped to sigma = amp/2.8 so ±20 px ~ 3σ coverage. Falls back to white when dt absent.

from __future__ import annotations

import math
import time

import numpy as np

from common.rng import get_rng

from disturbance.constants import CAMERA_JITTER_LIMITS
from disturbance.dt_provider import DtProvider


def _resolve_jitter_amp(intensity: float | None, jitter_px: float | None) -> float | None:
    if jitter_px is not None:
        if jitter_px > 20 and jitter_px <= 50:
            return float(np.clip(jitter_px, 0, 50))
        return float(np.clip(jitter_px, *CAMERA_JITTER_LIMITS))
    if intensity is not None:
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return None
        return (iv / 10.0) * 20.0
    return None


def apply_camera_jitter(
    pan: float,
    tilt: float,
    intensity: float | None = None,
    *,
    jitter_px: float | None = None,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    Apply per-frame camera jitter — OU-filtered Gaussian (correlated shake).

    Spec: Max Camera Jitter ±20 px/frame + user defined (0..50). Physical model:
      sigma = amp/2.8 so 99.5% samples within ±amp, OU tau=28ms gives high-freq
      correlated shake (like real mount resonance) that AI struggles with more than white jumps.

    Args:
      pan, tilt: pre-jitter world pixels
      intensity: legacy 0..10 maps to jitter = intensity/10 * 20 px
      jitter_px: direct max jitter in px (dominates)
      dt: seconds for OU correlation; if None -> white Gaussian fallback

    Returns (pan jittered, tilt jittered).
    """
    amp = _resolve_jitter_amp(intensity, jitter_px)
    if amp is None or amp <= 1e-9:
        return pan, tilt
    if dt is None:
        # White Gaussian fallback — isotropic, sigma = amp/2.8
        _rng = get_rng(rng)
        sigma = float(amp) / 2.8
        jx = float(_rng.normal(0, sigma))
        jy = float(_rng.normal(0, sigma))
        # Clip to ±amp to respect spec
        jx = float(np.clip(jx, -amp, amp))
        jy = float(np.clip(jy, -amp, amp))
        return pan + jx, tilt + jy
    # OU-filtered path — needs state; delegate to stateful version with temp state
    return apply_camera_jitter_with_state(pan, tilt, float(amp), state=None, dt=dt, rng=rng)


def apply_camera_jitter_with_state(
    pan: float,
    tilt: float,
    jitter_px: float,
    state: dict | None = None,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    Stateful OU jitter — correlated shake with dt-aware tau.

    State holds jx, jy, last_wall. Tau=28ms (mount resonance), sigma = amp/2.8
    """
    amp = float(np.clip(jitter_px, 0, 50)) if jitter_px is not None else 0.0
    if amp <= 1e-9:
        return pan, tilt
    if state is None:
        state = {}
    # Resolve dt
    dt_eff = DtProvider.resolve(state, dt, key="_jit_last_wall")
    sigma = amp / 2.8
    tau = 0.028  # 28 ms — high frequency but correlated
    alpha = math.exp(-float(dt_eff) / tau)
    # OU step: x = alpha*x_prev + sigma*sqrt(1-alpha^2)*N(0,1)
    _rng = get_rng(rng)
    scale = sigma * math.sqrt(max(0.0, 1 - alpha * alpha))
    prev_jx = float(state.get("jx", 0.0))
    prev_jy = float(state.get("jy", 0.0))
    jx = prev_jx * alpha + float(_rng.normal(0, 1)) * scale
    jy = prev_jy * alpha + float(_rng.normal(0, 1)) * scale
    # Occasional impulse for mount knock (2% chance, 1.8x amp) — challenging for AI
    if _rng.random() < 0.02:
        jx += float(_rng.normal(0, sigma * 0.55))
        jy += float(_rng.normal(0, sigma * 0.55))
    jx = float(np.clip(jx, -amp, amp))
    jy = float(np.clip(jy, -amp, amp))
    state["jx"], state["jy"] = jx, jy
    return pan + jx, tilt + jy
