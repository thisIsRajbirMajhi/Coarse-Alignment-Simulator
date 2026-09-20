# simulation/headless.py - Headless FSOC simulation (no Qt, deterministic, gym-compatible)
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from camera.config import CameraConfig, PIDConfig
from camera.pid_controller import PIDController
from camera.ptz import PTZCamera
from common.rng import get_rng, seed_global
from disturbance import disturbances as dist
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline
from environment.config import EnvironmentConfig
from environment.scene import Scene
from remote_terminal import RemoteTerminalManager, RemoteScenarioConfig, make_default_scenario


@dataclass
class HeadlessConfig:
    """Aggregated config for HeadlessSimulation - all validated, single source."""
    seed: int = 42
    env: EnvironmentConfig | None = None
    disturbance: DisturbanceConfig | None = None
    scenario: RemoteScenarioConfig | None = None
    camera: CameraConfig | None = None
    pid: PIDConfig | None = None
    max_steps: int = 2000
    dt: float = 1 / 30
    sim_speed: float = 1.0


class HeadlessSimulation:
    """
    Headless FSOC simulator — deterministic, no Qt.

    Pipeline:
      scene.update → remote terminals → disturbances → camera FOV capture → PID tracking
    """

    def __init__(
        self,
        seed: int = 42,
        env_config: EnvironmentConfig | None = None,
        disturbance_config: DisturbanceConfig | None = None,
        scenario_config: RemoteScenarioConfig | None = None,
        camera_config: CameraConfig | None = None,
        pid_config: PIDConfig | None = None,
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

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        scenario_config = scenario_config or kwargs.get("remote_config")
        self.scenario_config = (scenario_config or make_default_scenario()).validate()
        self.camera_config = (camera_config or CameraConfig()).validate()
        self.pid_config = (pid_config or PIDConfig()).validate()

        self._last_frame: np.ndarray | None = None
        self._last_fov: np.ndarray | None = None

        self._build_simulation()
        self._disturbance_pipeline = DisturbancePipeline(
            DisturbanceContext(self.disturbance_config, rng=self.rng, dt=self.dt),
            bounds=self._scene_size,
        )

    def _build_simulation(self):
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)

        scene_seed = int(cfg.seed) if cfg.seed is not None else self.seed
        self.remote = RemoteTerminalManager(
            self.scenario_config, bounds=self._scene_size, seed=scene_seed,
        )
        self.camera = PTZCamera(
            config=self.camera_config,
            world_size=self._scene_size,
            rng=self.rng,
        )
        self.controller = PIDController(config=self.pid_config)
        self._last_frame = None
        self._last_fov = None

    def _capture_frame(self, dt_eff: float = 1 / 30, advance: bool = True) -> np.ndarray:
        dc = self.disturbance_config
        self._disturbance_pipeline.context.config = dc
        self._disturbance_pipeline.context.rng = self.rng
        self._disturbance_pipeline.context.dt = dt_eff

        frame = self.scene.get_frame()

        try:
            frame = self.remote.render_spots(frame)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass

        vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                frame = apply_vignetting(frame, vig)
            except (AttributeError, TypeError, ValueError):
                pass

        try:
            from simulation.fov_pipeline import apply_post_noise as _post
            frame = _post(
                frame, dc, dt_eff, self.rng, self._disturbance_pipeline,
                advance=advance,
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            frame = dist.apply_turbulence(frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=self.rng)

        return frame

    # Backward compatibility alias
    _capture_fov_frame = _capture_frame

    def reset(self, seed: int | None = None) -> dict:
        if seed is not None:
            self.seed = int(seed)
            self.rng = get_rng(None, self.seed)
            seed_global(self.seed)
            self.env_config.seed = self.seed
            self.env_config.validate()
        self.step_count = 0
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
        except Exception:
            pass
        self._build_simulation()
        self._disturbance_pipeline.reset()
        self._disturbance_pipeline.context.config = self.disturbance_config
        self._disturbance_pipeline.context.rng = self.rng
        self._last_frame = self._capture_frame(self.dt)
        obs = self.get_observation()
        obs["frame"] = self._last_frame
        return obs

    def get_observation(self) -> dict:
        obs = {
            "world_size": self._scene_size,
            "step_count": self.step_count,
        }
        try:
            obs["terminals"] = self.remote.get_telemetry()
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass
        if self._last_frame is not None:
            obs["frame"] = self._last_frame
        if self._last_fov is not None:
            obs["fov_frame"] = self._last_fov
        if hasattr(self, "camera"):
            obs["camera"] = self.camera.get_telemetry()
        if hasattr(self, "controller"):
            obs["pid"] = self.controller.get_telemetry()
        return obs

    def step(self, action: np.ndarray | tuple | None = None, dt: float | None = None) -> tuple[dict, float, bool, bool, dict]:
        dt = float(dt if dt is not None else self.dt)
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))

        try:
            self.scene.update(dt_eff)
        except Exception:
            pass
        try:
            self.remote.update(dt_eff)
        except Exception:
            pass

        # -- Camera tracking & FOV extraction --
        cmd_pan, cmd_tilt = 0.0, 0.0
        if action is not None and len(action) >= 2:
            cmd_pan, cmd_tilt = float(action[0]), float(action[1])
        elif self.controller.config.mode == "AUTO":
            try:
                tel = self.remote.get_telemetry()
                term_list = tel.get("terminals", []) if isinstance(tel, dict) else []
                active_target = next((t for t in term_list if t.get("emitting")), term_list[0] if term_list else None)
                if active_target is not None:
                    pos = active_target.get("position_m", (0.0, 0.0))
                    cx, cy = self.camera.get_fov_center_world()
                    cmd_pan, cmd_tilt = self.controller.compute_from_pixels(
                        error_x_px=float(pos[0]) - cx,
                        error_y_px=float(pos[1]) - cy,
                        deg_per_px_h=self.camera.config.deg_per_px_h,
                        deg_per_px_v=self.camera.config.deg_per_px_v,
                        dt=dt_eff,
                    )
            except Exception:
                pass

        self.camera.update(dt_eff, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)

        # Camera pose disturbances (jitter/vibration/platform/drift) shift
        # where the camera looks. Disturb the post-update pose so the FOV
        # matches the fresh gimbal position; this advances pipeline time
        # once, so the optical/sensor stages below must NOT advance again.
        # True gimbal state stays clean (observation noise, not motion).
        from simulation.fov_pipeline import apply_jitter as _apply_pose
        pipe = self._disturbance_pipeline
        pipe.context.config = self.disturbance_config
        pipe.context.rng = self.rng
        cx, cy = self.camera.get_fov_center_world()
        dcx, dcy = _apply_pose(cx, cy, self.disturbance_config, dt_eff, self.rng, pipeline=pipe)

        frame = self._capture_frame(dt_eff, advance=False)
        self._last_frame = frame

        # Render at the disturbed pose.
        fov_frame = self.camera.extract_fov_at(frame, dcx, dcy)
        self._last_fov = fov_frame

        self.step_count += 1
        reward = 0.0
        terminated = False
        truncated = self.step_count >= self.max_steps

        obs = self.get_observation()
        obs["frame"] = frame
        obs["fov_frame"] = fov_frame

        info = {
            "step_count": self.step_count,
            "camera": self.camera.get_telemetry(),
            "pid": self.controller.get_telemetry(),
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def close(self):
        pass

    @property
    def observation_space(self):
        w, h = self._scene_size
        return {
            "frame": (h, w, 3),
        }

    @property
    def action_space(self):
        return {"shape": (0,)}
