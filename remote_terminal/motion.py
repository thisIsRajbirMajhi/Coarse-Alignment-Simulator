# remote_terminal/motion.py - MotionModel: trajectory only (§§27-34, §45).
#
# Owns the FORMATION-CENTER trajectory. Terminal positions are derived as
# center + rotated formation offset (RemoteTerminal.md §§44-45), so the
# formation stays coherent. No optical logic here.
#
# Determinism: analytic profiles are exact functions of time; RANDOM uses an
# explicitly passed stdlib ``random.Random`` (RemoteTerminal.md §67) — same
# seed + same configuration + same dt sequence → same trajectory.
from __future__ import annotations

import math
import random as py_random

from remote_terminal.config import MotionProfile
from remote_terminal.models import Vector2

# Internal model constants (NOT GUI parameters — RemoteTerminal.md §79).
LINEAR_RAMP_DURATION_S: float = 5.0
CIRCULAR_RADIUS_M: float = 500.0
SINUSOIDAL_AMPLITUDE_M: float = 50.0
SINUSOIDAL_OMEGA_RAD_S: float = 0.5
FIGURE8_AMPLITUDE_X_M: float = 100.0
FIGURE8_AMPLITUDE_Y_M: float = 100.0
FIGURE8_OMEGA_RAD_S: float = 0.25
RANDOM_MAX_TURN_DEG_S: float = 20.0


class MotionModel:
    """Formation-center motion for one scenario (§27).

    Inputs: speed, heading, motion profile, simulation time, dt.
    Outputs: position, velocity.
    """

    def __init__(
        self,
        speed_mps: float,
        heading_deg: float,
        profile: MotionProfile,
        start: Vector2 | None = None,
        rng: py_random.Random | None = None,
    ):
        if not isinstance(profile, MotionProfile):
            raise ValueError(f"unknown motion profile: {profile!r}.")
        self.speed_mps = max(0.0, float(speed_mps))
        self.heading_deg = float(heading_deg)
        self.profile = profile
        self.start = start or Vector2(0.0, 0.0)
        self.rng = rng if isinstance(rng, py_random.Random) else py_random.Random()
        self.sim_time_s = 0.0
        self.position = Vector2(self.start.x, self.start.y)
        self.velocity = Vector2(0.0, 0.0)
        self._random_heading_deg = self.heading_deg
        self._sync_static()

    # -- public ------------------------------------------------------
    def reset(self, start: Vector2 | None = None) -> None:
        """Restart the trajectory (t = 0)."""
        if start is not None:
            self.start = start
        self.sim_time_s = 0.0
        self.position = Vector2(self.start.x, self.start.y)
        self.velocity = Vector2(0.0, 0.0)
        self._random_heading_deg = self.heading_deg
        self._sync_static()

    def step(self, dt: float) -> tuple[Vector2, Vector2]:
        """Advance by ``dt`` seconds; returns (position, velocity)."""
        dt = max(0.0, float(dt))
        self.sim_time_s += dt
        if self.profile == MotionProfile.REST:
            pass  # position fixed (§28)
        elif self.profile == MotionProfile.CONSTANT_VELOCITY:
            self._constant_velocity(dt)
        elif self.profile == MotionProfile.LINEAR:
            self._linear(dt)
        elif self.profile == MotionProfile.CIRCULAR:
            self._absolute(self._circular_at(self.sim_time_s))
        elif self.profile == MotionProfile.SINUSOIDAL:
            self._absolute(self._sinusoidal_at(self.sim_time_s))
        elif self.profile == MotionProfile.FIGURE_8:
            self._absolute(self._figure8_at(self.sim_time_s))
        elif self.profile == MotionProfile.RANDOM:
            self._random(dt)
        else:  # pragma: no cover - guarded in __init__
            raise ValueError(f"unknown motion profile: {self.profile!r}.")
        return self.position, self.velocity

    # -- helpers -----------------------------------------------------
    def _heading_dir(self) -> Vector2:
        rad = math.radians(self.heading_deg)
        return Vector2(math.cos(rad), math.sin(rad))

    def _sync_static(self) -> None:
        """Exact state for time-invariant profiles (rest / zero speed)."""
        if self.profile == MotionProfile.REST or self.speed_mps <= 0.0:
            if self.profile in (
                MotionProfile.REST,
                MotionProfile.CONSTANT_VELOCITY,
                MotionProfile.LINEAR,
            ):
                self.position = Vector2(self.start.x, self.start.y)
                self.velocity = Vector2(0.0, 0.0)

    def _constant_velocity(self, dt: float) -> None:
        direction = self._heading_dir()
        self.velocity = direction * self.speed_mps  # derived, not editable (§29)
        self.position = self.position + self.velocity * dt

    def _linear(self, dt: float) -> None:
        # Deterministic straight line with a speed ramp 0 → configured (§30).
        ramp = min(1.0, self.sim_time_s / LINEAR_RAMP_DURATION_S)
        direction = self._heading_dir()
        self.velocity = direction * (self.speed_mps * ramp)
        self.position = self.position + self.velocity * dt

    def _absolute(self, pos_vel: tuple[Vector2, Vector2]) -> None:
        self.position, self.velocity = pos_vel

    def _circular_at(self, t: float) -> tuple[Vector2, Vector2]:
        # Circular path; heading sets the initial tangent direction (§31).
        # Tangential speed equals the configured speed: ω = speed / R.
        radius = CIRCULAR_RADIUS_M
        omega = self.speed_mps / radius if radius > 0 else 0.0
        phase0 = math.radians(self.heading_deg) - math.pi / 2.0
        phase = phase0 + omega * t
        pos = Vector2(
            self.start.x + radius * (math.cos(phase) - math.cos(phase0)),
            self.start.y + radius * (math.sin(phase) - math.sin(phase0)),
        )
        vel = Vector2(
            -radius * omega * math.sin(phase),
            radius * omega * math.cos(phase),
        )
        return pos, vel

    def _sinusoidal_at(self, t: float) -> tuple[Vector2, Vector2]:
        # Forward drift along heading + perpendicular oscillation (§32).
        direction = self._heading_dir()
        perp = Vector2(-direction.y, direction.x)
        along = self.speed_mps * t
        cross = SINUSOIDAL_AMPLITUDE_M * math.sin(SINUSOIDAL_OMEGA_RAD_S * t)
        pos = Vector2(self.start.x, self.start.y) + direction * along + perp * cross
        cross_v = SINUSOIDAL_AMPLITUDE_M * SINUSOIDAL_OMEGA_RAD_S * math.cos(
            SINUSOIDAL_OMEGA_RAD_S * t
        )
        vel = direction * self.speed_mps + perp * cross_v
        return pos, vel

    def _figure8_at(self, t: float) -> tuple[Vector2, Vector2]:
        # x = A·sin θ, y = B·sin θ·cos θ, rotated by heading (§33).
        theta = FIGURE8_OMEGA_RAD_S * t
        local = Vector2(
            FIGURE8_AMPLITUDE_X_M * math.sin(theta),
            FIGURE8_AMPLITUDE_Y_M * math.sin(theta) * math.cos(theta),
        )
        local_v = Vector2(
            FIGURE8_AMPLITUDE_X_M * FIGURE8_OMEGA_RAD_S * math.cos(theta),
            FIGURE8_AMPLITUDE_Y_M * FIGURE8_OMEGA_RAD_S * math.cos(2.0 * theta),
        )
        pos = Vector2(self.start.x, self.start.y) + local.rotated(self.heading_deg)
        vel = local_v.rotated(self.heading_deg)
        return pos, vel

    def _random(self, dt: float) -> None:
        # Bounded heading random walk at configured speed (§34): continuous
        # position, bounded velocity, no teleportation, no heading jumps.
        turn = (self.rng.random() * 2.0 - 1.0) * RANDOM_MAX_TURN_DEG_S * dt
        self._random_heading_deg += turn
        rad = math.radians(self._random_heading_deg)
        self.velocity = Vector2(math.cos(rad), math.sin(rad)) * self.speed_mps
        self.position = self.position + self.velocity * dt


__all__ = [
    "MotionModel",
    "LINEAR_RAMP_DURATION_S",
    "CIRCULAR_RADIUS_M",
    "SINUSOIDAL_AMPLITUDE_M",
    "SINUSOIDAL_OMEGA_RAD_S",
    "FIGURE8_AMPLITUDE_X_M",
    "FIGURE8_AMPLITUDE_Y_M",
    "FIGURE8_OMEGA_RAD_S",
    "RANDOM_MAX_TURN_DEG_S",
]
