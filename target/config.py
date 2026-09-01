# target/config.py - Typed, validated configuration for Beacon/Target system

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import numpy as np

from common.config_base import BaseValidatedConfig, clip_field
from target.constants import BEACON_DEFAULTS, BEACON_LIMITS, MULTI_BEACON_DEFAULTS, MULTI_BEACON_LIMITS

if TYPE_CHECKING:
    from target.motion import MotionProfile, Target

@dataclass
class BeaconConfig(BaseValidatedConfig):
    """
    Per-beacon typed configuration (8 parameters + metadata).

    1) enabled            — Toggle beacon on/off (bool)
    2) profile            — Motion profile string (e.g., "linear", "curved")
    3) position_seed      — Random seed for starting position (0..999999)
    4) x, y               — Starting position (px, clamped to world bounds)
    5) speed              — Motion speed (px/s, 5..300)
    6) brightness         — Beacon intensity (0..255)
    7) radius             — Visual size (px, 1..15)
    8) hitbox_radius      — Valid detection radius (px, 3..80) — ≥ radius
    9) center_radius      — Precise center radius (px, 1..10) — ≤ hitbox
    + heading            — Initial heading deg (None=random) 0..360
    + beacon_id          — Stable index 0..15
    """

    LIMITS = BEACON_LIMITS
    DEFAULTS = BEACON_DEFAULTS

    # Toggle & identity
    enabled: bool = BEACON_DEFAULTS["enabled"]
    beacon_id: int = 0

    # Motion — profile + starting position
    profile: str = BEACON_DEFAULTS["profile"]  # MotionProfile value string
    position_seed: int = BEACON_DEFAULTS["position_seed"]
    x: float = BEACON_DEFAULTS["x"]
    y: float = BEACON_DEFAULTS["y"]
    heading: float | None = BEACON_DEFAULTS["heading"]
    speed: float = BEACON_DEFAULTS["speed"]

    # Photometric — visual appearance
    brightness: int = BEACON_DEFAULTS["brightness"]
    radius: int = BEACON_DEFAULTS["radius"]

    # Detection geometry — hitbox vs center
    hitbox_radius: int = BEACON_DEFAULTS["hitbox_radius"]
    center_radius: int = BEACON_DEFAULTS["center_radius"]

    # Validation — clamp to BEACON_LIMITS

    def validate(self) -> "BeaconConfig":
        """Clamp all numeric fields via clip_field, return self."""
        self.brightness = int(clip_field(self.brightness, *self.LIMITS["brightness"]))
        self.radius = int(clip_field(self.radius, *self.LIMITS["radius"]))
        self.hitbox_radius = int(clip_field(self.hitbox_radius, *self.LIMITS["hitbox_radius"]))
        self.center_radius = int(clip_field(self.center_radius, *self.LIMITS["center_radius"]))
        if self.center_radius > self.hitbox_radius:
            self.center_radius = int(self.hitbox_radius)
        self.speed = float(clip_field(self.speed, *self.LIMITS["speed"]))
        self.position_seed = int(clip_field(self.position_seed, *self.LIMITS["position_seed"]))
        self.x = float(clip_field(self.x, *self.LIMITS["x"]))
        self.y = float(clip_field(self.y, *self.LIMITS["y"]))
        if self.heading is not None:
            self.heading = float(clip_field(float(self.heading) % 360, *self.LIMITS["heading"]))

        self.enabled = bool(self.enabled)
        self.beacon_id = int(self.beacon_id)
        # Normalize profile string to lowercase
        self.profile = str(self.profile).lower()
        return self

    # Conversions — Target ↔ BeaconConfig

    @classmethod
    def from_target(cls, target: "Target") -> "BeaconConfig":
        """Snapshot a live Target into a BeaconConfig."""
        import math
        heading_deg = float(math.degrees(getattr(target, "_heading", 0.0))) % 360
        return cls(
            enabled=bool(getattr(target, "enabled", True)),
            beacon_id=int(getattr(target, "beacon_id", 0)),
            profile=str(getattr(target, "profile", None).value if hasattr(getattr(target, "profile", None), "value") else str(getattr(target, "profile", "curved"))),
            position_seed=int(getattr(target, "_seed", 42) or 42),
            x=float(target.x),
            y=float(target.y),
            heading=float(heading_deg),
            speed=float(target.speed),
            brightness=int(target.brightness),
            radius=int(target.radius),
            hitbox_radius=int(target.hitbox_radius),
            center_radius=int(target.center_radius),
        ).validate()

    def to_target_kwargs(self) -> dict:
        """Map to Target.__init__ kwargs (handles heading deg→rad conversion)."""
        import math
        heading_rad = None if self.heading is None else math.radians(float(self.heading) % 360)
        return {
            "x": float(self.x),
            "y": float(self.y),
            "profile": self.profile,  # Target resolves string via MotionProfile()
            "speed": float(self.speed),
            "brightness": int(self.brightness),
            "radius": int(self.radius),
            "hitbox_radius": int(self.hitbox_radius),
            "center_radius": int(self.center_radius),
            "heading": heading_rad,
            "beacon_id": int(self.beacon_id),
            "seed": int(self.position_seed),
            "enabled": bool(self.enabled),
        }

    def apply_to_target(self, target: "Target") -> None:
        """Hot-apply this config onto a live Target (no rebuild)."""
        import math
        from target.motion import MotionProfile
        try:
            target.enabled = bool(self.enabled)
        except Exception:
            pass
        try:
            # Profile live switch (string → enum)
            target.profile = MotionProfile(self.profile)
        except Exception:
            pass
        # Position — clamped to target bounds
        try:
            w, h = target.bounds
            target.x = float(np.clip(float(self.x), 0, w))
            target.y = float(np.clip(float(self.y), 0, h))
        except Exception:
            target.x = float(self.x); target.y = float(self.y)
        # Heading — keep internal rad
        if self.heading is not None:
            try:
                target._heading = math.radians(float(self.heading) % 360)
            except Exception:
                pass
        # Dynamic scalars — validated
        target.speed = float(np.clip(float(self.speed), *BEACON_LIMITS["speed"]))
        target.brightness = int(np.clip(int(self.brightness), *BEACON_LIMITS["brightness"]))
        target.radius = int(np.clip(int(self.radius), *BEACON_LIMITS["radius"]))
        # Keep scintillation in sync for immediate visual
        try:
            target.current_brightness = float(target.brightness)
        except Exception:
            pass
        target.set_hitbox(int(self.hitbox_radius), int(self.center_radius))
        # Seed affects future RNG only if re-seeded externally; store for round-trip
        target._seed = int(self.position_seed)

    # Serialization
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BeaconConfig":
        known = {k: v for k, v in data.items() if k in BEACON_DEFAULTS or k in ("x", "y", "heading", "beacon_id")}
        # Merge with defaults to tolerate partial dicts
        merged = {**BEACON_DEFAULTS, **known}
        # Preserve explicit x/y/heading/beacon_id even if not in defaults keys set logic above
        for k in ("x", "y", "heading", "beacon_id"):
            if k in data:
                merged[k] = data[k]
        return cls(**merged).validate()

@dataclass
class MultiBeaconConfig(BaseValidatedConfig):
    """
    Multi-beacon collection configuration.

    1) beacon_count   — Total beacons (1..16)
    2) target_index   — Which beacon is tracked (0..beacon_count-1), others = distractors
    + beacons         — List[BeaconConfig] per-beacon configs (length == beacon_count)
    """

    LIMITS = MULTI_BEACON_LIMITS
    DEFAULTS = MULTI_BEACON_DEFAULTS

    beacon_count: int = MULTI_BEACON_DEFAULTS["beacon_count"]
    target_index: int = MULTI_BEACON_DEFAULTS["target_index"]
    beacons: list[BeaconConfig] | None = None  # None → generate defaults

    def validate(self) -> "MultiBeaconConfig":
        self.beacon_count = int(clip_field(self.beacon_count, *self.LIMITS["beacon_count"]))
        # target_index clamped to 0..beacon_count-1 for safety
        self.target_index = int(clip_field(self.target_index, 0, max(0, self.beacon_count - 1)))

        # Ensure beacons list length matches beacon_count
        if self.beacons is None:
            self.beacons = [BeaconConfig(beacon_id=i).validate() for i in range(self.beacon_count)]
        else:
            # Validate each and assign ids
            validated: list[BeaconConfig] = []
            for i, cfg in enumerate(self.beacons[: self.beacon_count]):
                cfg.beacon_id = i
                validated.append(cfg.validate())
            # Pad if short
            while len(validated) < self.beacon_count:
                validated.append(BeaconConfig(beacon_id=len(validated)).validate())
            self.beacons = validated
        return self

    def to_dict(self) -> dict:
        return {
            "beacon_count": int(self.beacon_count),
            "target_index": int(self.target_index),
            "beacons": [b.to_dict() for b in (self.beacons or [])],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MultiBeaconConfig":
        beacons_data = data.get("beacons", None)
        beacons: list[BeaconConfig] | None = None
        if isinstance(beacons_data, list):
            beacons = [BeaconConfig.from_dict(d) for d in beacons_data]
        return cls(
            beacon_count=int(data.get("beacon_count", MULTI_BEACON_DEFAULTS["beacon_count"])),
            target_index=int(data.get("target_index", MULTI_BEACON_DEFAULTS["target_index"])),
            beacons=beacons,
        ).validate()