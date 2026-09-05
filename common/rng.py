# common/rng.py - Centralized RNG for deterministic AI training
# Provides a seeded global Generator used by disturbance/camera modules when no explicit rng is passed.
# Fixes global RNG nondeterminism: previously every disturbance used np.random global RandomState,
# which ignores EnvironmentConfig.seed and makes episodes non-reproducible.
# Now: HeadlessSimulation creates a Generator(seed) and threads it through all apply_* calls.
# GUI path without explicit rng falls back to global Generator (seeded via seed_global).

from __future__ import annotations

import numpy as np
import random as py_random

_global_gen: np.random.Generator = np.random.default_rng()
_global_seed: int | None = None


def seed_global(seed: int | None) -> np.random.Generator:
    """Seed global RNGs (numpy Generator + stdlib random + legacy np.random) for determinism."""
    global _global_gen, _global_seed
    if seed is None:
        # No seed -> fresh unpredictable
        _global_gen = np.random.default_rng()
        _global_seed = None
        return _global_gen
    _global_gen = np.random.default_rng(int(seed))
    _global_seed = int(seed)
    # Also seed legacy global state for backwards compat where some code still uses np.random.*
    try:
        np.random.seed(int(seed) % (2**32 - 1))
    except Exception:
        pass
    try:
        py_random.seed(int(seed))
    except Exception:
        pass
    return _global_gen


def get_global_rng() -> np.random.Generator:
    """Return global Generator (seeded via seed_global or default)."""
    return _global_gen


def get_rng(rng: np.random.Generator | None = None, seed: int | None = None) -> np.random.Generator:
    """
    Resolve to a Generator:
      - if rng is a Generator -> return it
      - elif seed is not None -> new Generator(seed)
      - else -> global Generator
    """
    if isinstance(rng, np.random.Generator):
        return rng
    if seed is not None:
        return np.random.default_rng(int(seed))
    return get_global_rng()


def resolve_rng(rng: np.random.Generator | None = None) -> np.random.Generator:
    """Shorthand for get_rng(rng) — fallback to global."""
    if isinstance(rng, np.random.Generator):
        return rng
    return get_global_rng()


# Helper to make np.random.* calls via Generator with compatible API
def _as_gen(rng: np.random.Generator | None) -> np.random.Generator:
    return get_rng(rng)
