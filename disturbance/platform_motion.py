# disturbance/platform_motion.py - Platform Motion — +-20 px/frame, Linear default + Circular/Random/Spiral/Figure 8/Sin/Zig-Zag

from __future__ import annotations

import math

import numpy as np

from common.rng import get_rng

from disturbance.constants import PLATFORM_MAX_PX_PER_FRAME, PLATFORM_PROFILE_MAP
from disturbance.dt_provider import DtProvider

# Internal defaults for profile geometry
_DEFAULT_ORBIT_RADIUS = 90.0
_DEFAULT_AMPLITUDE = 110.0


def _normalize_profile(profile: str) -> str:
    p = str(profile).strip()
    # direct map
    if p in PLATFORM_PROFILE_MAP:
        return PLATFORM_PROFILE_MAP[p]
    low = p.lower().replace(" ", "_").replace("-", "_")
    if low in PLATFORM_PROFILE_MAP.values():
        return low
    if low in ("straight_line", "straight", "line"):
        return "linear"
    if low in ("circle", "circular", "orbit", "elliptical"):
        return "circular"
    if low in ("fig_8", "fig8", "figure8", "figure_8"):
        return "figure_8"
    if low == "sinusoidal":
        return "sin"
    if low in ("zig_zag", "zigzag"):
        return "zigzag"
    # fallback linear (mandatory default)
    return "linear"


def apply_platform_motion(
    pan: float,
    tilt: float,
    intensity: float | None = None,
    *,
    profile: str = "Linear",
    speed_px_per_frame: float | None = None,
    dt: float | None = None,
    state: dict | None = None,
    bounds: tuple[int, int] | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    Platform motion disturbance — moves camera/platform per frame with selectable trajectory.

    Spec:
      Platform Motion: +- 20 px/frame (MAX) + User configurable
      Default/Mandatory: Linear | Optional: Circular, Random, Spiral, Figure 8, Sin, Zig-Zag

    Args:
      pan, tilt: world pixels before platform motion
      intensity: legacy 0..10 controls speed = intensity/10 * 20 px/frame
      profile: display name or key. Must be one of PLATFORM_PROFILE_MAP keys.
      speed_px_per_frame: 0..20 px per frame (user configurable). At 30FPS => px/s = speed*30.
                          If given, dominates over intensity.
      dt: seconds (sim-speed-scaled). If None, wall-clock via DtProvider.
      state: dict holding per-profile state (t, heading, orbit_phase, etc.). Stateless if None -> fresh dict.
      bounds: (W,H) world size for bounce/clamp; if None, unconstrained (no bounce).

    Returns (pan_offset, tilt_offset) after platform motion step.
    Motion is additive delta for this frame (integrated via dx,dy = v*dt).

    Note: profile 'Linear' is mandatory default. Others are optional.
    """
    if state is None:
        state = {}
    _rng = get_rng(rng)

    # Resolve speed px/frame -> px/s via dt. We need dt first.
    dt_resolved = DtProvider.resolve(state, dt, key="_pm_last_wall") if dt is None else float(np.clip(dt, 0.005, 0.08))
    # If caller supplied dt explicitly, we still want to update wall but not double-clip beyond 0.08 already
    if dt is not None:
        # Ensure state last_wall updated for fallback later
        try:
            import time
            state["_pm_last_wall"] = time.time()
        except: pass

    # Resolve speed
    if speed_px_per_frame is not None:
        speed_frame = float(np.clip(speed_px_per_frame, 0, PLATFORM_MAX_PX_PER_FRAME))
        # allow user-defined beyond 20 up to 40 if they explicitly request >20 (spec says MAX 20 but User configurable)
        if speed_px_per_frame is not None and 20 < speed_px_per_frame <= 50:
            speed_frame = float(np.clip(speed_px_per_frame, 0, 50))
    elif intensity is not None:
        iv = float(np.clip(intensity, 0, 10))
        if iv <= 0:
            return pan, tilt
        speed_frame = (iv / 10.0) * PLATFORM_MAX_PX_PER_FRAME  # 10 => 20
    else:
        # No speed given -> default small
        speed_frame = 5.0

    if speed_frame <= 1e-9:
        return pan, tilt

    # Convert px/frame to px/s: speed_px_per_frame is conceptual at 30 FPS, so px/s = speed_frame * 30
    # But_dt is already ~0.033 at 30Hz. So delta = speed_frame * (dt*30) ??? Let's treat speed_frame as px per 33ms.
    # To make frame-rate independent: velocity_px_s = speed_frame / 0.033 = speed_frame * 30.303
    # Then delta = velocity_px_s * dt
    # This keeps +-20 px per 33ms frame consistent regardless of actual dt variation.
    vel_scale = 30.303030303  # 1/0.033
    speed_px_s = speed_frame * vel_scale

    key = _normalize_profile(profile)

    # Initialize state lazily
    if "t" not in state:
        state["t"] = 0.0
    if "heading" not in state:
        # random heading but deterministic per state
        state["heading"] = float(_rng.uniform(0, 2 * math.pi))
    if "orbit_phase" not in state:
        state["orbit_phase"] = float(_rng.uniform(0, 2 * math.pi))
    if "rw_vx" not in state:
        # random walk velocity
        state["rw_vx"] = float(_rng.normal(0, speed_px_s * 0.25))
        state["rw_vy"] = float(_rng.normal(0, speed_px_s * 0.25))
    if "zig_next_turn" not in state:
        state["zig_next_turn"] = float(_rng.uniform(1.0, 2.0))
    if "fe_A" not in state:
        state["fe_A"] = _DEFAULT_AMPLITUDE
        state["fe_B"] = _DEFAULT_AMPLITUDE * 0.55
        state["fe_omega"] = speed_px_s / max(_DEFAULT_AMPLITUDE, 1)
    if "sp_r" not in state:
        state["sp_r"] = 45.0
        state["sp_max_r"] = 180.0
        state["sp_omega"] = speed_px_s / 80.0
        state["sp_expand_rate"] = 0.5
    if "sin_phase" not in state:
        state["sin_phase"] = float(_rng.uniform(0, 2 * math.pi))
        state["sin_cy"] = 0.0  # will be centred

    t = float(state["t"] + dt_resolved)
    state["t"] = t

    dx = 0.0
    dy = 0.0

    if key == "linear":
        # Constant velocity with bounce at bounds if known, else no clamp
        hdg = float(state["heading"])
        vx = speed_px_s * math.cos(hdg)
        vy = speed_px_s * math.sin(hdg)
        dx = vx * dt_resolved
        dy = vy * dt_resolved
        # Bounce logic if bounds given
        if bounds is not None:
            w, h = bounds
            nx = pan + dx
            ny = tilt + dy
            bounced = False
            if nx <= 0 or nx >= w:
                # reflect heading horizontally
                hdg = math.pi - hdg
                bounced = True
                dx = speed_px_s * math.cos(hdg) * dt_resolved
            if ny <= 0 or ny >= h:
                hdg = -hdg
                bounced = True
                dy = speed_px_s * math.sin(hdg) * dt_resolved
            if bounced:
                state["heading"] = float(hdg % (2 * math.pi))
        # Store velocity for introspection
        state["vx"] = float(speed_px_s * math.cos(float(state["heading"])))
        state["vy"] = float(speed_px_s * math.sin(float(state["heading"])))


    elif key == "circular":
        # Circular orbit around origin (delta, not absolute) — tangential velocity
        omega = speed_px_s / max(_DEFAULT_ORBIT_RADIUS, 1)
        # small eccentricity phase noise
        state["orbit_phase"] = float(state["orbit_phase"] + omega * dt_resolved)
        phi = float(state["orbit_phase"])
        # Use finite diff to get delta: integrate velocity tangential
        # vx = -R*omega*sin(phi), vy = R*omega*cos(phi)
        R = float(_DEFAULT_ORBIT_RADIUS)
        # optional small random wobble
        R_eff = R * (1.0 + 0.06 * math.sin(t * 0.9))
        vx = -R_eff * omega * math.sin(phi)
        vy = R_eff * omega * math.cos(phi)
        dx = vx * dt_resolved
        dy = vy * dt_resolved

    elif key == "random":
        # Langevin / OU random walk, similar to target random_walk
        damping = 2.0
        noise_scale = speed_px_s * 1.7
        rx = float(_rng.normal(0, 1))
        ry = float(_rng.normal(0, 1))
        state["rw_vx"] = float(state["rw_vx"] + (-damping * state["rw_vx"] * dt_resolved + rx * noise_scale * math.sqrt(dt_resolved)))
        state["rw_vy"] = float(state["rw_vy"] + (-damping * state["rw_vy"] * dt_resolved + ry * noise_scale * math.sqrt(dt_resolved)))
        # clamp magnitude
        vmax = speed_px_s * 1.6
        vmag = math.hypot(float(state["rw_vx"]), float(state["rw_vy"]))
        if vmag > vmax:
            scale = vmax / (vmag + 1e-9)
            state["rw_vx"] *= scale
            state["rw_vy"] *= scale
        dx = float(state["rw_vx"] * dt_resolved)
        dy = float(state["rw_vy"] * dt_resolved)
        # Clamp delta to +-20 per frame spec even after clamp
        max_delta = speed_frame * 1.2
        dx = float(np.clip(dx, -max_delta, max_delta))
        dy = float(np.clip(dy, -max_delta, max_delta))

    elif key == "spiral":
        # Pulsating radius + angular
        r_range = float(state["sp_max_r"] - 45.0)
        puls = 0.5 + 0.5 * math.sin(float(state["sp_expand_rate"]) * t)
        r = 45.0 + r_range * puls
        omega_sp = float(state["sp_omega"])
        angle = omega_sp * t
        # velocity = radial + tangential
        drdt = r_range * 0.5 * float(state["sp_expand_rate"]) * math.cos(float(state["sp_expand_rate"]) * t)
        vx = drdt * math.cos(angle) - r * omega_sp * math.sin(angle)
        vy = drdt * math.sin(angle) + r * omega_sp * math.cos(angle)
        dx = vx * dt_resolved
        dy = vy * dt_resolved
        # Normalise to max speed so spiral still respects max px/frame
        # Scale if exceeds max_delta
        max_delta = speed_frame
        mag = math.hypot(dx, dy)
        if mag > max_delta and mag > 1e-9:
            scale = max_delta / mag
            dx *= scale
            dy *= scale

    elif key == "figure_8":
        # Lissajous figure-8 with frequency wobble
        A = float(state["fe_A"])
        B = float(state["fe_B"])
        omega = float(state["fe_omega"])
        omega_eff = omega * (1.0 + 0.06 * math.sin(t * 0.7))
        # Velocity
        vx = A * omega_eff * math.cos(omega_eff * t)
        vy = B * 2 * omega_eff * math.cos(2 * omega_eff * t)
        dx = vx * dt_resolved
        dy = vy * dt_resolved
        max_delta = speed_frame * 1.1
        mag = math.hypot(dx, dy)
        if mag > max_delta and mag > 1e-9:
            dx *= max_delta / mag
            dy *= max_delta / mag

    elif key == "sin":
        # Sinusoidal horizontal scan + slow vertical drift
        amp = float(_DEFAULT_AMPLITUDE)
        omega = speed_px_s / max(amp, 1) * 0.85
        phase = float(state["sin_phase"])
        vx = amp * omega * math.cos(omega * t + phase)
        # vertical small component
        vy = (amp * 0.22) * (omega * 0.55) * -math.sin(omega * 0.55 * t + phase)
        dx = vx * dt_resolved
        dy = vy * dt_resolved

    elif key == "zigzag":
        # Straight segments with periodic heading flips
        state["zig_next_turn"] = float(state["zig_next_turn"] - dt_resolved)
        if float(state["zig_next_turn"]) <= 0:
            turn = float(_rng.uniform(55, 120)) * math.pi / 180.0
            if _rng.random() < 0.5:
                turn = -turn
            state["heading"] = float((state["heading"] + turn) % (2 * math.pi))
            state["zig_next_turn"] = float(_rng.uniform(1.0, 1.8))
        hdg = float(state["heading"])
        vx = speed_px_s * math.cos(hdg)
        vy = speed_px_s * math.sin(hdg)
        dx = vx * dt_resolved
        dy = vy * dt_resolved
        if bounds is not None:
            w, h = bounds
            nx = pan + dx
            ny = tilt + dy
            if nx <= 0 or nx >= w or ny <= 0 or ny >= h:
                # bounce and reset turn timer
                hdg = float((hdg + math.pi * 0.5 + _rng.uniform(-0.3, 0.3)) % (2 * math.pi))
                state["heading"] = hdg
                state["zig_next_turn"] = float(_rng.uniform(0.8, 1.5))
                dx = speed_px_s * math.cos(hdg) * dt_resolved
                dy = speed_px_s * math.sin(hdg) * dt_resolved

    else:
        # fallback linear
        hdg = float(state["heading"])
        dx = speed_px_s * math.cos(hdg) * dt_resolved
        dy = speed_px_s * math.sin(hdg) * dt_resolved

    # Final global clamp to +-20 px/frame spec (supports user-defined beyond but warns)
    # Clamp delta to max allowed per frame (speed_frame is already clipped, but per-profile mag may overshoot)
    max_allowed = float(np.clip(speed_frame * 1.05, 0, 50))
    dx = float(np.clip(dx, -max_allowed, max_allowed))
    dy = float(np.clip(dy, -max_allowed, max_allowed))

    return pan + dx, tilt + dy


def _platform_state_reset(state: dict) -> None:
    """Clear platform motion state dict."""
    state.clear()
