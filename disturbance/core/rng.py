"""RNG ownership for reproducible disturbance runs."""

from __future__ import annotations

import numpy as np


class DisturbanceRng:
    """Small wrapper that makes the generator used by a run explicit."""

    def __init__(self, seed: int | None = None, generator: np.random.Generator | None = None):
        self.generator = generator or np.random.default_rng(seed)

    def fork(self) -> "DisturbanceRng":
        return DisturbanceRng(generator=np.random.default_rng(self.generator.integers(0, 2**63 - 1)))

    @staticmethod
    def spawn_streams(n: int, seed: int | None = None) -> list[int]:
        """Non-colliding child seeds for parallel pipelines (SeedSequence)."""
        import numpy as _np
        seq = _np.random.SeedSequence(int(seed) if seed is not None else 0)
        return [int(s.generate_state(1)[0]) for s in seq.spawn(int(max(1, n)))]

    def __getattr__(self, name):
        return getattr(self.generator, name)


__all__ = ["DisturbanceRng"]