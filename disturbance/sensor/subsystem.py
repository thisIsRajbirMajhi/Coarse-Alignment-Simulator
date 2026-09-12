"""Sensor-owned disturbance orchestration."""

from disturbance.sensor.image_noise import apply_image_noise
from disturbance.sensor.sensor_noise import apply_sensor_noise
from disturbance.core.state import SensorDefectState


class SensorDisturbanceSubsystem:
    def __init__(self, config):
        self.config = config
        self.defect_state = SensorDefectState()

    def apply(self, frame, context):
        cfg = self.config
        sensor_on = int(getattr(cfg, "noise", 0)) > 0
        out = frame
        if sensor_on:
            out = apply_sensor_noise(out, int(cfg.noise), rng=context.rng)
        if bool(getattr(cfg, "enable_salt_pepper", False) or getattr(cfg, "enable_gaussian", False) or getattr(cfg, "enable_poisson", False)):
            out = apply_image_noise(
                out,
                enable_salt_pepper=bool(getattr(cfg, "enable_salt_pepper", False)),
                enable_gaussian=bool(getattr(cfg, "enable_gaussian", False)) and not sensor_on,
                enable_poisson=bool(getattr(cfg, "enable_poisson", False)) and not sensor_on,
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


__all__ = ["SensorDisturbanceSubsystem"]