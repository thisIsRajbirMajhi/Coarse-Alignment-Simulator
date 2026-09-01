# target/factory.py - Beacon collection creation — deterministic spread, seed-driven, config-aware

from __future__ import annotations

import math

import numpy as np

from target.motion import MotionProfile, Target

# Optional config integration (soft import)
try:
    from target.config import BeaconConfig, MultiBeaconConfig
except Exception:
    BeaconConfig = None  # type: ignore
    MultiBeaconConfig = None  # type: ignore

def create_beacons(
    count: int,
    bounds: tuple[int, int],
    profile: MotionProfile | str,
    speed: float,
    seed: int | None = 42,
    hitbox_radius: int = 14,
    center_radius: int = 2,
    brightness: int = 255,
    radius: int = 5,
    shape: str = "square",
    size_w: int = 10,
    size_h: int = 10,
    blinking: bool = False,
    x: float | None = None,
    y: float | None = None,
    speed_random: bool = False,
) -> list[Target]:
    """
    Factory to create one or more beacons spread across world.

    - Stratified placement 18%..82% of world with de-overlap (6 attempts, 2.2*hitbox).
    - Speed jitter ±12% per extra beacon (for realism).
    - Profile: first beacon uses requested profile, others random.
    - Deterministic via seed (np.random.default_rng(seed)).

    Back-compat signature — tests and legacy app call this.
    """
    # Normalize profile — handle display names
    def _norm_profile(p):
        mapping = {
            "straight line": "linear",
            "straight_line": "linear",
            "circular": "curved",
            "figure 8": "figure_eight",
            "figure8": "figure_eight",
            "spiral": "spiral",
            "sin": "sinusoidal",
            "sinusoidal": "sinusoidal",
            "zig-zag": "zigzag",
            "zigzag": "zigzag",
            "random": "random",
        }
        s = str(p).lower().strip()
        s = mapping.get(s, s)
        if s == "random":
            return "random"
        try:
            return MotionProfile(s)
        except:
            return MotionProfile.CURVED

    is_random_profile = str(profile).lower().strip() in ("random", "random walk", "random_motion")
    # Also check normalized
    try:
        norm = _norm_profile(profile)
        is_random_profile = (norm == "random")
        prof_base = norm if not is_random_profile else None
    except:
        is_random_profile = False
        prof_base = MotionProfile.CURVED

    # Normalize shape
    shape_norm = str(shape).lower() if shape else "square"
    is_random_shape = shape_norm == "random"
    shape_base = shape_norm if not is_random_shape else "square"

    rng = np.random.default_rng(seed)
    beacons: list[Target] = []
    w, h = bounds
    n = int(np.clip(int(count), 1, 5))
    # Derive radius from size for backward compat
    radius_from_size = int(max(size_w, size_h) / 2) if size_w and size_h else int(radius)
    radius_from_size = int(np.clip(radius_from_size, 1, 15))
    for i in range(n):
        # Placement: if single beacon and x,y provided, use it; else stratified random
        if n == 1 and x is not None and y is not None:
            xi, yi = float(x), float(y)
        elif i == 0 and x is not None and y is not None and n == 1:
            xi, yi = float(x), float(y)
        else:
            xi = float(rng.uniform(w*0.18, w*0.82))
            yi = float(rng.uniform(h*0.18, h*0.82))
            for _ in range(6):
                too_close = any(math.hypot(xi - b.x, yi - b.y) < hitbox_radius*2.2 for b in beacons)
                if not too_close:
                    break
                xi = float(rng.uniform(w*0.15, w*0.85))
                yi = float(rng.uniform(h*0.15, h*0.85))
        # Speed
        if speed_random:
            sp = float(rng.uniform(20, 150))
        else:
            sp = float(speed)
            if n > 1:
                sp = float(np.clip(rng.normal(speed, speed*0.12), speed*0.55, speed*1.45)) if not is_random_profile else float(rng.uniform(20, 120))
        # Profile
        if is_random_profile:
            prof_i = rng.choice(list(MotionProfile))
        else:
            prof_i = prof_base if prof_base is not None else rng.choice(list(MotionProfile))
        # Shape
        shape_i = rng.choice(["square", "circle"]) if is_random_shape else shape_base
        beacons.append(
            Target(
                xi, yi, prof_i, sp, bounds,
                seed=int(rng.integers(0, 999999)),
                brightness=int(brightness), radius=int(radius_from_size),
                hitbox_radius=int(hitbox_radius), center_radius=int(center_radius),
                beacon_id=int(i),
                shape=str(shape_i), size_w=int(size_w), size_h=int(size_h), blinking=bool(blinking),
            )
        )
    return beacons

def create_beacons_with_configs(
    multi_config: "MultiBeaconConfig",
    bounds: tuple[int, int],
    global_seed: int | None = 42,
) -> list[Target]:
    if MultiBeaconConfig is None:
        return create_beacons(
            multi_config.beacon_count if hasattr(multi_config, "beacon_count") else 1,
            bounds, "curved", 60.0, seed=global_seed,
        )
    cfg = multi_config.validate()
    # Use shared config for all beacons
    return create_beacons(
        count=int(cfg.beacon_count),
        bounds=bounds,
        profile=str(getattr(cfg, "profile", "curved")),
        speed=float(getattr(cfg, "speed", 60.0)),
        seed=int(global_seed) if global_seed is not None else 42,
        hitbox_radius=14,
        center_radius=2,
        brightness=255,
        radius=int(max(getattr(cfg, "size_w", 10), getattr(cfg, "size_h", 10)) / 2),
        shape=str(getattr(cfg, "shape", "square")),
        size_w=int(getattr(cfg, "size_w", 10)),
        size_h=int(getattr(cfg, "size_h", 10)),
        blinking=bool(getattr(cfg, "blinking", False)),
        x=float(getattr(cfg, "x", 2500.0)) if cfg.beacon_count == 1 else None,
        speed_random=bool(getattr(cfg, "speed_random", False)),
        y=float(getattr(cfg, "y", 2500.0)) if cfg.beacon_count == 1 else None,
    )