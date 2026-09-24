"""Camera-owned disturbance orchestration."""

from __future__ import annotations

import numpy as np

from src.disturbance.camera.jitter import apply_camera_jitter_with_state
from src.disturbance.camera.drift import apply_camera_motion_with_state
from src.disturbance.core.state import CameraDriftState, JitterState, PlatformMotionState, VibrationState
from src.disturbance.camera.platform import apply_platform_motion
from src.disturbance.camera.vibration import apply_platform_vibration


class CameraDisturbanceSubsystem:
    """Apply camera disturbances in the legacy-compatible physical order."""

    def __init__(self, config, bounds: tuple[int, int] | None = None):
        self.config = config
        self.bounds = bounds
        self.platform_state = PlatformMotionState()
        self.vibration_state = VibrationState()
        self.jitter_state = JitterState()
        self.drift_state = CameraDriftState()

    def apply(self, pan: float, tilt: float, context) -> tuple[float, float]:
        cfg = self.config
        # Platform Motion is its own subsystem (§12 — geometry-level, not
        # channel medium). Honour its enable flag separately.
        platform_on = bool(getattr(cfg, "platform_enabled", True))
        # This order matches the established simulation path: vibration,
        # platform trajectory, jitter, then slow camera drift.
        vib = getattr(cfg, "vibration", 0)
        try:
            vib_f = float(vib)
        except (TypeError, ValueError):
            vib_f = 0.0
        if vib_f > 1e-9:
            pan, tilt = apply_platform_vibration(
                pan, tilt, vib_f,
                dt=context.dt, rng=context.rng, state=self.vibration_state,
            )
        speed = float(getattr(cfg, "platform_speed", 0.0))
        if platform_on and speed > 1e-9:
            pan, tilt = apply_platform_motion(
                pan, tilt, profile=str(getattr(cfg, "platform_profile", "Linear")),
                speed_px_per_frame=speed, dt=context.dt,
                state=self.platform_state, bounds=self.bounds, rng=context.rng,
            )
        jitter = float(getattr(cfg, "camera_jitter", 0.0))
        jitter_on = bool(getattr(cfg, "camera_jitter_enabled", getattr(cfg, "jitter_enabled", True)))
        if jitter_on and jitter > 1e-9:
            pan, tilt = apply_camera_jitter_with_state(
                pan, tilt, jitter, state=self.jitter_state,
                dt=context.dt, rng=context.rng,
            )
        # Preserve float camera_motion (was int() truncation which quantized
        # 0.5→0 and 2.7→2; drift kernel accepts float intensity).
        try:
            cm_f = float(getattr(cfg, "camera_motion", 0))
        except (TypeError, ValueError):
            cm_f = 0.0
        return apply_camera_motion_with_state(
            pan, tilt, cm_f,
            self.drift_state, dt=context.dt, rng=context.rng,
        )

    def reset(self) -> None:
        self.platform_state.clear()
        self.vibration_state.clear()
        self.jitter_state.clear()
        self.drift_state.clear()


__all__ = ["CameraDisturbanceSubsystem"]