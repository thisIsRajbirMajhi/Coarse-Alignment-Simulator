from __future__ import annotations

import random as _random

import numpy as np

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

@dataclass
class EnvironmentConfig(BaseValidatedConfig):
    """
    Typed configuration for all 8 Environment parameters.

    Groups logically per control-panel sections:
      - World: world_width, world_height
      - Seed: seed
      - Atmosphere: bg_top, bg_bottom, vignetting_pct, haze_pct
      - Starfield: star_count, star_brightness

    All fields validated via validate() — clamps to LIMITS and returns self
    for fluent usage. Call validate() before passing to Scene.
    """

    LIMITS = LIMITS
    DEFAULTS = DEFAULTS

    # World (px) — full 2D scene size
    world_width: int = DEFAULTS["world_width"]
    world_height: int = DEFAULTS["world_height"]

    # Seed — reproducible RNG
    seed: int | None = DEFAULTS["seed"]

    # Atmosphere — gradient + fog + vignetting
    bg_top: int = DEFAULTS["bg_top"]
    bg_bottom: int = DEFAULTS["bg_bottom"]
    vignetting_pct: int = DEFAULTS["vignetting_pct"]
    haze_pct: int = DEFAULTS["haze_pct"]

    # Starfield / Clutter
    star_count: int = DEFAULTS["star_count"]
    star_brightness: float = DEFAULTS["star_brightness"]

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
        return self

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
        ).validate()

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

    # ---------- AI Training Helpers (robust-simple) ----------
    def randomize_for_training(self, rng: np.random.Generator | None = None, difficulty: str = "mixed") -> "EnvironmentConfig":
        """
        Domain randomization for AI data generation — produces challenging variants.

        Args:
          rng: optional Generator for reproducibility
          difficulty: "easy" | "medium" | "hard" | "mixed"
        Returns self (mutated) for chaining.
        """
        if rng is None:
            rng = np.random.default_rng(_random.randint(0, 999999))
        diff = str(difficulty).lower()
        if diff == "easy":
            self.haze_pct = int(rng.integers(0, 20))
            self.star_count = int(rng.integers(20, 120))
            self.star_brightness = float(rng.uniform(0.7, 1.1))
            self.vignetting_pct = int(rng.integers(0, 15))
        elif diff == "medium":
            self.haze_pct = int(rng.integers(15, 55))
            self.star_count = int(rng.integers(80, 400))
            self.star_brightness = float(rng.uniform(0.9, 1.4))
            self.vignetting_pct = int(rng.integers(5, 35))
        elif diff == "hard":
            self.haze_pct = int(rng.integers(45, 95))
            self.star_count = int(rng.integers(300, 2500))
            self.star_brightness = float(rng.uniform(1.2, 1.8))
            self.vignetting_pct = int(rng.integers(15, 60))
            self.bg_bottom = int(rng.integers(18, 40))
        else:  # mixed — 30/40/30
            pick = rng.choice(["easy", "medium", "hard"], p=[0.30, 0.40, 0.30])
            return self.randomize_for_training(rng, pick)
        self.bg_top = int(rng.integers(8, 18))
        self.seed = int(rng.integers(0, 999999))
        return self.validate()

    @classmethod
    def generate_training_batch(cls, n: int = 100, difficulty: str = "mixed", seed: int | None = 42) -> list["EnvironmentConfig"]:
        """Generate n randomized configs for batch AI data generation."""
        rng = np.random.default_rng(seed)
        return [cls().randomize_for_training(rng, difficulty) for _ in range(n)]