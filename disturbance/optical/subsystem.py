"""Optical-owned disturbance orchestration."""

from __future__ import annotations

from disturbance.environment.atmospheric import apply_atmospheric_disturbance
from disturbance.optical.turbulence import apply_turbulence
from disturbance.core.state import TurbulenceState


class OpticalDisturbanceSubsystem:
    def __init__(self, config):
        self.config = config
        self.turbulence_state = TurbulenceState()

    def apply(self, frame, context):
        cfg = self.config
        out = apply_turbulence(
            frame, int(getattr(cfg, "turbulence", 0)),
            dt=context.dt, rng=context.rng, state=self.turbulence_state,
        )
        preset = str(getattr(cfg, "atmospheric_preset", "Clear"))
        contrast = float(getattr(cfg, "atmospheric_contrast", 0.0))
        brightness = float(getattr(cfg, "atmospheric_brightness", 0.0))
        if preset != "Clear" or contrast > 0 or brightness > 0:
            out = apply_atmospheric_disturbance(
                out, preset=preset, contrast_reduction=contrast,
                brightness_reduction=brightness, rng=context.rng,
            )
        return out


__all__ = ["OpticalDisturbanceSubsystem"]