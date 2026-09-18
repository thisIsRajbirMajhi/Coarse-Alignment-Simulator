"""Canonical disturbance ordering per DisturbanceModel.txt §13.

Remote Terminal → Ideal Beam → Propagation Channel → Received Signal →
Local Terminal/Camera (+ Platform Motion) → Image Formation →
Sensor Effects → Observed Frame → Detection/Tracking.
"""

from __future__ import annotations

import numpy as np

from disturbance.camera.subsystem import CameraDisturbanceSubsystem
from disturbance.core.context import DisturbanceContext
from disturbance.optical.subsystem import OpticalDisturbanceSubsystem
from disturbance.sensor.subsystem import SensorDisturbanceSubsystem


def _global_enabled(config) -> bool:
    try:
        if hasattr(config, "global_enabled"):
            return bool(config.global_enabled)
        return bool(getattr(config.global_, "enabled", True))
    except Exception:
        return True


class DisturbancePipeline:
    """Apply the configured disturbance chain for one run."""

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

    # ---- Beam-state stage: Remote Terminal → Propagation Channel ----
    def propagate_beam(self, beam, distance_m: float | None = None, dt: float | None = None):
        """Ideal OpticalBeamState → ReceivedOpticalState (deterministic)."""
        self._sync_config()
        if dt is not None:
            self.context.dt = float(dt)
        if not _global_enabled(self.context.config):
            from disturbance.optical.channel import ReceivedOpticalState
            return ReceivedOpticalState(
                intensity=float(getattr(beam, "emittedIntensity", 1.0)),
                position=tuple(getattr(beam, "position", (0.0, 0.0))),
                direction=tuple(getattr(beam, "direction", (0.0, 0.0))),
                spotSize=float(getattr(beam, "spotSize", 9.0)),
            )
        return self.optical.propagate_beam(beam, self.context, distance_m=distance_m)

    def channel_state(self) -> dict:
        """Centralized ChannelState snapshot for telemetry/logging (§3/§17)."""
        self._sync_config()
        try:
            return self.optical.channel_state_dict()
        except Exception:
            return {}

    def telemetry(self) -> dict:
        """Disturbance telemetry/logging (§17 tree)."""
        self._sync_config()
        cfg = self.context.config
        return {
            "globalEnabled": _global_enabled(cfg),
            "channel": self.channel_state(),
            "camera": {
                "jitter": float(getattr(cfg, "camera_jitter", 0.0)),
                "vibration": int(getattr(cfg, "vibration", 0)),
            },
            "platform": {
                "enabled": bool(getattr(cfg, "platform_enabled", True)),
                "profile": str(getattr(cfg, "platform_profile", "Linear")),
                "speed": float(getattr(cfg, "platform_speed", 0.0)),
            },
            "sensor": {
                "gaussian": bool(getattr(cfg, "enable_gaussian", False)),
                "poisson": bool(getattr(cfg, "enable_poisson", False)),
                "saltPepper": bool(getattr(cfg, "enable_salt_pepper", False)),
            },
            "sim_time": float(getattr(self.context, "sim_time", 0.0)),
            "step": int(getattr(self.context, "step", 0)),
        }

    # ---- Camera geometry stage (Local Terminal + Platform Motion) ----
    def apply_camera(self, pan: float, tilt: float) -> tuple[float, float]:
        return self.camera.apply(pan, tilt, self.context)

    def disturb_camera_pose(self, pan: float, tilt: float, dt: float | None = None) -> tuple[float, float]:
        self._sync_config()
        if not _global_enabled(self.context.config):
            return pan, tilt
        self.context.advance(dt)
        return self.camera.apply(pan, tilt, self.context)

    # ---- Image stages ----
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

    def apply_frame(self, frame: np.ndarray, advance: bool = True) -> np.ndarray:
        self._sync_config()
        if not _global_enabled(self.context.config):
            return frame
        if advance:
            self.context.advance()
        return self.sensor.apply(self.optical.apply(frame, self.context), self.context)

    def reset(self) -> None:
        self.context.reset()
        self.camera.reset()
        self.sensor.reset()
        try:
            self.optical.reset()
        except Exception:
            try:
                self.optical.turbulence_state.clear()
            except Exception:
                pass
        try:
            from disturbance.core.state import reset_disturbance_state
            reset_disturbance_state()
        except Exception:
            pass


__all__ = ["DisturbancePipeline"]
