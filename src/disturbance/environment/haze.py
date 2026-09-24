"""Deprecated alias — use disturbance.environment.atmospheric directly.

Strict-compat shim for legacy ``apply_haze`` callers. Beam-state haze loss
lives in disturbance.optical.channel (authoritative); this remains the
image-space residual rendering.
"""
from src.disturbance.environment.atmospheric import apply_atmospheric_disturbance


def apply_haze(frame, intensity: float = 5.0, **kwargs):
    contrast = min(100.0, max(0.0, float(intensity) * 3.0))
    brightness = min(100.0, max(0.0, float(intensity) * 2.0))
    return apply_atmospheric_disturbance(
        frame, preset="User Defined", contrast_reduction=contrast,
        brightness_reduction=brightness, **kwargs,
    )


__all__ = ["apply_haze"]