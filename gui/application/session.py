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
    world_frame: Any  # np.ndarray BGR, full scene with disturbances
    world_size: tuple[int, int]
    dt: float = 1 / 30

    @property
    def fov_frame(self) -> Any:
        return self.world_frame


class SimulationSession:
    """Owns Scene/Disturbance.

    GUI talks to this; widgets never touch sim objects directly.
    """

    def __init__(self, env_config=None, disturbance_config=None, seed: int = 42, **kwargs):
        from disturbance.core.config import DisturbanceConfig
        from environment.config import EnvironmentConfig

        self.seed = int(seed)
        self.env_config = (env_config or EnvironmentConfig()).validate()
        self.disturbance_config = (disturbance_config or DisturbanceConfig()).validate()
        self._built = False
        self._frame_id = 0
        self._last_dt = 1 / 30

    # -- construction -------------------------------------------------
    def build(self) -> None:
        from common.rng import get_rng, seed_global
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

        self.scene = Scene(config=cfg)
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
    def apply_camera_config(self, config=None) -> None:
        pass

    def apply_controller_config(self, config=None) -> None:
        pass

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

        pipe = self._disturbance_pipeline_for(dt_eff)

        world_frame = self.scene.get_frame()

        try:
            vig = float(getattr(self.env_config, "vignetting_pct", 0)) / 100.0
            if vig > 1e-3:
                from environment.vignetting import apply_vignetting
                world_frame = apply_vignetting(world_frame, vig)
        except Exception as e:
            log.debug("vignetting skipped: %s", e)

        world_frame = pipe.apply_frame(world_frame, advance=True)

        self._frame_id += 1

        return FrameSnapshot(
            frame_id=self._frame_id,
            world_frame=world_frame,
            world_size=(int(self.env_config.world_width), int(self.env_config.world_height)),
            dt=dt_eff,
        )

