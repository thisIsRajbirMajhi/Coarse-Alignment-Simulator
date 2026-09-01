"""
Module: environment.config
Purpose: Typed, validated configuration for the Environment (10 parameters).
Public API: EnvironmentConfig
Notes: Single source of truth — consumed by Scene and EnvironmentPanel.
       Immediate migration: MainWindow now stores self.env_config (replaces
       6 separate _env_* attributes).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from common.config_base import BaseValidatedConfig, clip_field
from environment.constants import (
    DEFAULTS,
    LIMITS,
    haze_pct_to_strength,
    haze_strength_to_pct,
    vignetting_pct_to_strength,
    vignetting_strength_to_pct,
)

if TYPE_CHECKING:
    from environment.scene import Scene

# ============================================================
# SECTION: EnvironmentConfig — Dataclass
# ============================================================

@dataclass
class EnvironmentConfig(BaseValidatedConfig):
    """
    Typed configuration for all 10 Environment parameters.

    Groups logically per control-panel sections:
      - World: world_width, world_height
      - Seed: seed
      - Atmosphere: bg_top, bg_bottom, vignetting_pct, haze_pct
      - Starfield: star_count, star_brightness
      - Dynamics: dynamic, dynamic_speed

    All fields validated via validate() — clamps to LIMITS and returns self
    for fluent usage. Call validate() before passing to Scene.
    """

    LIMITS = LIMITS
    DEFAULTS = DEFAULTS

    # --------------------------------------------------------
    # World (px) — full 2D scene size
    # --------------------------------------------------------
    world_width: int = DEFAULTS["world_width"]
    world_height: int = DEFAULTS["world_height"]

    # --------------------------------------------------------
    # Seed — reproducible RNG
    # --------------------------------------------------------
    seed: int | None = DEFAULTS["seed"]

    # --------------------------------------------------------
    # Atmosphere — gradient + fog + vignetting
    # --------------------------------------------------------
    bg_top: int = DEFAULTS["bg_top"]
    bg_bottom: int = DEFAULTS["bg_bottom"]
    vignetting_pct: int = DEFAULTS["vignetting_pct"]
    haze_pct: int = DEFAULTS["haze_pct"]

    # --------------------------------------------------------
    # Starfield / Clutter
    # --------------------------------------------------------
    star_count: int = DEFAULTS["star_count"]
    star_brightness: float = DEFAULTS["star_brightness"]

    # --------------------------------------------------------
    # Dynamics — time-varying animation
    # --------------------------------------------------------
    dynamic: bool = DEFAULTS["dynamic"]
    dynamic_speed: float = DEFAULTS["dynamic_speed"]

    # ========================================================
    # SECTION: Validation
    # ========================================================

    def validate(self) -> "EnvironmentConfig":
        """
        Clamp all fields to LIMITS in-place and return self — now via clip_field.
        """
        self.world_width = int(clip_field(self.world_width, *LIMITS["world_width"]))
        self.world_height = int(clip_field(self.world_height, *LIMITS["world_height"]))
        if self.seed is not None:
            self.seed = int(clip_field(self.seed, *LIMITS["seed"]))
        self.bg_top = int(clip_field(self.bg_top, *LIMITS["bg_top"]))
        self.bg_bottom = int(clip_field(self.bg_bottom, *LIMITS["bg_bottom"]))
        self.vignetting_pct = int(clip_field(self.vignetting_pct, *LIMITS["vignetting_pct"]))
        self.haze_pct = int(clip_field(self.haze_pct, *LIMITS["haze_pct"]))
        self.star_count = int(clip_field(self.star_count, *LIMITS["star_count"]))
        self.star_brightness = float(clip_field(self.star_brightness, *LIMITS["star_brightness"]))
        self.dynamic = bool(self.dynamic)
        self.dynamic_speed = float(clip_field(self.dynamic_speed, *LIMITS["dynamic_speed"]))
        return self

    # ========================================================
    # SECTION: Conversions — Scene ↔ Config
    # ========================================================

    def to_scene_kwargs(self) -> dict:
        """
        Map this config to Scene.__init__ / Scene.regenerate kwargs.

        Handles unit conversions:
          haze_pct (0-100) -> haze_strength (0-1)
          vignetting_pct (0-92) -> vignetting (0-0.92)
          world_width/height -> width/height
        """
        return {
            "width": int(self.world_width),
            "height": int(self.world_height),
            "seed": self.seed,
            "haze_strength": haze_pct_to_strength(self.haze_pct),
            "star_count": int(self.star_count),
            "star_brightness_scale": float(self.star_brightness),
            "bg_top": int(self.bg_top),
            "bg_bottom": int(self.bg_bottom),
            "vignetting": vignetting_pct_to_strength(self.vignetting_pct),
            "dynamic": bool(self.dynamic),
            "dynamic_speed": float(self.dynamic_speed),
        }

    @classmethod
    def from_scene(cls, scene: "Scene") -> "EnvironmentConfig":
        """
        Build a config snapshot from a live Scene instance.

        Used for initial panel population and for test round-trips.
        """
        return cls(
            world_width=int(scene.width),
            world_height=int(scene.height),
            seed=scene.seed,
            bg_top=int(scene.bg_top),
            bg_bottom=int(scene.bg_bottom),
            vignetting_pct=vignetting_strength_to_pct(float(scene.vignetting)),
            haze_pct=haze_strength_to_pct(float(scene.haze_strength)),
            star_count=int(scene.get_star_count()),
            star_brightness=float(scene.star_brightness_scale),
            dynamic=bool(scene.dynamic),
            dynamic_speed=float(scene.dynamic_speed),
        ).validate()

    # ========================================================
    # SECTION: Serialization helpers
    # ========================================================

    def to_dict(self) -> dict:
        """Return a plain dict (e.g., for logging or export)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EnvironmentConfig":
        """Create validated config from a plain dict (e.g., loaded JSON)."""
        # Filter to known fields to tolerate extra keys
        known = {k: v for k, v in data.items() if k in DEFAULTS}
        cfg = cls(**{**DEFAULTS, **known})
        return cfg.validate()
