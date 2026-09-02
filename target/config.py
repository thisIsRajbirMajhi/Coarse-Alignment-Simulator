# target/config.py - Simplified beacon configuration — only multiple beacons and target selection

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from common.config_base import BaseValidatedConfig, clip_field
from target.constants import BEACON_DEFAULTS, BEACON_LIMITS, MULTI_BEACON_DEFAULTS, MULTI_BEACON_LIMITS

if TYPE_CHECKING:
    from target.motion import Target

@dataclass
class BeaconConfig(BaseValidatedConfig):
    """
    Per-beacon config kept for backward compatibility only.
    System now uses fixed defaults (no per-beacon customization).
    Only beacon_id and profile are relevant for randomise motion.
    """

    LIMITS = BEACON_LIMITS
    DEFAULTS = BEACON_DEFAULTS

    enabled: bool = BEACON_DEFAULTS["enabled"]
    beacon_id: int = 0
    profile: str = BEACON_DEFAULTS["profile"]
    position_seed: int = BEACON_DEFAULTS["position_seed"]
    x: float = BEACON_DEFAULTS["x"]
    y: float = BEACON_DEFAULTS["y"]
    heading: float | None = BEACON_DEFAULTS["heading"]
    speed: float = BEACON_DEFAULTS["speed"]
    brightness: int = BEACON_DEFAULTS["brightness"]
    radius: int = BEACON_DEFAULTS["radius"]
    hitbox_radius: int = BEACON_DEFAULTS["hitbox_radius"]
    center_radius: int = BEACON_DEFAULTS["center_radius"]
    shape: str = BEACON_DEFAULTS["shape"]
    size_w: int = BEACON_DEFAULTS["size_w"]
    size_h: int = BEACON_DEFAULTS["size_h"]
    blinking: bool = BEACON_DEFAULTS["blinking"]

    def validate(self) -> "BeaconConfig":
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
        self.profile = str(self.profile).lower()
        self.shape = str(self.shape).lower() if self.shape else "square"
        if self.shape not in ("square", "circle", "random"):
            self.shape = "square"
        self.size_w = int(clip_field(self.size_w, *self.LIMITS["size_w"]))
        self.size_h = int(clip_field(self.size_h, *self.LIMITS["size_h"]))
        self.blinking = bool(self.blinking)
        return self

    @classmethod
    def from_target(cls, target: "Target") -> "BeaconConfig":
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
            shape=str(getattr(target, "shape", "square")),
            size_w=int(getattr(target, "size_w", 10)),
            size_h=int(getattr(target, "size_h", 10)),
            blinking=bool(getattr(target, "blinking", False)),
        ).validate()

    def to_target_kwargs(self) -> dict:
        import math
        heading_rad = None if self.heading is None else math.radians(float(self.heading) % 360)
        return {
            "x": float(self.x),
            "y": float(self.y),
            "profile": self.profile,
            "speed": float(self.speed),
            "brightness": int(self.brightness),
            "radius": int(self.radius),
            "hitbox_radius": int(self.hitbox_radius),
            "center_radius": int(self.center_radius),
            "heading": heading_rad,
            "beacon_id": int(self.beacon_id),
            "seed": int(self.position_seed),
            "enabled": bool(self.enabled),
            "shape": str(self.shape),
            "size_w": int(self.size_w),
            "size_h": int(self.size_h),
            "blinking": bool(self.blinking),
        }

    def apply_to_target(self, target: "Target") -> None:
        import math
        from target.motion import MotionProfile
        try:
            target.enabled = bool(self.enabled)
        except Exception:
            pass
        try:
            target.profile = MotionProfile(self.profile)
        except Exception:
            pass
        try:
            w, h = target.bounds
            target.x = float(__import__("numpy").clip(float(self.x), 0, w))
            target.y = float(__import__("numpy").clip(float(self.y), 0, h))
        except Exception:
            target.x = float(self.x); target.y = float(self.y)
        if self.heading is not None:
            try:
                target._heading = math.radians(float(self.heading) % 360)
            except Exception:
                pass
        target.speed = float(__import__("numpy").clip(float(self.speed), *BEACON_LIMITS["speed"]))
        target.brightness = int(__import__("numpy").clip(int(self.brightness), *BEACON_LIMITS["brightness"]))
        target.radius = int(__import__("numpy").clip(int(self.radius), *BEACON_LIMITS["radius"]))
        try:
            target.current_brightness = float(target.brightness)
        except Exception:
            pass
        target.set_hitbox(int(self.hitbox_radius), int(self.center_radius))
        target._seed = int(self.position_seed)
        try:
            target.shape = str(self.shape)
            target.size_w = int(self.size_w)
            target.size_h = int(self.size_h)
            target.blinking = bool(self.blinking)
        except Exception:
            pass

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BeaconConfig":
        known = {k: v for k, v in data.items() if k in BEACON_DEFAULTS or k in ("x", "y", "heading", "beacon_id")}
        merged = {**BEACON_DEFAULTS, **known}
        for k in ("x", "y", "heading", "beacon_id"):
            if k in data:
                merged[k] = data[k]
        return cls(**merged).validate()


@dataclass
class MultiBeaconConfig(BaseValidatedConfig):
    """
    Single-panel beacon configuration — all beacons share same rules.
      beacon_count, target_index, shape, size_w, size_h, x, y, profile, speed, blinking
    Shape: square/circle/random — if random each beacon gets random shape
    Profile: Straight Line/Circular etc — if Random each beacon gets random motion
    """

    LIMITS = MULTI_BEACON_LIMITS
    DEFAULTS = MULTI_BEACON_DEFAULTS

    beacon_count: int = MULTI_BEACON_DEFAULTS["beacon_count"]
    target_index: int = MULTI_BEACON_DEFAULTS["target_index"]
    shape: str = MULTI_BEACON_DEFAULTS["shape"]
    size_w: int = MULTI_BEACON_DEFAULTS["size_w"]
    size_h: int = MULTI_BEACON_DEFAULTS["size_h"]
    x: float = MULTI_BEACON_DEFAULTS["x"]
    y: float = MULTI_BEACON_DEFAULTS["y"]
    profile: str = MULTI_BEACON_DEFAULTS["profile"]
    speed: float = MULTI_BEACON_DEFAULTS["speed"]
    blinking: bool = MULTI_BEACON_DEFAULTS["blinking"]
    speed_random: bool = MULTI_BEACON_DEFAULTS["speed_random"]
    beacons: list[BeaconConfig] | None = None

    def validate(self) -> "MultiBeaconConfig":
        self.beacon_count = int(clip_field(self.beacon_count, *self.LIMITS["beacon_count"]))
        self.target_index = int(clip_field(self.target_index, 0, max(0, self.beacon_count - 1)))
        self.shape = str(self.shape).lower() if self.shape else "square"
        if self.shape not in ("square", "circle", "random"):
            self.shape = "square"
        self.size_w = int(clip_field(self.size_w, *BEACON_LIMITS["size_w"]))
        self.size_h = int(clip_field(self.size_h, *BEACON_LIMITS["size_h"]))
        self.x = float(clip_field(self.x, *BEACON_LIMITS["x"]))
        self.y = float(clip_field(self.y, *BEACON_LIMITS["y"]))
        self.profile = str(self.profile).lower()
        self.speed = float(clip_field(self.speed, *BEACON_LIMITS["speed"]))
        self.blinking = bool(self.blinking)
        self.speed_random = bool(self.speed_random)
        if self.beacons is None:
            self.beacons = [BeaconConfig(beacon_id=i).validate() for i in range(self.beacon_count)]
        else:
            validated: list[BeaconConfig] = []
            for i, cfg in enumerate(self.beacons[: self.beacon_count]):
                cfg.beacon_id = i
                validated.append(cfg.validate())
            while len(validated) < self.beacon_count:
                validated.append(BeaconConfig(beacon_id=len(validated)).validate())
            self.beacons = validated
        return self

    def to_dict(self) -> dict:
        return {
            "beacon_count": int(self.beacon_count),
            "target_index": int(self.target_index),
            "shape": str(self.shape),
            "size_w": int(self.size_w),
            "size_h": int(self.size_h),
            "x": float(self.x),
            "y": float(self.y),
            "profile": str(self.profile),
            "speed": float(self.speed),
            "blinking": bool(self.blinking),
            "speed_random": bool(self.speed_random),
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
            shape=str(data.get("shape", MULTI_BEACON_DEFAULTS["shape"])),
            size_w=int(data.get("size_w", MULTI_BEACON_DEFAULTS["size_w"])),
            size_h=int(data.get("size_h", MULTI_BEACON_DEFAULTS["size_h"])),
            x=float(data.get("x", MULTI_BEACON_DEFAULTS["x"])),
            y=float(data.get("y", MULTI_BEACON_DEFAULTS["y"])),
            profile=str(data.get("profile", MULTI_BEACON_DEFAULTS["profile"])),
            speed=float(data.get("speed", MULTI_BEACON_DEFAULTS["speed"])),
            blinking=bool(data.get("blinking", MULTI_BEACON_DEFAULTS["blinking"])),
            speed_random=bool(data.get("speed_random", MULTI_BEACON_DEFAULTS["speed_random"])),
            beacons=beacons,
        ).validate()
