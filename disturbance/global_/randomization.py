"""Scenario-level configuration randomization."""

from disturbance.core.config import DisturbanceConfig


def randomize_config(config: DisturbanceConfig | None = None, rng=None, difficulty: str = "mixed") -> DisturbanceConfig:
    result = config or DisturbanceConfig()
    return result.randomize_for_training(rng=rng, difficulty=difficulty).validate()


__all__ = ["randomize_config"]