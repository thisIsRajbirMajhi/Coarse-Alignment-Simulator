"""Canonical ordering for camera and image disturbances."""

from __future__ import annotations

import numpy as np

from disturbance.camera.subsystem import CameraDisturbanceSubsystem
from disturbance.core.context import DisturbanceContext
from disturbance.optical.subsystem import OpticalDisturbanceSubsystem
from disturbance.sensor.subsystem import SensorDisturbanceSubsystem


class DisturbancePipeline:
    """Apply the configured post-capture disturbance chain for one run."""

    def __init__(self, context: DisturbanceContext | None = None, bounds=None):
        self.context = context or DisturbanceContext()
        config = self.context.config
        self.camera = CameraDisturbanceSubsystem(config, bounds=bounds)
        self.optical = OpticalDisturbanceSubsystem(config)
        self.sensor = SensorDisturbanceSubsystem(config)

    def _sync_config(self) -> None:
        self.camera.config = self.context.config
        self.optical.config = self.context.config
        self.sensor.config = self.context.config

    def apply_camera(self, pan: float, tilt: float) -> tuple[float, float]:
        return self.camera.apply(pan, tilt, self.context)

    def disturb_camera_pose(self, pan: float, tilt: float, dt: float | None = None) -> tuple[float, float]:
        self._sync_config()
        if not getattr(self.context.config.global_, "enabled", True):
            return pan, tilt
        self.context.advance(dt)
        return self.camera.apply(pan, tilt, self.context)

    def apply_optical(self, frame: np.ndarray, dt: float | None = None) -> np.ndarray:
        self._sync_config()
        if dt is not None:
            self.context.dt = float(dt)
        return self.optical.apply(frame, self.context)

    def apply_sensor(self, frame: np.ndarray, dt: float | None = None) -> np.ndarray:
        self._sync_config()
        if dt is not None:
            self.context.dt = float(dt)
        return self.sensor.apply(frame, self.context)

    def apply_frame(self, frame: np.ndarray) -> np.ndarray:
        self._sync_config()
        if not getattr(self.context.config.global_, "enabled", True):
            return frame
        self.context.advance()
        return self.sensor.apply(self.optical.apply(frame, self.context), self.context)

    def reset(self) -> None:
        self.context.reset()
        self.camera.reset()
        self.sensor.reset()
        self.optical.turbulence_state.clear()


__all__ = ["DisturbancePipeline"]