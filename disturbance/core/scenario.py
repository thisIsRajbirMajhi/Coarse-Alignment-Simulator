"""Deterministic disturbance scenario generation."""

from __future__ import annotations

import numpy as np

from disturbance.core.config import DisturbanceConfig


class DisturbanceScenarioGenerator:
    def generate(self, seed: int, difficulty: str = "medium") -> DisturbanceConfig:
        rng = np.random.default_rng(int(seed))
        return DisturbanceConfig().randomize_for_training(rng=rng, difficulty=difficulty)


__all__ = ["DisturbanceScenarioGenerator"]