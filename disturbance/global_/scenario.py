"""Named, reproducible disturbance scenarios."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from disturbance.core.config import DisturbanceConfig
from disturbance.core.context import DisturbanceContext
from disturbance.core.pipeline import DisturbancePipeline
from disturbance.global_.randomization import randomize_config


@dataclass
class DisturbanceScenario:
    config: DisturbanceConfig
    seed: int | None = None

    @classmethod
    def randomized(cls, seed: int | None = None, difficulty: str = "mixed") -> "DisturbanceScenario":
        rng = np.random.default_rng(seed)
        return cls(randomize_config(rng=rng, difficulty=difficulty), seed)

    def create_pipeline(self, dt: float = 1.0 / 30.0) -> DisturbancePipeline:
        return DisturbancePipeline(DisturbanceContext(self.config, rng=np.random.default_rng(self.seed), dt=dt))


__all__ = ["DisturbanceScenario"]