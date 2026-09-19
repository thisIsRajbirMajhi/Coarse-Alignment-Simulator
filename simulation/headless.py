# simulation/headless.py - Headless FSOC simulation (no Qt, deterministic, gym-compatible)
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from common.rng import get_rng, seed_global
from disturbance import disturbances as dist
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline
from environment.config import EnvironmentConfig
from environment.scene import Scene
from local_terminal import LocalTerminal, LocalTerminalConfig
from remote_terminal import RemoteTerminalScenario, RemoteTerminalScenarioConfig


@dataclass
class HeadlessConfig:
    """Aggregated config for HeadlessSimulation - all validated, single source."""
    seed: int = 42
    env: EnvironmentConfig | None = None
    camera: LocalTerminalConfig | None = None
    local_terminal: LocalTerminalConfig | None = None
    controller: Any | None = None
    disturbance: DisturbanceConfig | None = None
    scenario: RemoteTerminalScenarioConfig | None = None
    max_steps: int = 2000
    dt: float = 1 / 30
    sim_speed: float = 1.0


class HeadlessSimulation:
    """
    Headless FSOC simulator — deterministic, no Qt.

    Pipeline:
      scene.update → local_terminal.update → disturbances → capture FOV → local_terminal.move (direct action)
    """

    def __init__(
        self,
        seed: int = 42,
        env_config: EnvironmentConfig | None = None,
        camera_config: LocalTerminalConfig | None = None,
        local_terminal_config: LocalTerminalConfig | None = None,
        controller_config: Any | None = None,
        disturbance_config: DisturbanceConfig | None = None,
        scenario_config: RemoteTerminalScenarioConfig | None = None,
        rng: np.random.Generator | None = None,
        max_steps: int = 2000,
        dt: float = 1 / 30,
        sim_speed: float = 1.0,
        **kwargs,
    ):
        self.seed = int(seed)
        self.rng: np.random.Generator = get_rng(rng, self.seed)
        seed_global(self.seed)

        self.dt = float(dt)
        self.sim_speed = float(sim_speed)
        self.max_steps = int(max_steps)
        self.step_count = 0

        self.env_config = (env_config or EnvironmentConfig()).validate()
        if env_config is None:
            self.env_config.seed = self.seed
            self.env_config.validate()
        self._scene_size = (int(self.env_config.world_width), int(self.env_config.world_height))

        # Local Terminal configuration (replaces standalone camera system)
        lt_cfg = local_terminal_config or camera_config or kwargs.get("local_terminal")
        if lt_cfg is None:
            lt_cfg = LocalTerminalConfig()
        elif not isinstance(lt_cfg, LocalTerminalConfig):
            lt_cfg = LocalTerminalConfig.from_camera_config(lt_cfg)
        self.local_terminal_config = lt_cfg.validate(self._scene_size)
        # Compatibility property alias
        self.camera_config = self.local_terminal_config

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.scenario_config = (scenario_config or RemoteTerminalScenarioConfig()).validate()

        self._camera_drift_state: dict = {}
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}
        self._last_frame: np.ndarray | None = None

        self._build_simulation()
        self._disturbance_pipeline = DisturbancePipeline(
            DisturbanceContext(self.disturbance_config, rng=self.rng, dt=self.dt),
            bounds=self._scene_size,
        )

    @property
    def controller_config(self):
        """Compatibility property forwarding to Local Terminal tracking config."""
        return self.local_terminal_config.tracking

    def _build_simulation(self):
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)

        sw, sh = self._scene_size
        lt_cfg = self.local_terminal_config.validate((sw, sh))
        self.local_terminal_config = lt_cfg
        self.camera_config = lt_cfg
        self._fov_size = (int(lt_cfg.camera.resolution_width), int(lt_cfg.camera.resolution_height))

        self.local_terminal = LocalTerminal(config=lt_cfg, scene_bounds=(sw, sh), rng=self.rng)
        # Compatibility alias for external callers
        self.camera = self.local_terminal

        try:
            vig = float(cfg.vignetting_pct) / 100.0
            self.local_terminal.set_vignetting(vig)
        except Exception:
            pass

        self.terminal_scenario = RemoteTerminalScenario(self.scenario_config, bounds=self._scene_size, rng=self.rng)

        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        self._last_frame = None

    def _capture_fov_frame(self, dt_eff: float = 1 / 30) -> np.ndarray:
        # Already validated at __init__/reset/apply — no per-frame validate()
        # (~450-line dual-sync + string normalizes each frame).
        dc = self.disturbance_config
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            self.camera.set_vignetting(vig)
        except (AttributeError, TypeError, ValueError):
            vig = 0.0

        self._disturbance_pipeline.context.config = dc
        self._disturbance_pipeline.context.rng = self.rng
        # Keep ground truth: disturb a copy, render from disturbed pose,
        # then restore true pose so telemetry/observations stay truthful.
        true_pan, true_tilt = float(self.camera.pan), float(self.camera.tilt)
        pan_dist, tilt_dist = self._disturbance_pipeline.disturb_camera_pose(
            true_pan, true_tilt, dt_eff,
        )

        try:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)
        except AttributeError:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)

        x0, y0, x1, y1 = self.camera.get_fov_rect()
        fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))

        if hasattr(self, "terminal_scenario") and self.terminal_scenario is not None:
            try:
                # Beam-state propagation: ideal beacons → channel → received
                # spots, before camera/image-formation and sensor stages.
                fov_frame = self.terminal_scenario.render_fov_beacons(
                    fov_frame, self.camera,
                    pipeline=self._disturbance_pipeline, rng=self.rng, dt=dt_eff,
                )
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass

        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
            except (AttributeError, TypeError, ValueError):
                pass

        # disturb_camera_pose() already advanced context time once; apply
        # optical+sensor without a second advance so turbulence ages 1x/frame.
        try:
            from simulation.fov_pipeline import apply_post_noise as _post
            fov_frame = _post(
                fov_frame, dc, dt_eff, self.rng, self._disturbance_pipeline,
                advance=False,
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            fov_frame = dist.apply_turbulence(fov_frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=self.rng)

        # Restore true pose; capture pose/rect refer to disturbed view.
        try:
            self.camera.set_position(float(true_pan), float(true_tilt), clear_queue=False)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            self._last_capture_pose = (float(pan_dist), float(tilt_dist))
            self._last_fov_rect = (int(x0), int(y0), int(x1), int(y1))
            self._true_pose = (float(true_pan), float(true_tilt))
        except (AttributeError, TypeError, ValueError):
            pass

        return fov_frame

    def reset(self, seed: int | None = None) -> dict:
        if seed is not None:
            self.seed = int(seed)
            self.rng = get_rng(None, self.seed)
            seed_global(self.seed)
            self.env_config.seed = self.seed
            self.env_config.validate()
        self.step_count = 0
        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
        except Exception:
            pass
        self._build_simulation()
        self._disturbance_pipeline.reset()
        self._disturbance_pipeline.context.config = self.disturbance_config
        self._disturbance_pipeline.context.rng = self.rng
        self._last_frame = self._capture_fov_frame(self.dt)
        obs = self.get_observation()
        obs["frame"] = self._last_frame
        return obs

    def get_observation(self) -> dict:
        # pan/tilt = ground truth; disturbed capture pose exposed separately.
        fov_rect = getattr(self, "_last_fov_rect", None)
        if fov_rect is None:
            try:
                fov_rect = self.camera.get_fov_rect()
            except Exception:
                fov_rect = (0, 0, 0, 0)
        cap = getattr(self, "_last_capture_pose", None)
        obs = {
            "pan": float(self.camera.pan),
            "tilt": float(self.camera.tilt),
            "fov_rect": fov_rect,
            "world_size": self._scene_size,
            "fov_size": self._fov_size,
            "step_count": self.step_count,
        }
        if cap is not None:
            try:
                obs["pan_disturbed"] = float(cap[0])
                obs["tilt_disturbed"] = float(cap[1])
            except Exception:
                pass
        if hasattr(self, "local_terminal") and self.local_terminal is not None:
            try:
                obs["local_terminal"] = self.local_terminal.get_telemetry()
            except Exception:
                pass
        if hasattr(self, "terminal_scenario") and self.terminal_scenario is not None:
            try:
                obs["terminals"] = self.terminal_scenario.get_telemetry()
            except Exception:
                pass
        if self._last_frame is not None:
            obs["frame"] = self._last_frame
        return obs

    def step(self, action: np.ndarray | tuple | None = None, dt: float | None = None) -> tuple[dict, float, bool, bool, dict]:
        dt = float(dt if dt is not None else self.dt)
        # Single timebase: sim_speed scales everything (scene, scenario,
        # actuator, tracker, disturbances) so physics stay consistent.
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))

        try:
            self.scene.update(dt_eff)
        except Exception:
            pass
        if hasattr(self, "terminal_scenario") and self.terminal_scenario is not None:
            try:
                self.terminal_scenario.update(dt_eff, camera=self.camera)
            except Exception:
                pass
        try:
            self.local_terminal.update(
                dt_eff,
                fov_frame=self._last_frame,
                fov_capture_pose=getattr(self, "_last_capture_pose", None),
            )
        except Exception:
            try:
                self.camera.update(dt_eff)
            except Exception:
                pass

        # Direct action (manual override / gym action) applied BEFORE capture
        # so the returned frame reflects the action (no 1-step delay).
        if action is not None:
            try:
                arr = np.asarray(action, dtype=float).reshape(-1)
                d_pan = float(arr[0]) if len(arr) > 0 else 0.0
                d_tilt = float(arr[1]) if len(arr) > 1 else 0.0
                try:
                    self.camera.move(d_pan, d_tilt, dt_eff)
                except Exception:
                    self.camera.move(d_pan, d_tilt)
                try:
                    self.camera.flush_pending()
                except Exception:
                    pass
            except Exception:
                pass

        # Capture disturbed frame
        fov_frame = self._capture_fov_frame(dt_eff)
        self._last_frame = fov_frame

        self.step_count += 1
        reward = 0.0
        terminated = False
        truncated = self.step_count >= self.max_steps

        x0, y0, _, _ = self.camera.get_fov_rect()
        obs = self.get_observation()
        obs["frame"] = fov_frame

        try:
            from gui.core.renderer import Renderer as _Renderer
            obs["viewport"] = _Renderer.render_viewport(
                fov_frame, self.camera, telemetry=obs.get("local_terminal"))
        except Exception:
            obs["viewport"] = fov_frame

        info = {
            "fov_origin": (int(x0), int(y0)),
            "step_count": self.step_count,
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def close(self):
        pass

    @property
    def observation_space(self):
        try:
            h, w = int(self.camera_config.fov_height), int(self.camera_config.fov_width)
        except Exception:
            h, w = 480, 640
        return {
            "frame": (h, w, 3),
            "pan_tilt": (2,),
        }

    @property
    def action_space(self):
        try:
            clamp = float(self.controller_config.output_clamp)
        except Exception:
            clamp = 120.0
        return {"d_pan": (-clamp, clamp), "d_tilt": (-clamp, clamp), "shape": (2,)}
