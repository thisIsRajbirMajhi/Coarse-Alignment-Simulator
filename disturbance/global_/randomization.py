"""Scenario-level configuration randomization."""

import copy

from disturbance.core.config import DisturbanceConfig


def randomize_config(config: DisturbanceConfig | None = None, rng=None, difficulty: str = "mixed") -> DisturbanceConfig:
    # Copy-on-write: never mutate the caller's config alias (was result=config).
    base = copy.deepcopy(config) if config is not None else DisturbanceConfig()
    return base.randomize_for_training(rng=rng, difficulty=difficulty).validate()


__all__ = ["randomize_config"]