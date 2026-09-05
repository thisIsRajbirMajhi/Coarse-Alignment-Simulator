# simulation/__init__.py — Headless simulation package for AI training
# Provides HeadlessSimulation (gym-like) without Qt, deterministic via seeded RNG.

from simulation.headless import HeadlessSimulation  # noqa: F401

try:
    from simulation.env import FSOCEnv  # noqa: F401
except Exception:
    pass

__all__ = ["HeadlessSimulation"]
