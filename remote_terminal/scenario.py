# remote_terminal/scenario.py - RemoteTerminalManager: multi-terminal (§§15, 68).
#
# Update flow (§68): formation-center motion → formation offsets → per
# terminal: motion state → position → velocity → geometry → pointing →
# beacon → optical emission → RemoteScenarioRuntime.
#
# SIM INTEGRATION ASSUMPTIONS (documented, deterministic):
#   * Metre-to-pixel mapping is 1 m = 1 px (``M_PER_PX``).
#   * The formation center starts at the scene-bounds center (position is
#     deliberately NOT a GUI parameter — RemoteTerminal.md §79).
#   * The geometric reference (intended receiver) defaults to the scene
#     center; override via ``reference_m``.
#   * ``render_spots`` is visualization-only: a gaussian marker whose floor
#     size keeps sub-pixel beams visible. Physics lives in telemetry and
#     OpticalEmission, not in the marker.
from __future__ import annotations

import random as py_random
from typing import Any

import numpy as np

from common.rng import substream
from remote_terminal.config import RemoteScenarioConfig, make_default_scenario
from remote_terminal.formation import FormationManager
from remote_terminal.models import RemoteScenarioRuntime, Vector2
from remote_terminal.motion import MotionModel
from remote_terminal.terminal import RemoteTerminal

M_PER_PX: float = 1.0
MIN_SPOT_SIGMA_PX: float = 3.0
POWER_REF_W: float = 1.0  # visualization brightness normalization


class RemoteTerminalManager:
    """Owns the formation center trajectory and all terminals."""

    def __init__(
        self,
        config: RemoteScenarioConfig | None = None,
        bounds: tuple[int, int] = (2000, 2000),
        seed: int = 42,
        reference_m: Vector2 | None = None,
    ):
        self.config = (config if config is not None else make_default_scenario()).validate()
        self.bounds = (max(1, int(bounds[0])), max(1, int(bounds[1])))
        self.seed = int(seed)
        self.sim_time_s = 0.0
        self._formation = FormationManager()
        center = Vector2(self.bounds[0] / 2.0, self.bounds[1] / 2.0)
        self._center = center
        self.reference_m = reference_m or Vector2(center.x, center.y)
        self._motion_rng = py_random.Random(self.seed)
        self._point_rng = substream(self.seed, "remote_terminal", "pointing")
        form = self.config.formation
        self._motion = MotionModel(
            speed_mps=form.speed_mps,
            heading_deg=form.heading_deg,
            profile=form.motion_profile,
            start=Vector2(center.x, center.y),
            rng=self._motion_rng,
        )
        self.terminals: list[RemoteTerminal] = [
            RemoteTerminal(cfg, terminal_index=i)
            for i, cfg in enumerate(self.config.terminals)
        ]
        self._offsets = self._compute_offsets()
        self.runtime = RemoteScenarioRuntime(
            simulation_time_s=0.0,
            formation_center_m=Vector2(center.x, center.y),
            terminals=[],
        )

    # -- lifecycle ---------------------------------------------------
    def apply_config(self, config: RemoteScenarioConfig) -> None:
        """Replace configuration (validated); re-sync motion and terminals.

        Beacon sequences restart: new generators begin at sequence 0.
        Simulation time keeps running.
        """
        self.config = config.validate()
        form = self.config.formation
        # Preserve the live center across reconfiguration.
        self._motion = MotionModel(
            speed_mps=form.speed_mps,
            heading_deg=form.heading_deg,
            profile=form.motion_profile,
            start=Vector2(self._center.x, self._center.y),
            rng=self._motion_rng,
        )
        self.terminals = [
            RemoteTerminal(cfg, terminal_index=i)
            for i, cfg in enumerate(self.config.terminals)
        ]
        self._offsets = self._compute_offsets()

    def update(self, dt: float) -> RemoteScenarioRuntime:
        """Advance the scenario by ``dt`` seconds (§68)."""
        dt = float(max(0.0, dt))
        self.sim_time_s += dt
        center, velocity = self._motion.step(dt)

        # Boundary containment: ensure formation center and all terminals stay inside world bounds
        bw = float(self.bounds[0])
        bh = float(self.bounds[1])
        max_ox = max((abs(o.x) for o in self._offsets), default=0.0)
        max_oy = max((abs(o.y) for o in self._offsets), default=0.0)
        margin_x = max(30.0, max_ox + 20.0)
        margin_y = max(30.0, max_oy + 20.0)

        cx, cy = center.x, center.y
        vx, vy = velocity.x, velocity.y

        bounced = False
        # Reflect off left/right vertical boundary walls
        if cx <= margin_x:
            cx = margin_x
            if vx < 0:
                vx = -vx
                bounced = True
                if hasattr(self._motion, "heading_deg"):
                    self._motion.heading_deg = (180.0 - self._motion.heading_deg) % 360.0
                if hasattr(self._motion, "_random_heading_deg"):
                    self._motion._random_heading_deg = (180.0 - self._motion._random_heading_deg) % 360.0
        elif cx >= bw - margin_x:
            cx = bw - margin_x
            if vx > 0:
                vx = -vx
                bounced = True
                if hasattr(self._motion, "heading_deg"):
                    self._motion.heading_deg = (180.0 - self._motion.heading_deg) % 360.0
                if hasattr(self._motion, "_random_heading_deg"):
                    self._motion._random_heading_deg = (180.0 - self._motion._random_heading_deg) % 360.0

        # Reflect off top/bottom horizontal boundary walls
        if cy <= margin_y:
            cy = margin_y
            if vy < 0:
                vy = -vy
                bounced = True
                if hasattr(self._motion, "heading_deg"):
                    self._motion.heading_deg = (-self._motion.heading_deg) % 360.0
                if hasattr(self._motion, "_random_heading_deg"):
                    self._motion._random_heading_deg = (-self._motion._random_heading_deg) % 360.0
        elif cy >= bh - margin_y:
            cy = bh - margin_y
            if vy > 0:
                vy = -vy
                bounced = True
                if hasattr(self._motion, "heading_deg"):
                    self._motion.heading_deg = (-self._motion.heading_deg) % 360.0
                if hasattr(self._motion, "_random_heading_deg"):
                    self._motion._random_heading_deg = (-self._motion._random_heading_deg) % 360.0

        if bounced:
            self._motion.velocity = Vector2(vx, vy)
            self._motion.position = Vector2(cx, cy)
            self._motion.start = Vector2(cx, cy)
            self._motion.sim_time_s = 0.0

        center = Vector2(cx, cy)
        velocity = Vector2(vx, vy)
        self._center = center

        runtimes = []
        for terminal, offset in zip(self.terminals, self._offsets):
            pos_x = max(10.0, min(bw - 10.0, center.x + offset.x))
            pos_y = max(10.0, min(bh - 10.0, center.y + offset.y))
            pos = Vector2(pos_x, pos_y)
            runtimes.append(
                terminal.step(
                    dt=dt,
                    sim_time_s=self.sim_time_s,
                    position_m=pos,
                    velocity_mps=Vector2(velocity.x, velocity.y),
                    reference_m=self.reference_m,
                    rng=self._point_rng,
                )
            )
        self.runtime = RemoteScenarioRuntime(
            simulation_time_s=self.sim_time_s,
            formation_center_m=Vector2(center.x, center.y),
            terminals=runtimes,
        )
        return self.runtime

    # -- outputs -----------------------------------------------------
    def get_telemetry(self) -> dict[str, Any]:
        """Scenario telemetry snapshot.

        Per-terminal ``emitting`` reports the emission GATE (power + beacon
        switches and BEACONING/LINKED state); ``instantaneous_power_w`` is
        the chip-level truth (0 W on an OOK low chip while gated on).
        """
        terms = [t.get_telemetry() for t in self.terminals]
        emitting = sum(1 for t in terms if t["emitting"])
        return {
            "terminal_count": len(terms),
            "emitting_count": emitting,
            "simulation_time_s": self.sim_time_s,
            "formation_center_m": self._center.as_tuple(),
            "reference_m": self.reference_m.as_tuple(),
            "terminals": terms,
        }

    def render_spots(self, frame: np.ndarray) -> np.ndarray:
        """Blend visualization markers for emitting terminals into ``frame``.

        Marker: 2D gaussian, sigma from the beam footprint (floored for
        visibility), peak brightness normalized by ``POWER_REF_W``.
        """
        if frame is None or not self.terminals:
            return frame
        out = frame
        h, w = frame.shape[:2]
        for terminal in self.terminals:
            power = float(terminal.runtime.instantaneous_power_w)
            if not terminal.runtime.effective_emission_enabled or power <= 0.0:
                continue
            cx = terminal.position_m.x * M_PER_PX
            cy = terminal.position_m.y * M_PER_PX
            if not (-50 <= cx < w + 50 and -50 <= cy < h + 50):
                continue
            sigma = max(float(terminal.runtime.beam_diameter_m) / 2.0, MIN_SPOT_SIGMA_PX)
            peak = float(np.clip(power / POWER_REF_W, 0.0, 1.0)) * 255.0
            out = _add_gaussian_spot(out, cx, cy, sigma, peak)
        return out

    # -- internals ---------------------------------------------------
    def _compute_offsets(self) -> list[Vector2]:
        form = self.config.formation
        return self._formation.oriented_offsets(
            form.terminal_count,
            form.formation_shape,
            form.terminal_spacing_m,
            form.heading_deg,
        )


def _add_gaussian_spot(
    frame: np.ndarray, cx: float, cy: float, sigma: float, peak: float
) -> np.ndarray:
    radius = int(max(1.0, sigma * 3.0))
    x0, x1 = int(round(cx)) - radius, int(round(cx)) + radius + 1
    y0, y1 = int(round(cy)) - radius, int(round(cy)) + radius + 1
    h, w = frame.shape[:2]
    if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
        return frame
    xs = np.arange(x0, x1, dtype=np.float64)
    ys = np.arange(y0, y1, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)
    patch = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma * sigma))
    patch *= float(peak)
    fx0, fx1 = max(0, x0), min(w, x1)
    fy0, fy1 = max(0, y0), min(h, y1)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    region = frame[fy0:fy1, fx0:fx1].astype(np.float64)
    spot = patch[fy0 - y0 : fy1 - y0, fx0 - x0 : fx1 - x0]
    if spot.ndim == 2 and region.ndim == 3:
        spot = spot[:, :, None]
    np.add(region, spot, out=region)
    np.clip(region, 0, 255, out=region)
    frame[fy0:fy1, fx0:fx1] = region.astype(frame.dtype)
    return frame


__all__ = ["RemoteTerminalManager", "M_PER_PX", "MIN_SPOT_SIGMA_PX", "POWER_REF_W"]
