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
    local_terminal: dict | None = None


class SimulationSession:
    """Owns Scene/LocalTerminal/Controller/Disturbance.

    GUI talks to this; widgets never touch sim objects directly.
    """

    def __init__(self, env_config=None, camera_config=None, local_terminal_config=None, controller_config=None,
                 disturbance_config=None, scenario_config=None, seed: int = 42, **kwargs):
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig
        from local_terminal import LocalTerminal, LocalTerminalConfig
        from remote_terminal import RemoteTerminalScenario, RemoteTerminalScenarioConfig

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))

        # Local Terminal configuration (replaces standalone camera system)
        lt_cfg = local_terminal_config or kwargs.get("local_terminal")
        if lt_cfg is None:
            if camera_config is not None:
                lt_cfg = LocalTerminalConfig.from_camera_config(camera_config)
            else:
                lt_cfg = LocalTerminalConfig()
        self.local_terminal_config = lt_cfg.validate(scene_bounds)
        self.camera_config = self.local_terminal_config

        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self.scenario_config = (scenario_config or kwargs.get("terminal_config") or RemoteTerminalScenarioConfig()).validate()
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    # -- construction -------------------------------------------------
    def build(self) -> None:
        from common.rng import get_rng, seed_global
        from environment.scene import Scene
        from local_terminal import LocalTerminal, LocalTerminalConfig

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
        lt_cfg = self.local_terminal_config.validate((scene_w, scene_h))
        self.local_terminal_config = lt_cfg
        self.camera_config = lt_cfg

        self.scene = Scene(config=cfg)
        self.local_terminal = LocalTerminal(config=lt_cfg, scene_bounds=(scene_w, scene_h), rng=getattr(self, "rng", None))
        self.camera = self.local_terminal
        try:
            self.local_terminal.set_vignetting(float(getattr(cfg, "vignetting_pct", 0)) / 100.0)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

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
    def apply_local_terminal_config(self, config) -> None:
        self.ensure_built()
        scene_bounds = (int(self.env_config.world_width), int(self.env_config.world_height))
        self.local_terminal_config = config.validate(scene_bounds)
        self.camera_config = self.local_terminal_config
        self.local_terminal.apply_config(self.local_terminal_config)

    def apply_camera_config(self, config) -> None:
        from local_terminal import LocalTerminalConfig
        if isinstance(config, LocalTerminalConfig):
            self.apply_local_terminal_config(config)
        else:
            lt_cfg = LocalTerminalConfig.from_camera_config(config)
            self.apply_local_terminal_config(lt_cfg)

    @property
    def controller_config(self):
        """Compatibility property forwarding to Local Terminal tracking config."""
        return self.local_terminal_config.tracking

    @controller_config.setter
    def controller_config(self, cfg) -> None:
        if cfg is not None:
            self.apply_controller_config(cfg)

    def apply_controller_config(self, config=None) -> None:
        """Compatibility adapter: updates Local Terminal tracking servo parameters."""
        if config is None:
            return
        if hasattr(config, "kp"):
            self.local_terminal_config.tracking.kp = float(config.kp)
        if hasattr(config, "ki"):
            self.local_terminal_config.tracking.ki = float(config.ki)
        if hasattr(config, "kd"):
            self.local_terminal_config.tracking.kd = float(config.kd)
        if hasattr(config, "dead_zone"):
            self.local_terminal_config.tracking.dead_zone = float(config.dead_zone)
        if hasattr(config, "output_clamp"):
            self.local_terminal_config.tracking.output_clamp = float(config.output_clamp)
        if self._built and self.local_terminal is not None:
            self.local_terminal.apply_config(self.local_terminal_config)

    def apply_environment_config(self, config) -> None:
        new_cfg = config.validate()
        old = self.env_config
        old_w = int(getattr(old, "world_width", 0) or 0)
        old_h = int(getattr(old, "world_height", 0) or 0)
        new_w, new_h = int(new_cfg.world_width), int(new_cfg.world_height)
        # Vignetting-only fast path: capture-stage effect, no sky rebuild.
        # Makes the vignette slider truly live (Design.md §15 hybrid).
        if (self._built and new_w == old_w and new_h == old_h
                and int(getattr(old, "vignetting_pct", 0)) != int(getattr(new_cfg, "vignetting_pct", 0))
                and all(int(getattr(old, k, 0)) == int(getattr(new_cfg, k, 0)) for k in
                        ("world_width", "world_height", "bg_top", "bg_bottom",
                         "haze_pct", "star_count"))
                and float(getattr(old, "star_brightness", 1.0)) == float(getattr(new_cfg, "star_brightness", 1.0))
                and str(getattr(old, "seed", "")) == str(getattr(new_cfg, "seed", ""))):
            self.env_config = new_cfg
            try:
                self.local_terminal.set_vignetting(float(getattr(new_cfg, "vignetting_pct", 0)) / 100.0)
            except (AttributeError, TypeError, ValueError):
                pass
            return
        self.env_config = new_cfg
        if self._built and new_w == old_w and new_h == old_h:
            # Fast path: same world size — regenerate sky in place, keep
            # terminals/queues alive so the 30 ms loop never freezes.
            try:
                self.scene.regenerate_from_config(new_cfg)
            except Exception:
                self.build()
            try:
                self.local_terminal.set_vignetting(float(getattr(new_cfg, "vignetting_pct", 0)) / 100.0)
            except Exception:
                pass
            return
        # World-size change requires full rebuild (scene + camera bounds).
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
        if getattr(self, "terminal_scenario", None) is not None:
            try:
                self.terminal_scenario.update(dt_eff, camera=self.camera)
            except Exception as e:
                log.debug("terminal scenario update skipped: %s", e)

        try:
            self.local_terminal.update(
                dt_eff,
                fov_frame=getattr(self, "_last_fov_frame", None),
                fov_capture_pose=getattr(self, "_last_capture_pose", None),
            )
        except Exception:
            self.camera.update(dt_eff)

        pipe = self._disturbance_pipeline_for(dt_eff)
        true_pan, true_tilt = float(self.camera.pan), float(self.camera.tilt)
        pan_dist, tilt_dist = pipe.disturb_camera_pose(true_pan, true_tilt, dt_eff)
        try:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)
        except AttributeError:
            self.camera.set_position(float(pan_dist), float(tilt_dist), clear_queue=False)

        x0, y0, x1, y1 = self.camera.get_fov_rect()
        fov_frame = self.scene.get_region(int(x0), int(y0), int(x1), int(y1))

        if getattr(self, "terminal_scenario", None) is not None:
            try:
                fov_frame = self.terminal_scenario.render_fov_beacons(
                    fov_frame, self.camera, pipeline=pipe, rng=self.rng, dt=dt_eff,
                )
            except Exception as e:
                log.debug("fov beacon render skipped: %s", e)

        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                fov_frame = apply_vignetting(fov_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

        # disturb_camera_pose() already advanced time; don't advance again.
        fov_frame = pipe.apply_frame(fov_frame, advance=False)
        # Restore ground truth; snapshot pan/tilt stay truthful.
        try:
            self.camera.set_position(float(true_pan), float(true_tilt), clear_queue=False)
        except Exception:
            pass
        try:
            self._last_fov_frame = fov_frame
            self._last_capture_pose = (float(pan_dist), float(tilt_dist))
        except Exception:
            pass

        self._frame_id += 1

        try:
            scale = float(getattr(self.camera.config, "pixel_scale_mrad", 0.109083))
        except Exception:
            scale = 0.109083

        return FrameSnapshot(
            frame_id=self._frame_id,
            fov_frame=fov_frame,
            world_frame=None,
            fov_origin=(int(x0), int(y0)),
            pan=float(true_pan),
            tilt=float(true_tilt),
            fov_size=(int(self.camera_config.fov_width), int(self.camera_config.fov_height)),
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            pixel_scale_mrad=scale,
            dt=dt_eff,
            terminals=self.terminal_scenario.get_telemetry() if getattr(self, "terminal_scenario", None) is not None else None,
            local_terminal=self.local_terminal.get_telemetry() if getattr(self, "local_terminal", None) is not None else None,
        )
