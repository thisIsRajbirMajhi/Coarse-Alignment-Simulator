# remote_terminal/motion.py - Multi-terminal formations and kinematics per RemoteTerminal.md
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from remote_terminal.config import FormationConfig, MotionConfig


def compute_formation_offsets(
    terminal_count: int,
    formation: FormationConfig,
) -> list[tuple[float, float, float]]:
    """
    Compute relative (dx, dy, dz) offsets for N terminals in a formation,
    rotated by formation.rotation_deg.
    """
    count = max(1, int(terminal_count))
    if count == 1 or formation.shape == "Single":
        return [(0.0, 0.0, 0.0)]

    offsets: list[tuple[float, float, float]] = []
    shape = formation.shape
    rot_rad = math.radians(formation.rotation_deg)
    cos_r = math.cos(rot_rad)
    sin_r = math.sin(rot_rad)

    def _rotate_2d(x: float, y: float, z: float = 0.0) -> tuple[float, float, float]:
        rx = x * cos_r - y * sin_r
        ry = x * sin_r + y * cos_r
        return (rx, ry, z)

    if shape == "Circle":
        radius = float(formation.radius_m)
        for i in range(count):
            angle = 2.0 * math.pi * i / count
            lx = radius * math.cos(angle)
            ly = radius * math.sin(angle)
            offsets.append(_rotate_2d(lx, ly))

    elif shape == "Line":
        spacing = float(formation.spacing_m)
        total_len = (count - 1) * spacing
        for i in range(count):
            lx = -total_len / 2.0 + i * spacing
            offsets.append(_rotate_2d(lx, 0.0))

    elif shape == "Arc":
        radius = float(formation.radius_m)
        span_rad = math.radians(min(180.0, 30.0 * (count - 1)))
        start_ang = -span_rad / 2.0
        step_ang = span_rad / max(1, count - 1)
        for i in range(count):
            ang = start_ang + i * step_ang
            lx = radius * math.cos(ang)
            ly = radius * math.sin(ang) - radius
            offsets.append(_rotate_2d(lx, ly))

    elif shape == "Grid" or shape == "Rectangle":
        cols = max(1, formation.columns)
        rows = max(1, (count + cols - 1) // cols)
        sp_x = float(formation.spacing_m)
        sp_y = float(formation.spacing_m)
        off_x = (cols - 1) * sp_x / 2.0
        off_y = (rows - 1) * sp_y / 2.0
        for i in range(count):
            r = i // cols
            c = i % cols
            lx = c * sp_x - off_x
            ly = r * sp_y - off_y
            offsets.append(_rotate_2d(lx, ly))

    elif shape == "V-Formation":
        spacing = float(formation.spacing_m)
        angle_deg = 35.0
        tan_v = math.tan(math.radians(angle_deg))
        # Apex at center (0, 0)
        offsets.append(_rotate_2d(0.0, 0.0))
        for i in range(1, count):
            side = 1 if i % 2 == 1 else -1
            wing_idx = (i + 1) // 2
            lx = side * wing_idx * spacing
            ly = -wing_idx * spacing * tan_v
            offsets.append(_rotate_2d(lx, ly))

    else:  # Custom / fallback
        spacing = float(formation.spacing_m)
        for i in range(count):
            offsets.append(_rotate_2d(i * spacing, 0.0))

    return offsets


class ScenarioMotionTracker:
    """
    Maintains continuous motion state (anchor position, current velocity, heading)
    and integrates trajectory over time with acceleration ramping and boundary bouncing.
    """

    def __init__(self, motion_config: MotionConfig | None = None, bounds: tuple[int, int] = (2000, 2000)):
        self.config = (motion_config or MotionConfig()).validate()
        self.bounds = bounds
        self.x = float(self.config.start_x)
        self.y = float(self.config.start_y)
        self.z = float(self.config.start_z)
        self.current_speed = 0.0
        self.heading_deg = float(self.config.direction_deg)
        self.sim_time = 0.0
        self._circle_phase = 0.0

    def reset(self, motion_config: MotionConfig | None = None) -> None:
        if motion_config is not None:
            self.config = motion_config.validate()
        self.x = float(self.config.start_x)
        self.y = float(self.config.start_y)
        self.z = float(self.config.start_z)
        self.current_speed = 0.0
        self.heading_deg = float(self.config.direction_deg)
        self.sim_time = 0.0
        self._circle_phase = 0.0

    def update(self, dt: float) -> tuple[float, float, float]:
        """
        Advance motion state by dt seconds.
        Returns anchor (x, y, z).
        """
        dt = float(max(1e-4, min(dt, 0.5)))
        self.sim_time += dt

        target_speed = float(self.config.speed_mps)
        accel = float(self.config.acceleration_mps2)
        if accel > 1e-3:
            if self.current_speed < target_speed:
                self.current_speed = min(target_speed, self.current_speed + accel * dt)
            elif self.current_speed > target_speed:
                self.current_speed = max(target_speed, self.current_speed - accel * dt)
        else:
            self.current_speed = target_speed

        profile = self.config.profile
        bw, bh = self.bounds
        margin = 80.0

        if profile == "Stationary":
            pass

        elif profile == "Constant Velocity" or profile == "Linear":
            heading_rad = math.radians(self.heading_deg)
            vx = self.current_speed * math.cos(heading_rad)
            vy = self.current_speed * math.sin(heading_rad)
            self.x += vx * dt
            self.y += vy * dt

            # Smooth soft bounce off world boundaries
            if self.x < margin:
                self.x = margin
                self.heading_deg = 180.0 - self.heading_deg
            elif self.x > bw - margin:
                self.x = bw - margin
                self.heading_deg = 180.0 - self.heading_deg
            if self.y < margin:
                self.y = margin
                self.heading_deg = -self.heading_deg
            elif self.y > bh - margin:
                self.y = bh - margin
                self.heading_deg = -self.heading_deg
            self.heading_deg = self.heading_deg % 360.0

        elif profile == "Circular":
            radius = max(50.0, min(float(self.config.speed_mps) * 10.0, 300.0) if self.config.speed_mps > 1e-2 else 120.0)
            omega = (self.current_speed / radius) if radius > 1e-2 else 0.1
            self._circle_phase = (self._circle_phase + omega * dt) % (2.0 * math.pi)
            # Center of orbit chosen so that at _circle_phase == 0, x == start_x, y == start_y
            cx = float(self.config.start_x) - radius
            cy = float(self.config.start_y)
            self.x = cx + radius * math.cos(self._circle_phase)
            self.y = cy + radius * math.sin(self._circle_phase)

        elif profile == "Sinusoidal":
            heading_rad = math.radians(self.heading_deg)
            fwd_x = math.cos(heading_rad)
            fwd_y = math.sin(heading_rad)
            lat_x = -fwd_y
            lat_y = fwd_x

            # Forward progress + lateral sine oscillation integrated via derivative
            dist_fwd = self.current_speed * dt
            sine_amp = 60.0
            sine_freq = 0.2
            # Derivative d(A * sin(2*pi*f*t))/dt = A * 2*pi*f * cos(2*pi*f*t)
            lat_vel = sine_amp * (2.0 * math.pi * sine_freq) * math.cos(2.0 * math.pi * sine_freq * self.sim_time)

            self.x += fwd_x * dist_fwd + lat_x * lat_vel * dt
            self.y += fwd_y * dist_fwd + lat_y * lat_vel * dt

            # Check bounds and reflect
            if self.x < margin or self.x > bw - margin or self.y < margin or self.y > bh - margin:
                self.heading_deg = (self.heading_deg + 180.0) % 360.0
                self.x = float(np.clip(self.x, margin, bw - margin))
                self.y = float(np.clip(self.y, margin, bh - margin))

        return (self.x, self.y, self.z)
