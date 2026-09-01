# presets/preset.py - Preset dataclass — full simulator configuration + goal (well-commented)

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class Preset:
    """
    Preconfigured test preset — one-click entire software.

    Fields:
      name: short label (e.g., "Ideal — Baseline")
      description: 1-2 line what it configures (disturbances, beacons, speed, etc.)
      goal: brief end goal — what to observe / metric to expect (e.g., "Lock retention 100%, acquisition <1s")
      category: group (e.g., "baseline", "stress", "acquisition")

      configs: dict of subsystem configs (all optional, only specified keys override defaults)
        - environment: EnvironmentConfig dict
        - camera: CameraConfig dict
        - beacons: MultiBeaconConfig dict + disturbances dict + detector/tracker overrides
        - disturbances: {Turbulence,Vibration,Camera Motion,Noise} 0..10
        - controller: ControllerConfig dict
        - overlay: OverlayConfig dict
        - detector: {brightness_threshold, min_area}
        - tracker: {smoothing, miss_limit}
        - target: {profile, speed} (applied to MultiBeaconConfig beacons)

      All dicts are plain (serializable) — constructed via Config.from_dict().
    """

    name: str
    description: str
    goal: str
    category: str = "general"
    # Subsystem configs — plain dicts (validated on apply)
    environment: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    beacons: dict = field(default_factory=dict)  # MultiBeaconConfig dict
    disturbances: dict = field(default_factory=dict)  # {Turbulence:0..10, ...}
    controller: dict = field(default_factory=dict)
    overlay: dict = field(default_factory=dict)
    detector: dict = field(default_factory=dict)
    tracker: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)  # {profile, speed}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "goal": self.goal,
            "category": self.category,
            "environment": dict(self.environment),
            "camera": dict(self.camera),
            "beacons": dict(self.beacons),
            "disturbances": dict(self.disturbances),
            "controller": dict(self.controller),
            "overlay": dict(self.overlay),
            "detector": dict(self.detector),
            "tracker": dict(self.tracker),
            "target": dict(self.target),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Preset":
        return cls(
            name=str(data.get("name", "Unnamed")),
            description=str(data.get("description", "")),
            goal=str(data.get("goal", "")),
            category=str(data.get("category", "general")),
            environment=dict(data.get("environment", {})),
            camera=dict(data.get("camera", {})),
            beacons=dict(data.get("beacons", {})),
            disturbances=dict(data.get("disturbances", {})),
            controller=dict(data.get("controller", {})),
            overlay=dict(data.get("overlay", {})),
            detector=dict(data.get("detector", {})),
            tracker=dict(data.get("tracker", {})),
            target=dict(data.get("target", {})),
        )