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
    world_frame: Any  # np.ndarray BGR, full scene with beacons & disturbances
    world_size: tuple[int, int]
    fov_frame: Any = None
    camera_telemetry: dict | None = None
    pid_telemetry: dict | None = None
    dt: float = 1 / 30
    terminals: dict | None = None
    pan: float = 0.0
    tilt: float = 0.0
    fov_size: tuple[int, int] = (640, 480)


class SimulationSession:
    """Owns Scene/Disturbance/Remote-terminal/PTZ-Camera/PID-Controller scenario.

    GUI talks to this; widgets never touch sim objects directly.
    """

    def __init__(self, env_config=None, disturbance_config=None, scenario_config=None,
                 camera_config=None, pid_config=None, seed: int = 42, **kwargs):
        from camera.config import CameraConfig, PIDConfig
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig
        from remote_terminal import make_default_scenario

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        scenario_config = scenario_config or kwargs.get("remote_config")
        self.scenario_config = (scenario_config or make_default_scenario()).validate()
        self.camera_config = (camera_config or CameraConfig()).validate()
        self.pid_config = (pid_config or PIDConfig()).validate()
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    # -- construction -------------------------------------------------
    def build(self) -> None:
        from camera.pid_controller import PIDController
        from camera.ptz import PTZCamera
        from common.rng import get_rng, seed_global
        from environment.scene import Scene
        from remote_terminal import RemoteTerminalManager

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

        self.scene = Scene(config=cfg)
        scene_seed = int(cfg.seed) if cfg.seed is not None else self.seed
        self.remote = RemoteTerminalManager(
            self.scenario_config,
            bounds=(int(cfg.world_width), int(cfg.world_height)),
            seed=scene_seed,
        )
        self.camera = PTZCamera(
            config=self.camera_config,
            world_size=(int(cfg.world_width), int(cfg.world_height)),
            rng=self.rng,
        )
        self.controller = PIDController(config=self.pid_config)
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
        if hasattr(self, "camera") and self.camera is not None:
            self.camera.reset()
        if hasattr(self, "controller") and self.controller is not None:
            self.controller.reset()

    # -- config application (validated, explicit) ----------------------
    def apply_camera_config(self, config=None) -> None:
        if config is not None:
            self.camera_config = config.validate()
            if hasattr(self, "camera") and self.camera is not None:
                self.camera.apply_config(self.camera_config)

    def apply_controller_config(self, config=None) -> None:
        if config is not None:
            self.pid_config = config.validate()
            if hasattr(self, "controller") and self.controller is not None:
                self.controller.apply_config(self.pid_config)

    def apply_environment_config(self, config) -> None:
        new_cfg = config.validate()
        old = self.env_config
        old_w = int(getattr(old, "world_width", 0) or 0)
        old_h = int(getattr(old, "world_height", 0) or 0)
        new_w, new_h = int(new_cfg.world_width), int(new_cfg.world_height)
        self.env_config = new_cfg
        if self._built and new_w == old_w and new_h == old_h:
            # Fast path: same world size — regenerate sky in place.
            try:
                self.scene.regenerate_from_config(new_cfg)
            except Exception:
                self.build()
            return
        # World-size change requires full rebuild.
        self.build()

    def apply_disturbance_config(self, config) -> None:
        self.ensure_built()
        self.disturbance_config = config.validate()

    def apply_remote_config(self, config) -> None:
        self.ensure_built()
        self.scenario_config = config.validate()
        self.remote.apply_config(self.scenario_config)

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
        try:
            self.remote.update(dt_eff)
        except Exception as e:
            log.debug("remote terminal update skipped: %s", e)

        pipe = self._disturbance_pipeline_for(dt_eff)

        world_frame = self.scene.get_frame()

        try:
            world_frame = self.remote.render_spots(world_frame)
        except Exception as e:
            log.debug("remote beacon render skipped: %s", e)

        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                world_frame = apply_vignetting(world_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

        # -- Closed-loop PTZ Tracking --
        terms = self._safe_remote_telemetry()
        cmd_pan, cmd_tilt = 0.0, 0.0
        if terms and isinstance(terms, dict):
            term_list = terms.get("terminals", [])
            # Prioritize emitting terminal, otherwise pick first terminal
            active_target = None
            for t in term_list:
                if t.get("emitting"):
                    active_target = t
                    break
            if active_target is None and term_list:
                active_target = term_list[0]

            if active_target is not None:
                pos = active_target.get("position_m", (0.0, 0.0))
                tx, ty = float(pos[0]), float(pos[1])
                cx, cy = self.camera.get_fov_center_world()
                err_x_px = tx - cx
                err_y_px = ty - cy

                cmd_pan, cmd_tilt = self.controller.compute_from_pixels(
                    error_x_px=err_x_px,
                    error_y_px=err_y_px,
                    deg_per_px_h=self.camera.config.deg_per_px_h,
                    deg_per_px_v=self.camera.config.deg_per_px_v,
                    dt=dt_eff,
                )

        if self.controller.config.mode == "AUTO":
            self.camera.update(dt_eff, cmd_pan_vel=cmd_pan, cmd_tilt_vel=cmd_tilt)
        else:
            self.camera.update(dt_eff, cmd_pan_vel=0.0, cmd_tilt_vel=0.0)

        # Camera pose disturbances (jitter/vibration/platform/drift) shift
        # where the camera looks. Disturb the post-update pose so the FOV
        # matches the fresh gimbal position; disturb_camera_pose advances
        # pipeline time once, so the optical/sensor stages must NOT advance
        # again. True gimbal state stays clean (observation noise, not motion).
        from simulation.fov_pipeline import apply_jitter as _apply_pose
        from simulation.fov_pipeline import apply_post_noise as _apply_post
        cx, cy = self.camera.get_fov_center_world()
        try:
            dcx, dcy = _apply_pose(cx, cy, self.disturbance_config, dt_eff, self.rng, pipeline=pipe)
        except Exception as e:
            log.debug("camera pose disturbance skipped: %s", e)
            dcx, dcy = cx, cy
            world_frame = pipe.apply_frame(world_frame, advance=True)
        else:
            world_frame = _apply_post(
                world_frame, self.disturbance_config, dt_eff, self.rng, pipe, advance=False,
            )

        # Extract FOV viewport at the disturbed pose.
        fov_frame = self.camera.extract_fov_at(world_frame, dcx, dcy)

        self._frame_id += 1
        cam_st = self.camera.get_state()

        return FrameSnapshot(
            frame_id=self._frame_id,
            world_frame=world_frame,
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            fov_frame=fov_frame,
            camera_telemetry=self.camera.get_telemetry(),
            pid_telemetry=self.controller.get_telemetry(),
            dt=dt_eff,
            terminals=terms,
            pan=cam_st.pan_deg,
            tilt=cam_st.tilt_deg,
            fov_size=(self.camera.fov_width, self.camera.fov_height),
        )

    def _safe_remote_telemetry(self) -> dict | None:
        try:
            return self.remote.get_telemetry()
        except Exception as e:
            log.debug("remote telemetry skipped: %s", e)
            return None

