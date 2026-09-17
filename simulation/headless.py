# simulation/headless.py - Headless FSOC simulation (no Qt, deterministic, gym-compatible)
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from camera.config import CameraConfig
from camera.ptz_camera import PTZCamera
from common.rng import get_rng, seed_global
from control.config import ControllerConfig
from control.controller import PIDController
from disturbance import disturbances as dist
from disturbance.core.config import DisturbanceConfig
from disturbance.core import DisturbanceContext, DisturbancePipeline
from environment.config import EnvironmentConfig
from environment.scene import Scene


@dataclass
class HeadlessConfig:
    """Aggregated config for HeadlessSimulation — all validated, single source."""
    seed: int = 42
    env: EnvironmentConfig | None = None
    camera: CameraConfig | None = None
    controller: ControllerConfig | None = None
    disturbance: DisturbanceConfig | None = None
    max_steps: int = 2000
    dt: float = 1 / 30
    sim_speed: float = 1.0


class HeadlessSimulation:
    """
    Headless FSOC simulator — deterministic, no Qt.

    Pipeline:
      scene.update → camera.update → disturbances → capture FOV → camera.move (direct action)
    """

    def __init__(
        self,
        seed: int = 42,
        env_config: EnvironmentConfig | None = None,
        camera_config: CameraConfig | None = None,
        controller_config: ControllerConfig | None = None,
        disturbance_config: DisturbanceConfig | None = None,
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

        if camera_config is None:
            fov = (640, 480)
            self.camera_config = CameraConfig(
                fov_width=fov[0], fov_height=fov[1],
                viewport_width=2000, viewport_height=2000,
                god_width=2000, god_height=2000,
            ).validate(self._scene_size)
        else:
            self.camera_config = camera_config.validate(self._scene_size)

        self.controller_config = (controller_config or ControllerConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()

        self._camera_drift_state: dict = {}
        self._platform_motion_state: dict = {}
        self._jitter_state: dict = {}
        self._last_frame: np.ndarray | None = None

        self._build_simulation()
        self._disturbance_pipeline = DisturbancePipeline(
            DisturbanceContext(self.disturbance_config, rng=self.rng, dt=self.dt),
            bounds=self._scene_size,
        )

    def _build_simulation(self):
        cfg = self.env_config.validate()
        self._scene_size = (int(cfg.world_width), int(cfg.world_height))
        self.scene = Scene(config=cfg)

        sw, sh = self._scene_size
        cam_cfg = self.camera_config.validate((sw, sh))
        fov_w = min(int(cam_cfg.fov_width), sw - 10)
        fov_h = min(int(cam_cfg.fov_height), sh - 10)
        cam_cfg.fov_width = max(20, fov_w)
        cam_cfg.fov_height = max(20, fov_h)
        self.camera_config = cam_cfg
        self._fov_size = (int(cam_cfg.fov_width), int(cam_cfg.fov_height))
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(sw, sh), rng=self.rng)
        try:
            vig = float(cfg.vignetting_pct) / 100.0
            self.camera.set_vignetting(vig)
        except Exception:
            pass

        ctrl_cfg = self.controller_config.validate()
        self.controller = PIDController(config=ctrl_cfg)

        self._camera_drift_state.clear()
        self._platform_motion_state.clear()
        self._jitter_state.clear()
        self._last_frame = None

    def _capture_fov_frame(self, dt_eff: float = 1 / 30) -> np.ndarray:
        dc = self.disturbance_config.validate() if hasattr(self.disturbance_config, "validate") else self.disturbance_config
        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            self.camera.set_vignetting(vig)
        except Exception:
            vig = 0.0

        self._disturbance_pipeline.context.config = dc
        self._disturbance_pipeline.context.rng = self.rng
        pan_dist, tilt_dist = self._disturbance_pipeline.disturb_camera_pose(
            self.camera.pan, self.camera.tilt, dt_eff,
        )

        try:
            self.camera.apply_disturbance(float(pan_dist), float(tilt_dist))
        except AttributeError:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)

        x0, y0, x1, y1 = self.camera.get_fov_rect()
        fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))

        if vig > 1e-3:
            try:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
            except Exception:
                pass

        try:
            from simulation.fov_pipeline import apply_post_noise as _post
            fov_frame = _post(fov_frame, dc, dt_eff, self.rng, self._disturbance_pipeline)
        except Exception:
            fov_frame = dist.apply_turbulence(fov_frame, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=self.rng)

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
        obs = {
            "pan": float(self.camera.pan),
            "tilt": float(self.camera.tilt),
            "fov_rect": self.camera.get_fov_rect(),
            "world_size": self._scene_size,
            "fov_size": self._fov_size,
            "step_count": self.step_count,
        }
        if self._last_frame is not None:
            obs["frame"] = self._last_frame
        return obs

    def step(self, action: np.ndarray | tuple | None = None, dt: float | None = None) -> tuple[dict, float, bool, bool, dict]:
        dt = float(dt if dt is not None else self.dt)
        dt_eff = float(np.clip(dt * self.sim_speed, 1e-4, 0.1))
        dt_wall = float(np.clip(dt, 0.005, 0.1))

        try:
            self.scene.update(dt_eff)
        except Exception:
            pass
        try:
            self.camera.update(dt_wall)
        except Exception:
            pass

        # Capture disturbed frame
        fov_frame = self._capture_fov_frame(dt_eff)
        self._last_frame = fov_frame

        # Direct action (manual override / gym action)
        if action is not None:
            try:
                arr = np.asarray(action, dtype=float).reshape(-1)
                d_pan = float(arr[0]) if len(arr) > 0 else 0.0
                d_tilt = float(arr[1]) if len(arr) > 1 else 0.0
                try:
                    self.camera.move(d_pan, d_tilt, dt_eff)
                except Exception:
                    self.camera.move(d_pan, d_tilt)
            except Exception:
                pass

        self.step_count += 1
        reward = 0.0
        terminated = False
        truncated = self.step_count >= self.max_steps

        x0, y0, _, _ = self.camera.get_fov_rect()
        obs = self.get_observation()
        obs["frame"] = fov_frame

        try:
            from gui.core.renderer import Renderer as _Renderer
            obs["viewport"] = _Renderer.render_viewport(fov_frame, self.camera)
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
