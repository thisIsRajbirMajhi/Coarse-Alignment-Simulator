# gui/application/session.py - SimulationSession: Qt-free owner of simulation.
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class FrameSnapshot:
    """Immutable per-step output for presenters/views."""
    frame_id: int
    fov_frame: Any  # np.ndarray BGR, raw disturbed (no overlay)
    world_frame: Any | None  # full scene background (may be None; view caches)
    fov_origin: tuple[int, int]  # (x0, y0) scene coords of FOV
    pan: float
    tilt: float
    fov_size: tuple[int, int]
    world_size: tuple[int, int]
    pixel_scale_mrad: float = 0.035
    dt: float = 1 / 30
    terminals: dict | None = None


class SimulationSession:
    """Owns Scene/Camera/Controller/Disturbance.

    GUI talks to this; widgets never touch sim objects directly.
    """

    def __init__(self, env_config=None, camera_config=None, controller_config=None,
                 disturbance_config=None, scenario_config=None, seed: int = 42, **kwargs):
        from camera.config import CameraConfig
        from control.config import ControllerConfig
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig
        from remote_terminal import RemoteTerminalScenario, RemoteTerminalScenarioConfig

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))
        self.camera_config = (camera_config or CameraConfig()).validate(scene_bounds)
        self.controller_config = (controller_config or ControllerConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.scenario_config = (scenario_config or kwargs.get("terminal_config") or RemoteTerminalScenarioConfig()).validate()
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    # -- construction -------------------------------------------------
    def build(self) -> None:
        from camera.ptz_camera import PTZCamera
        from common.rng import get_rng, seed_global
        from control.controller import PIDController
        from environment.scene import Scene

        cfg = self.env_config.validate()
        seed_global(int(cfg.seed) if cfg.seed is not None else self.seed)
        self.rng = get_rng(None, int(cfg.seed) if cfg.seed is not None else self.seed)
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
            from disturbance.sensor.image_noise import clear_hot_pixel_cache
            clear_hot_pixel_cache()
        except Exception as e:
            log.debug("disturbance reset skipped: %s", e)

        scene_w, scene_h = int(cfg.world_width), int(cfg.world_height)
        cam_cfg = self.camera_config.validate((scene_w, scene_h))
        # clamp FOV inside world
        cam_cfg.fov_width = min(int(cam_cfg.fov_width), scene_w - 10)
        cam_cfg.fov_height = min(int(cam_cfg.fov_height), scene_h - 10)
        self.camera_config = cam_cfg

        self.scene = Scene(config=cfg)
        self.camera = PTZCamera(config=cam_cfg, scene_bounds=(scene_w, scene_h), rng=getattr(self, "rng", None))
        try:
            self.camera.set_vignetting(float(getattr(cfg, "vignetting_pct", 0)) / 100.0)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

        ctrl_cfg = self.controller_config.validate()
        self.controller = PIDController(config=ctrl_cfg)
        from remote_terminal import RemoteTerminalScenario
        self.terminal_scenario = RemoteTerminalScenario(self.scenario_config, bounds=(scene_w, scene_h), rng=self.rng)

        self._disturbance_pipeline = None
        self._built = True
        self._frame_id = 0

    def ensure_built(self) -> None:
        if not self._built:
            self.build()

    # -- lifecycle ----------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = int(seed)
            try:
                self.env_config.seed = int(seed)
            except Exception as e:
                log.debug("seed apply skipped: %s", e)
        self.build()

    # -- config application (validated, explicit) ----------------------
    def apply_camera_config(self, config) -> None:
        self.ensure_built()
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))
        self.camera_config = config.validate(scene_bounds)
        self.camera.apply_config(self.camera_config)

    def apply_controller_config(self, config) -> None:
        self.ensure_built()
        self.controller_config = config.validate()
        self.controller.apply_config(self.controller_config)

    def apply_environment_config(self, config) -> None:
        # World-size change requires rebuild (scene + camera bounds).
        self.env_config = config.validate()
        self.build()

    def apply_disturbance_config(self, config) -> None:
        self.ensure_built()
        self.disturbance_config = config.validate()

    def apply_terminal_config(self, config) -> None:
        self.ensure_built()
        self.scenario_config = config.validate()
        self.terminal_scenario.apply_config(self.scenario_config)

    # -- stepping ------------------------------------------------------
    def _disturbance_pipeline_for(self, dt: float):
        from disturbance.core import DisturbanceContext, DisturbancePipeline
        if self._disturbance_pipeline is None:
            self._disturbance_pipeline = DisturbancePipeline(
                DisturbanceContext(self.disturbance_config, rng=self.rng, dt=dt),
                bounds=(int(self.env_config.world_width), int(self.env_config.world_height)),
            )
        self._disturbance_pipeline.context.config = self.disturbance_config
        self._disturbance_pipeline.context.rng = self.rng
        self._disturbance_pipeline.context.dt = dt
        return self._disturbance_pipeline

    def step(self, dt: float) -> FrameSnapshot:
        self.ensure_built()
        dt_eff = float(np.clip(dt, 1e-4, 0.1))
        self._last_dt = dt_eff
        self.scene.update(dt_eff)
        self.camera.update(dt)
        if getattr(self, "terminal_scenario", None) is not None:
            try:
                self.terminal_scenario.update(dt_eff, camera=self.camera)
            except Exception as e:
                log.debug("terminal scenario update skipped: %s", e)

        pipe = self._disturbance_pipeline_for(dt_eff)
        pan_dist, tilt_dist = pipe.disturb_camera_pose(self.camera.pan, self.camera.tilt, dt_eff)
        try:
            self.camera.apply_disturbance(float(pan_dist), float(tilt_dist))
        except AttributeError:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)

        x0, y0, x1, y1 = self.camera.get_fov_rect()
        fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))

        if getattr(self, "terminal_scenario", None) is not None:
            try:
                fov_frame = self.terminal_scenario.render_fov_beacons(fov_frame, self.camera)
            except Exception as e:
                log.debug("fov beacon render skipped: %s", e)

        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

        fov_frame = pipe.apply_frame(fov_frame)

        self._frame_id += 1

        try:
            scale = float(getattr(self.camera.config, "pixel_scale_mrad", 0.035))
        except Exception:
            scale = 0.035

        return FrameSnapshot(
            frame_id=self._frame_id,
            fov_frame=fov_frame,
            world_frame=None,
            fov_origin=(int(x0), int(y0)),
            pan=float(self.camera.pan),
            tilt=float(self.camera.tilt),
            fov_size=(int(self.camera_config.fov_width), int(self.camera_config.fov_height)),
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            pixel_scale_mrad=scale,
            dt=dt_eff,
            terminals=self.terminal_scenario.get_telemetry() if getattr(self, "terminal_scenario", None) is not None else None,
        )
