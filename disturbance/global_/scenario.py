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
        # Strict-compat: identical seeds → identical streams via default_rng.
        # For parallel pipelines from one parent, use
        # DisturbanceRng.spawn_streams(n) to avoid collisions.
        return DisturbancePipeline(DisturbanceContext(self.config, rng=np.random.default_rng(self.seed), dt=dt))

    def create_pipelines(self, n: int, dt: float = 1.0 / 30.0) -> list[DisturbancePipeline]:
        """Parallel pipelines with non-colliding spawned streams."""
        from disturbance.core.rng import DisturbanceRng
        seeds = DisturbanceRng.spawn_streams(int(n), seed=self.seed)
        return [DisturbancePipeline(DisturbanceContext(self.config, rng=np.random.default_rng(int(s)), dt=dt))
                for s in seeds]


__all__ = ["DisturbanceScenario"]