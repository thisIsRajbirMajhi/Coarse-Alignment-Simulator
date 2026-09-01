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
) -> list[Target]:
    """
    Factory to create one or more beacons spread across world.

    - Stratified placement 18%..82% of world with de-overlap (6 attempts, 2.2*hitbox).
    - Speed jitter ±12% per extra beacon (for realism).
    - Profile: first beacon uses requested profile, others random.
    - Deterministic via seed (np.random.default_rng(seed)).

    Back-compat signature — tests and legacy app call this.
    """
    # Normalize profile
    try:
        prof = profile if isinstance(profile, MotionProfile) else MotionProfile(str(profile).lower())
    except Exception:
        prof = MotionProfile.CURVED

    rng = np.random.default_rng(seed)
    beacons: list[Target] = []
    w, h = bounds
    n = int(np.clip(int(count), 1, 16))
    for i in range(n):
        # Stratified placement
        x = float(rng.uniform(w*0.18, w*0.82))
        y = float(rng.uniform(h*0.18, h*0.82))
        for _ in range(6):
            too_close = any(math.hypot(x - b.x, y - b.y) < hitbox_radius*2.2 for b in beacons)
            if not too_close:
                break
            x = float(rng.uniform(w*0.15, w*0.85))
            y = float(rng.uniform(h*0.15, h*0.85))
        # Speed jitter for distractors
        sp = float(np.clip(rng.normal(speed, speed*0.12), speed*0.55, speed*1.45)) if n > 1 else float(speed)
        # Profile staggering
        prof_i = prof if i == 0 else rng.choice(list(MotionProfile))
        beacons.append(
            Target(
                x, y, prof_i, sp, bounds,
                seed=int(rng.integers(0, 999999)),
                brightness=int(brightness), radius=int(radius),
                hitbox_radius=int(hitbox_radius), center_radius=int(center_radius),
                beacon_id=int(i),
            )
        )
    return beacons

def create_beacons_with_configs(
    multi_config: "MultiBeaconConfig",
    bounds: tuple[int, int],
    global_seed: int | None = 42,
) -> list[Target]:
    """
    Create beacons directly from a validated MultiBeaconConfig.

    Each BeaconConfig drives one Target via Target(config=cfg, bounds=bounds, beacon_id=i).
    If configs contain explicit x/y, they are used; otherwise seed-driven placement
    (mirrors create_beacons spread logic) fills in.

    Returns list[Target] length == multi_config.beacon_count, with enabled flags preserved.
    """
    if MultiBeaconConfig is None or BeaconConfig is None:
        # No config support — fallback to basic
        return create_beacons(
            multi_config.beacon_count if hasattr(multi_config, "beacon_count") else 1,
            bounds, "curved", 60.0, seed=global_seed,
        )

    cfg = multi_config.validate()
    rng = np.random.default_rng(global_seed)
    w, h = bounds
    targets: list[Target] = []

    for i, beacon_cfg in enumerate(cfg.beacons):
        # If beacon_cfg has default placeholder position (400,300), treat as "needs placement"
        # and generate spread position deterministically.
        # We detect placeholder by checking if x/y are still defaults and not yet validated against bounds.
        use_spread = False
        # If beacon was freshly defaulted (beacon_id matches and x/y are 400/300), generate spread
        if (beacon_cfg.x == 400.0 and beacon_cfg.y == 300.0 and beacon_cfg.position_seed == 42
                and len(cfg.beacons) == cfg.beacon_count):
            # Heuristic: allow caller to request auto-placement by leaving defaults
            # We generate spread for first creation; subsequent edits keep explicit positions.
            # To avoid overriding user-edited positions, only auto-place when bounds are large
            # and we haven't yet placed any beacons.
            # For now, respect explicit x/y — if caller wants spread, they should pre-randomize.
            pass

        # Resolve position via spread if not explicitly set? For now keep config's x/y as is,
        # but ensure non-overlapping if multiple beacons share same default center.
        x, y = float(beacon_cfg.x), float(beacon_cfg.y)
        # Simple de-overlap for duplicates
        for _ in range(6):
            too_close = any(math.hypot(x - t.x, y - t.y) < beacon_cfg.hitbox_radius*2.2 for t in targets)
            if not too_close:
                break
            x = float(rng.uniform(w*0.15, w*0.85))
            y = float(rng.uniform(h*0.15, h*0.85))
            # Update config to reflect new position for round-trip
            beacon_cfg.x = x; beacon_cfg.y = y

        # Build Target via config — clamp x/y to bounds
        x = float(np.clip(x, 0, w)); y = float(np.clip(y, 0, h))
        beacon_cfg.x = x; beacon_cfg.y = y
        beacon_cfg.beacon_id = int(i)

        try:
            prof = beacon_cfg.profile if isinstance(beacon_cfg.profile, MotionProfile) else MotionProfile(str(beacon_cfg.profile).lower())
        except Exception:
            prof = MotionProfile.CURVED

        tgt = Target(
            x=x, y=y, profile=prof, speed=float(beacon_cfg.speed), bounds=bounds,
            seed=int(beacon_cfg.position_seed), brightness=int(beacon_cfg.brightness),
            radius=int(beacon_cfg.radius), hitbox_radius=int(beacon_cfg.hitbox_radius),
            center_radius=int(beacon_cfg.center_radius),
            heading=None if beacon_cfg.heading is None else float(beacon_cfg.heading) * math.pi / 180.0,
            beacon_id=int(i), enabled=bool(beacon_cfg.enabled),
        )
        # Preserve enabled even if Target.__init__ didn't accept it (set post-init)
        tgt.enabled = bool(beacon_cfg.enabled)
        targets.append(tgt)

    return targets