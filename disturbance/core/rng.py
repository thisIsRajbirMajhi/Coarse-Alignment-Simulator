"""RNG ownership for reproducible disturbance runs."""

from __future__ import annotations

import numpy as np


class DisturbanceRng:
    """Small wrapper that makes the generator used by a run explicit."""

    def __init__(self, seed: int | None = None, generator: np.random.Generator | None = None):
        self.generator = generator or np.random.default_rng(seed)

    def fork(self) -> "DisturbanceRng":
        return DisturbanceRng(generator=np.random.default_rng(self.generator.integers(0, 2**63 - 1)))

    def __getattr__(self, name):
        return getattr(self.generator, name)


__all__ = ["DisturbanceRng"]