# target/strategy.py - Strategy interface for motion profiles — eliminates God method Target

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from target.motion import Target

class MotionContext:
    """Data passed to strategy.step — dt, bounds, t, rng."""

    def __init__(self, dt: float, bounds: tuple[float, float], t: float, rng: np.random.Generator):
        self.dt = float(dt)
        self.bounds = bounds
        self.t = float(t)
        self.rng = rng
        self.W, self.H = float(bounds[0]), float(bounds[1])

class MotionStrategy(ABC):
    """Abstract motion profile — one step per tick."""

    @abstractmethod
    def step(self, target: "Target", ctx: MotionContext) -> None:
        """Advance target position/velocity in place. Must update target.x, target.y, target._heading, target._vx/_vy as needed."""

    def bounce(self, pos: float, vel: float, lo: float, hi: float, coeff: float = 0.88) -> tuple[float, float]:
        """Bounce with energy loss — single source for 5× duplication at target/motion.py:394."""
        if pos <= lo:
            return lo + 0.5, abs(float(vel)) * float(coeff)
        if pos >= hi:
            return hi - 0.5, -abs(float(vel)) * float(coeff)
        return pos, vel

    @staticmethod
    def wrap_angle(a: float) -> float:
        return float(a % (2 * math.pi))

# Minimal example strategies — full 10-profile split can follow same pattern incrementally
class StationaryStrategy(MotionStrategy):
    def step(self, target: "Target", ctx: MotionContext) -> None:
        target.x = float(np.clip(target.x + float(ctx.rng.normal(0, 0.12)), 0, ctx.W))
        target.y = float(np.clip(target.y + float(ctx.rng.normal(0, 0.12)), 0, ctx.H))

class LinearStrategy(MotionStrategy):
    def step(self, target: "Target", ctx: MotionContext) -> None:
        # Heading diffusion + leaky velocity — simplified extract from target/motion.py:382
        target._heading += float(ctx.rng.normal(0, 0.35 * math.sqrt(ctx.dt)))
        target.speed = float(np.clip(target.speed + float(ctx.rng.normal(0, 4 * math.sqrt(ctx.dt))), 0.7 * 60, 1.3 * 60))
        # Use target's stored vx/vy if present, else derive
        vx = target.speed * math.cos(target._heading)
        vy = target.speed * math.sin(target._heading)
        # Leaky
        tau = 0.12
        alpha = ctx.dt / (tau + ctx.dt)
        # Assume target has _vx, _vy
        prev_vx = getattr(target, "_vx", vx)
        prev_vy = getattr(target, "_vy", vy)
        vx = prev_vx + alpha * (vx - prev_vx)
        vy = prev_vy + alpha * (vy - prev_vy)
        target._vx, target._vy = vx, vy
        nx, ny = target.x + vx * ctx.dt, target.y + vy * ctx.dt
        nx, vx = self.bounce(nx, vx, 0, ctx.W, 0.88)
        ny, vy = self.bounce(ny, vy, 0, ctx.H, 0.88)
        target.x, target.y = nx, ny
        target._vx, target._vy = vx, vy
        target._heading = math.atan2(vy, vx)