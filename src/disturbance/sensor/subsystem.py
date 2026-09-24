"""Sensor-owned disturbance orchestration."""

from src.disturbance.sensor.image_noise import apply_image_noise
from src.disturbance.sensor.sensor_noise import apply_sensor_noise
from src.disturbance.core.state import SensorDefectState


class SensorDisturbanceSubsystem:
    def __init__(self, config):
        self.config = config
        self.defect_state = SensorDefectState()
        self._cached_version: int | None = None
        self._modern_on: bool = False
        self._legacy_noise: int = 0

    def _sync_flags(self) -> None:
        """Cache enable flags per config version (~12 getattr/frame saved)."""
        cfg = self.config
        try:
            ver = hash((
                bool(getattr(cfg, "enable_salt_pepper", False)),
                bool(getattr(cfg, "enable_gaussian", False)),
                bool(getattr(cfg, "enable_poisson", False)),
                int(getattr(cfg, "noise", 0)),
            ))
        except (AttributeError, TypeError, ValueError):
            ver = None
        if ver is not None and ver == self._cached_version:
            return
        self._modern_on = bool(getattr(cfg, "enable_salt_pepper", False) or getattr(cfg, "enable_gaussian", False) or getattr(cfg, "enable_poisson", False))
        try:
            self._legacy_noise = int(getattr(cfg, "noise", 0))
        except (TypeError, ValueError):
            self._legacy_noise = 0
        self._cached_version = ver

    def apply(self, frame, context):
        cfg = self.config
        self._sync_flags()
        modern_on = self._modern_on
        out = frame
        # Exclusive paths: modern stack wins when enabled, otherwise legacy.
        # Applying both double-counts photons (salt twice) and runs two
        # independent hot-pixel models on the same frame.
        if modern_on:
            pass
        elif self._legacy_noise > 0:
            out = apply_sensor_noise(out, int(self._legacy_noise), rng=context.rng)
        if modern_on:
            out = apply_image_noise(
                out,
                enable_salt_pepper=bool(getattr(cfg, "enable_salt_pepper", False)),
                enable_gaussian=bool(getattr(cfg, "enable_gaussian", False)),
                enable_poisson=bool(getattr(cfg, "enable_poisson", False)),
                salt_pepper_density=float(getattr(cfg, "salt_pepper_density", 0.10)),
                salt_pepper_ratio=float(getattr(cfg, "salt_pepper_ratio", 0.50)),
                gaussian_sigma=float(getattr(cfg, "gaussian_sigma", 8.0)),
                gaussian_sigma_max=float(getattr(cfg, "gaussian_sigma_max", 20.0)),
                poisson_scale=float(getattr(cfg, "poisson_scale", 1.0)),
                poisson_peak=float(getattr(cfg, "poisson_peak", 100.0)),
                rng=context.rng,
                defect_state=self.defect_state.hot_pixels,
            )
        return out

    def reset(self) -> None:
        self.defect_state.clear()
        self._cached_version = None
        try:
            from src.disturbance.sensor.image_noise import clear_hot_pixel_cache
            clear_hot_pixel_cache()
        except (AttributeError, TypeError, ValueError, ImportError):
            pass


__all__ = ["SensorDisturbanceSubsystem"]