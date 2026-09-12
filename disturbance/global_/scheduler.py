"""Step scheduler for globally coordinated disturbances."""

from __future__ import annotations


class DisturbanceScheduler:
    def __init__(self, dt: float = 1.0 / 30.0):
        self.dt = float(dt)
        self.time = 0.0
        self.step = 0

    def advance(self, dt: float | None = None) -> float:
        self.dt = float(self.dt if dt is None else dt)
        self.time += self.dt
        self.step += 1
        return self.time

    def reset(self) -> None:
        self.time = 0.0
        self.step = 0


__all__ = ["DisturbanceScheduler"]