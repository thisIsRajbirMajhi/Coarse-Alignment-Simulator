# remote_terminal/scenario.py - Remote Terminal Scenario manager per RemoteTerminal.md
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from remote_terminal.config import RemoteTerminalConfig, RemoteTerminalScenarioConfig
from remote_terminal.motion import ScenarioMotionTracker, compute_formation_offsets
from remote_terminal.terminal import RemoteTerminal


class RemoteTerminalScenario:
    """
    Orchestrates the Remote Terminal Scenario:
      - Group-level formation & motion kinematics
      - Individual RemoteTerminal synchronization
      - Line-of-sight & target signature matching
      - Communication link state progression:
        NO LINK -> DETECTING -> OPTICAL LOCK -> HANDSHAKE -> CONNECTED
    """

    def __init__(
        self,
        config: RemoteTerminalScenarioConfig | None = None,
        bounds: tuple[int, int] = (2000, 2000),
        rng: np.random.Generator | None = None,
    ):
        self.bounds = bounds
        self.rng = rng or np.random.default_rng(42)
        self.config = (config or RemoteTerminalScenarioConfig()).validate()
        self.motion_tracker = ScenarioMotionTracker(self.config.motion, bounds=bounds, rng=rng)
        self.terminals: list[RemoteTerminal] = []
        self._lock_timers: dict[str, float] = {}
        self._rebuild_terminals()

    def _rebuild_terminals(self) -> None:
        self.terminals = [RemoteTerminal(cfg) for cfg in self.config.terminals]
        self._sync_terminal_positions()

    def _sync_terminal_positions(self) -> None:
        ax, ay = self.motion_tracker.x, self.motion_tracker.y
        offsets = compute_formation_offsets(len(self.terminals), self.config.formation)
        for t, (dx, dy) in zip(self.terminals, offsets):
            t.set_position(ax + dx, ay + dy)

    def apply_config(self, config: RemoteTerminalScenarioConfig) -> None:
        self.config = config.validate()
        # Avoid abrupt jumps if starting anchor and profile did not change
        if (
            self.motion_tracker.config.start_x != self.config.motion.start_x
            or self.motion_tracker.config.start_y != self.config.motion.start_y
            or self.motion_tracker.config.profile != self.config.motion.profile
        ):
            self.motion_tracker.reset(self.config.motion)
        else:
            self.motion_tracker.config = self.config.motion

        # Preserve existing terminals to avoid resetting runtime link dwell and sim_time
        existing = {t.config.identity.id: t for t in self.terminals}
        new_terminals = []
        for cfg in self.config.terminals:
            if cfg.identity.id in existing:
                t = existing[cfg.identity.id]
                t.config = cfg
                t._sync_states()
                new_terminals.append(t)
            else:
                new_terminals.append(RemoteTerminal(cfg))
        self.terminals = new_terminals
        self._sync_terminal_positions()

    def get_visible_terminals(self, camera) -> list[Any]:
        if camera is None:
            return []
        x0, y0, x1, y1 = camera.get_fov_rect()
        return [t for t in self.terminals if x0 <= t.x <= x1 and y0 <= t.y <= y1]

    def update(self, dt: float, camera=None) -> None:
        """Advance scenario motion, update each terminal, and evaluate link progression."""
        dt = float(max(1e-4, min(dt, 0.2)))
        self.motion_tracker.update(dt)
        self._sync_terminal_positions()

        # Camera FOV bounds and center
        if camera is not None:
            fov_x0, fov_y0, fov_x1, fov_y1 = camera.get_fov_rect()
            cam_cx = (fov_x0 + fov_x1) / 2.0
            cam_cy = (fov_y0 + fov_y1) / 2.0
            fov_w = max(1.0, fov_x1 - fov_x0)
            fov_h = max(1.0, fov_y1 - fov_y0)
            pixel_scale = getattr(getattr(camera, "config", None), "pixel_scale_mrad", None)
            if pixel_scale is None:
                try:
                    am = getattr(getattr(camera, "config", None), "angular_model", None)
                    pixel_scale = float(am.pixel_to_angle_x) * 0.001 if am is not None else 0.109083
                except Exception:
                    pixel_scale = 0.109083
        else:
            fov_x0, fov_y0, fov_x1, fov_y1 = 0, 0, 0, 0
            cam_cx, cam_cy = 1000.0, 1000.0
            fov_w, fov_h = 640, 480
            pixel_scale = 0.109083

        for t in self.terminals:
            t.update(dt)
            tid = t.config.identity.id
            dwell = self._lock_timers.get(tid, 0.0)

            if camera is None:
                if t.is_emitting:
                    dwell += dt
                    self._lock_timers[tid] = dwell
                    t.config.state.communication_state = "EMITTING"
                else:
                    dwell = max(0.0, dwell - dt * 2.0)
                    self._lock_timers[tid] = dwell
                    t.config.state.communication_state = "NO_LINK"
                continue

            if not t.is_emitting:
                # No emission -> link decays to NO_LINK
                dwell = max(0.0, dwell - dt * 2.0)
                self._lock_timers[tid] = dwell
                t.config.state.communication_state = "NO_LINK"
                continue

            # 2D link: presence + dwell only.
            in_fov = (fov_x0 <= t.x <= fov_x1) and (fov_y0 <= t.y <= fov_y1)
            dist_to_center = math.hypot(t.x - cam_cx, t.y - cam_cy)
            lock_radius = min(fov_w, fov_h) * 0.15

            if in_fov:
                dwell += dt
                self._lock_timers[tid] = dwell

                if dist_to_center <= lock_radius:
                    # Link timing: 0.2s LOCK / 0.5s HANDSHAKE / 1.2s CONNECTED
                    if dwell >= 1.2:
                        t.config.state.communication_state = "CONNECTED"
                    elif dwell >= 0.5:
                        t.config.state.communication_state = "HANDSHAKE"
                    elif dwell >= 0.2:
                        t.config.state.communication_state = "OPTICAL_LOCK"
                    else:
                        t.config.state.communication_state = "DETECTING"
                else:
                    t.config.state.communication_state = "DETECTING"
            else:
                dwell = max(0.0, dwell - dt * 1.5)
                self._lock_timers[tid] = dwell
                if dwell > 0.4:
                    t.config.state.communication_state = "DETECTING"
                else:
                    t.config.state.communication_state = "NO_LINK"

    def render_beacons(self, frame: np.ndarray, camera=None, channel=None,
                       pipeline=None, rng=None, dt: float = 1.0 / 30.0,
                       distance_m: float | None = None,
                       target_rect: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """Blends terminal optical spots into the given frame (world or FOV)."""
        if frame is None:
            return frame

        display = frame.copy()
        if target_rect is not None:
            fov_rect = target_rect
            pixel_scale = 0.035
        elif camera is not None:
            fov_rect = camera.get_fov_rect()
            pixel_scale = getattr(getattr(camera, "config", None), "pixel_scale_mrad", 0.035)
        else:
            fh, fw = display.shape[:2]
            fov_rect = (0, 0, fw, fh)
            pixel_scale = 0.035

        fh, fw = display.shape[:2]

        for t in self.terminals:
            patch, px, py = t.render_to_fov(fov_rect, pixel_scale_mrad=pixel_scale)
            if patch is None:
                continue

            # Route the ideal beam through the Propagation Channel when one
            # is supplied: wander shifts the spot, attenuation/spread reshape
            # the patch. This keeps channel effects in the optical domain.
            if pipeline is not None or channel is not None:
                try:
                    ideal = t.emit_ideal_beam(pixel_scale_mrad=pixel_scale)
                    if pipeline is not None:
                        received = pipeline.propagate_beam(ideal, dt=dt, distance_m=distance_m)
                        applier = pipeline.optical.channel
                    else:
                        from common.rng import get_rng as _get_rng
                        _rng = _get_rng(rng)
                        received = channel.propagate_beam(ideal, dt=dt, rng=_rng, distance_m=distance_m)
                        applier = channel
                    dx = float(received.position[0] - ideal.position[0])
                    dy = float(received.position[1] - ideal.position[1])
                    px = int(round(px + dx))
                    py = int(round(py + dy))
                    patch = applier.apply_to_patch(patch, received)
                    if received.intensity <= 1e-6:
                        continue
                except (AttributeError, TypeError, ValueError):
                    pass

            ph, pw = patch.shape[:2]
            # Clip patch to FOV canvas
            x0_src = max(0, -px)
            y0_src = max(0, -py)
            x1_src = min(pw, fw - px)
            y1_src = min(ph, fh - py)

            x0_dst = max(0, px)
            y0_dst = max(0, py)
            x1_dst = min(fw, px + pw)
            y1_dst = min(fh, py + ph)

            w = min(x1_dst - x0_dst, x1_src - x0_src)
            h = min(y1_dst - y0_dst, y1_src - y0_src)
            if w > 0 and h > 0:
                sub_dst = display[y0_dst : y0_dst + h, x0_dst : x0_dst + w].astype(np.float32)
                sub_src = patch[y0_src : y0_src + h, x0_src : x0_src + w].astype(np.float32)
                # Optical additive blending with screen saturation
                blended = np.clip(sub_dst + sub_src - (sub_dst * sub_src) / 255.0, 0, 255).astype(np.uint8)
                display[y0_dst : y0_dst + h, x0_dst : x0_dst + w] = blended

        return display

    render_fov_beacons = render_beacons

    def get_telemetry(self) -> dict[str, Any]:
        """Summary telemetry for UI and presenters."""
        term_data = [t.get_telemetry() for t in self.terminals]
        emitting_count = sum(1 for t in self.terminals if t.is_emitting)
        connected_count = sum(1 for t in self.terminals if t.config.state.communication_state == "CONNECTED")
        best_link = "NO_LINK"
        for st in ("CONNECTED", "HANDSHAKE", "OPTICAL_LOCK", "DETECTING", "NO_LINK"):
            if any(t.config.state.communication_state == st for t in self.terminals):
                best_link = st
                break

        return {
            "terminal_count": len(self.terminals),
            "emitting_count": emitting_count,
            "connected_count": connected_count,
            "best_link": best_link,
            "anchor_pos": (self.motion_tracker.x, self.motion_tracker.y),
            "current_speed": self.motion_tracker.current_speed,
            "heading_deg": self.motion_tracker.heading_deg,
            "terminals": term_data,
        }
