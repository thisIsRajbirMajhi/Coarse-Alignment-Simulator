# simulation/fov_pipeline — shared post-capture image chain (single source).
#
# Extracted from duplicated logic in simulation/headless.py and
# gui/mixins/tick_mixin.py. Both callers must use these helpers so noise
# ordering / double-count fixes apply everywhere.
from __future__ import annotations
import numpy as np
from disturbance import disturbances as dist


def apply_jitter(pan: float, tilt: float, dc, dt_eff: float, rng, jitter_state: dict | None):
    amp = float(getattr(dc, "camera_jitter", 0.0))
    if amp <= 1e-9:
        return pan, tilt
    if jitter_state is None:
        jitter_state = {}
    try:
        return dist.apply_camera_jitter_with_state(pan, tilt, amp, state=jitter_state, dt=dt_eff, rng=rng)
    except Exception:
        return dist.apply_camera_jitter(pan, tilt, jitter_px=amp, rng=rng)


def apply_post_noise(frame: np.ndarray, dc, dt_eff: float, rng) -> np.ndarray:
    """Turbulence -> atmospheric -> sensor -> image(S&P only if sensor off)."""
    out = frame
    try:
        out = dist.apply_turbulence(out, int(getattr(dc, "turbulence", 0)), dt=dt_eff, rng=rng)
    except Exception:
        pass
    try:
        preset = str(getattr(dc, "atmospheric_preset", "Clear"))
        contrast = float(getattr(dc, "atmospheric_contrast", 0.0))
        brightness = float(getattr(dc, "atmospheric_brightness", 0.0))
        if preset != "Clear" or contrast > 1e-9 or brightness > 1e-9:
            out = dist.apply_atmospheric_disturbance(out, preset=preset, contrast_reduction=contrast, brightness_reduction=brightness, rng=rng)
    except Exception:
        pass
    sensor_on = int(getattr(dc, "noise", 0)) > 0
    try:
        if sensor_on:
            out = dist.apply_sensor_noise(out, int(getattr(dc, "noise")), rng=rng)
    except Exception:
        pass
    try:
        if bool(getattr(dc, "enable_salt_pepper", False) or getattr(dc, "enable_gaussian", False) or getattr(dc, "enable_poisson", False)):
            img_p = bool(getattr(dc, "enable_poisson", False)) and not sensor_on
            img_g = bool(getattr(dc, "enable_gaussian", False)) and not sensor_on
            if bool(getattr(dc, "enable_salt_pepper", False)) or img_g or img_p:
                out = dist.apply_image_noise(
                    out,
                    enable_salt_pepper=bool(getattr(dc, "enable_salt_pepper", False)),
                    enable_gaussian=img_g, enable_poisson=img_p,
                    salt_pepper_density=float(getattr(dc, "salt_pepper_density", 0.10)),
                    salt_pepper_ratio=float(getattr(dc, "salt_pepper_ratio", 0.50)),
                    gaussian_sigma=float(getattr(dc, "gaussian_sigma", 8.0)),
                    gaussian_sigma_max=float(getattr(dc, "gaussian_sigma_max", 20.0)),
                    poisson_scale=float(getattr(dc, "poisson_scale", 1.0)),
                    poisson_peak=float(getattr(dc, "poisson_peak", 100.0)),
                    rng=rng,
                )
    except Exception:
        pass
    return out
