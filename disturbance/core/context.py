"""Per-run context shared by all disturbance domains."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from disturbance.core.config import DisturbanceConfig
from disturbance.core.rng import DisturbanceRng
from disturbance.core.state import DisturbanceState


@dataclass
class DisturbanceContext:
    config: DisturbanceConfig = field(default_factory=DisturbanceConfig)
    state: DisturbanceState = field(default_factory=DisturbanceState)
    rng: np.random.Generator | DisturbanceRng = field(default_factory=DisturbanceRng)
    dt: float = 1.0 / 30.0
    sim_time: float = 0.0
    step: int = 0

    def __post_init__(self) -> None:
        self.config.validate()
        if isinstance(self.rng, DisturbanceRng):
            self.rng = self.rng.generator

    def reset(self) -> None:
        self.state.reset()
        self.sim_time = 0.0
        self.step = 0

    def advance(self, dt: float | None = None) -> "DisturbanceContext":
        if dt is not None:
            self.dt = float(dt)
        self.sim_time += self.dt
        self.step += 1
        return self


__all__ = ["DisturbanceContext"]