from disturbance.environment.atmospheric import apply_atmospheric_disturbance


def apply_haze(frame, intensity: float = 5.0, **kwargs):
    contrast = min(100.0, max(0.0, float(intensity) * 3.0))
    brightness = min(100.0, max(0.0, float(intensity) * 2.0))
    return apply_atmospheric_disturbance(
        frame, preset="User Defined", contrast_reduction=contrast,
        brightness_reduction=brightness, **kwargs,
    )


__all__ = ["apply_haze"]