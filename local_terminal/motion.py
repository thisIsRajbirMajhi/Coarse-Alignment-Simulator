# local_terminal/motion.py - Constant-velocity α-β motion model (Plan.md §7.3).
#
# Deliberately simple (no Kalman matrices): deterministic, testable, and
# exact per the spec equations. One filter per axis, FOV-pixel coordinates.
# Camera-motion compensation enters via origin_shift (see ImageTracker):
# the prior is translated by the FOV-origin shift before prediction so the
# velocity estimate tracks target motion, not camera motion.

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AlphaBetaConfig:
    """Gains per Plan.md §7.3 (defaults at 30 Hz)."""

    alpha: float = 0.4
    beta: float = 0.05
    uncertainty_growth_px: float = 2.0  # per coasted frame
    uncertainty_cap_px: float = 30.0    # == prediction search cap (§7.1)

    def validate(self) -> "AlphaBetaConfig":
        self.alpha = float(min(max(self.alpha, 0.0), 1.0))
        self.beta = float(min(max(self.beta, 0.0), 1.0))
        self.uncertainty_growth_px = float(max(0.0, self.uncertainty_growth_px))
        self.uncertainty_cap_px = float(max(1.0, self.uncertainty_cap_px))
        return self


class AlphaBetaAxis:
    """Single-axis α-β filter: predict x_p = x + v·dt; update on measurement."""

    def __init__(self, config: AlphaBetaConfig | None = None):
        self.config = (config or AlphaBetaConfig()).validate()
        self.x = 0.0
        self.v = 0.0
        self.uncertainty_px = 0.0
        self._initialised = False

    def reset(self) -> None:
        self.x = 0.0
        self.v = 0.0
        self.uncertainty_px = 0.0
        self._initialised = False

    def initialise(self, x0: float, x1: float, dt: float) -> None:
        """Seed from two associations: v = (x1 − x0)/dt (spec: v = 0 until
        two associations exist; callers may instead initialise(x0, x0, dt))."""
        self.x = float(x1)
        self.v = (float(x1) - float(x0)) / max(float(dt), 1e-6)
        self.uncertainty_px = 0.0
        self._initialised = True

    def shift(self, dx: float) -> None:
        """Translate the prior by FOV-origin motion (camera moved under us)."""
        self.x += float(dx)
        self.v = self.v  # velocity is relative; translation preserves it

    def predict(self, dt: float) -> float:
        return self.x + self.v * max(float(dt), 1e-6)

    def update(self, z: float, dt: float) -> float:
        """Predict-then-correct with measurement z; returns corrected x."""
        dt_eff = max(float(dt), 1e-6)
        if not self._initialised:
            self.x = float(z)
            self.v = 0.0
            self._initialised = True
            self.uncertainty_px = 0.0
            return self.x
        x_p = self.predict(dt_eff)
        self.x = x_p + self.config.alpha * (float(z) - x_p)
        self.v = self.v + (self.config.beta / dt_eff) * (float(z) - x_p)
        self.uncertainty_px = 0.0
        return self.x

    def coast(self, dt: float) -> float:
        """No measurement: hold prediction, grow uncertainty to the cap."""
        self.x = self.predict(float(dt))
        self.uncertainty_px = min(
            self.uncertainty_px + self.config.uncertainty_growth_px,
            self.config.uncertainty_cap_px,
        )
        return self.x


class AlphaBetaFilter2D:
    """Two-axis bundle with shared config and 2D helpers."""

    def __init__(self, config: AlphaBetaConfig | None = None):
        cfg = (config or AlphaBetaConfig()).validate()
        self.ax = AlphaBetaAxis(cfg)
        self.ay = AlphaBetaAxis(cfg)

    @property
    def config(self) -> AlphaBetaConfig:
        return self.ax.config

    def reset(self) -> None:
        self.ax.reset()
        self.ay.reset()

    @property
    def initialised(self) -> bool:
        return self.ax._initialised

    def initialise(self, x0: float, y0: float, x1: float, y1: float, dt: float) -> None:
        self.ax.initialise(x0, x1, dt)
        self.ay.initialise(y0, y1, dt)

    def shift(self, dx: float, dy: float) -> None:
        self.ax.shift(dx)
        self.ay.shift(dy)

    def predict(self, dt: float) -> tuple[float, float]:
        return (self.ax.predict(dt), self.ay.predict(dt))

    def update(self, x: float, y: float, dt: float) -> tuple[float, float]:
        return (self.ax.update(x, dt), self.ay.update(y, dt))

    def coast(self, dt: float) -> tuple[float, float]:
        return (self.ax.coast(dt), self.ay.coast(dt))

    @property
    def velocity(self) -> tuple[float, float]:
        return (self.ax.v, self.ay.v)

    @property
    def estimate(self) -> tuple[float, float]:
        """Current state estimate (already predicted/coasted for this frame)."""
        return (self.ax.x, self.ay.x)

    @property
    def uncertainty_px(self) -> float:
        return max(self.ax.uncertainty_px, self.ay.uncertainty_px)


__all__ = ["AlphaBetaAxis", "AlphaBetaConfig", "AlphaBetaFilter2D"]
