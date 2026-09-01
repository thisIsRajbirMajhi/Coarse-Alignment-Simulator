# disturbance/camera_jitter.py - Camera Jitter — per-frame uniform +-20px, user configurable

from __future__ import annotations

import math

import numpy as np

from disturbance.constants import CAMERA_JITTER_LIMITS


def apply_camera_jitter(
    pan: float,
    tilt: float,
    intensity: float | None = None,
    *,
    jitter_px: float | None = None,
    dt: float | None = None,
) -> tuple[float, float]:
    """
    Apply per-frame uniform camera jitter ± jitter_px (px) isotropic.

    Spec: Max Camera Jitter +- 20 px / frame + user defined (0..20, extended to 50 via override).
    Stateless — independent each frame (white uniform).

    Args:
      pan, tilt: pre-jitter world pixels
      intensity: legacy 0..10 maps to jitter = intensity/10 * 20 px (10 => 20px)
      jitter_px: direct max jitter in px (dominates over intensity if given)
      dt: unused, kept for API symmetry with other disturbances

    Returns (pan jittered, tilt jittered).
    """
    # Resolve jitter amplitude
    if jitter_px is not None:
        amp = float(np.clip(jitter_px, *CAMERA_JITTER_LIMITS))
        # allow user-defined extended beyond 20 if caller passes >20 but <50 via manual clip
        # we keep clip at 20 for standard, but if max user 50 requested, extend
        # here we honour passed jitter_px up to 50 if >20
        if jitter_px > 20 and jitter_px <= 50:
            amp = float(np.clip(jitter_px, 0, 50))
    elif intensity is not None:
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return pan, tilt
        amp = (iv / 10.0) * 20.0  # 10 -> 20px
    else:
        return pan, tilt

    if amp <= 1e-9:
        return pan, tilt

    # Uniform +-amp independent per axis (spec: +- 20 px/frame)
    jx = float(np.random.uniform(-amp, amp))
    jy = float(np.random.uniform(-amp, amp))
    return pan + jx, tilt + jy


def apply_camera_jitter_with_state(
    pan: float,
    tilt: float,
    jitter_px: float,
    state: dict | None = None,
    dt: float | None = None,
) -> tuple[float, float]:
    """
    Stateful variant kept for symmetry with apply_camera_motion_with_state.
    Jitter is white, so state unused except for last_wall tracking if needed.
    """
    return apply_camera_jitter(pan, tilt, jitter_px=jitter_px, dt=dt)
