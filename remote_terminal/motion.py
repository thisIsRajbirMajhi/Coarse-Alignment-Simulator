# remote_terminal/motion.py - MotionModel: trajectory only (Plan Hybrid-AI §1).
#
# Pruned to 5 profiles: REST, CONSTANT_VELOCITY, CIRCULAR, FIGURE_8, RANDOM.
# LINEAR merged into CONSTANT_VELOCITY, SINUSOIDAL deleted (dup of FIGURE_8).

from __future__ import annotations

import math
import random as py_random

from remote_terminal.config import MotionProfile
from remote_terminal.models import Vector2

# Internal model constants (NOT GUI parameters).
CIRCULAR_RADIUS_M: float = 500.0
FIGURE8_AMPLITUDE_X_M: float = 100.0
FIGURE8_AMPLITUDE_Y_M: float = 100.0
FIGURE8_OMEGA_RAD_S: float = 0.25
RANDOM_MAX_TURN_DEG_S: float = 20.0


class MotionModel:
    """Formation-center motion for one scenario."""

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
        # Map legacy LINEAR/SINUSOIDAL to canonical profiles for backward compat
        legacy_map = {"linear": MotionProfile.CONSTANT_VELOCITY, "sinusoidal": MotionProfile.FIGURE_8}
        if isinstance(profile, str):
            profile = legacy_map.get(profile.lower(), profile)
        # If enum value is string legacy (should not happen after prune, but handle)
        try:
            if profile.value == "linear":
                profile = MotionProfile.CONSTANT_VELOCITY
            elif profile.value == "sinusoidal":
                profile = MotionProfile.FIGURE_8
        except Exception:
            pass
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

    def reset(self, start: Vector2 | None = None) -> None:
        if start is not None:
            self.start = start
        self.sim_time_s = 0.0
        self.position = Vector2(self.start.x, self.start.y)
        self.velocity = Vector2(0.0, 0.0)
        self._random_heading_deg = self.heading_deg
        self._sync_static()

    def step(self, dt: float) -> tuple[Vector2, Vector2]:
        dt = max(0.0, float(dt))
        self.sim_time_s += dt
        if self.profile == MotionProfile.REST:
            pass
        elif self.profile == MotionProfile.CONSTANT_VELOCITY:
            self._constant_velocity(dt)
        elif self.profile == MotionProfile.CIRCULAR:
            self._absolute(self._circular_at(self.sim_time_s))
        elif self.profile == MotionProfile.FIGURE_8:
            self._absolute(self._figure8_at(self.sim_time_s))
        elif self.profile == MotionProfile.RANDOM:
            self._random(dt)
        else:
            raise ValueError(f"unknown motion profile: {self.profile!r}.")
        return self.position, self.velocity

    def _heading_dir(self) -> Vector2:
        rad = math.radians(self.heading_deg)
        return Vector2(math.cos(rad), math.sin(rad))

    def _sync_static(self) -> None:
        if self.profile == MotionProfile.REST or self.speed_mps <= 0.0:
            if self.profile in (MotionProfile.REST, MotionProfile.CONSTANT_VELOCITY):
                self.position = Vector2(self.start.x, self.start.y)
                self.velocity = Vector2(0.0, 0.0)

    def _constant_velocity(self, dt: float) -> None:
        direction = self._heading_dir()
        self.velocity = direction * self.speed_mps
        self.position = self.position + self.velocity * dt

    def _absolute(self, pos_vel: tuple[Vector2, Vector2]) -> None:
        self.position, self.velocity = pos_vel

    def _circular_at(self, t: float) -> tuple[Vector2, Vector2]:
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

    def _figure8_at(self, t: float) -> tuple[Vector2, Vector2]:
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
        turn = (self.rng.random() * 2.0 - 1.0) * RANDOM_MAX_TURN_DEG_S * dt
        self._random_heading_deg += turn
        rad = math.radians(self._random_heading_deg)
        self.velocity = Vector2(math.cos(rad), math.sin(rad)) * self.speed_mps
        self.position = self.position + self.velocity * dt


__all__ = [
    "MotionModel",
    "CIRCULAR_RADIUS_M",
    "FIGURE8_AMPLITUDE_X_M",
    "FIGURE8_AMPLITUDE_Y_M",
    "FIGURE8_OMEGA_RAD_S",
    "RANDOM_MAX_TURN_DEG_S",
]
