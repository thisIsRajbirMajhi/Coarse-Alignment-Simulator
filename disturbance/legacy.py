"""Backward-compatible facade for the pre-domain disturbance API."""

from disturbance.environment.atmospheric import apply_atmospheric_disturbance
from disturbance.camera.jitter import apply_camera_jitter, apply_camera_jitter_with_state
from disturbance.camera.drift import apply_camera_motion, apply_camera_motion_with_state
from disturbance.core.config import DisturbanceConfig
from disturbance.core.constants import *  # noqa: F401,F403
from disturbance.core.helpers import r0_from_intensity as _r0_from_intensity
from disturbance.core.helpers import rytov_variance as _rytov_variance
from disturbance.sensor.image_noise import (
	apply_gaussian_noise, apply_image_noise, apply_poisson_noise,
	apply_salt_pepper, clear_hot_pixel_cache,
)
from disturbance.camera.platform import apply_platform_motion
from disturbance.sensor.sensor_noise import apply_sensor_noise
from disturbance.core.state import (
	_cam_motion_state_global, _elapsed_dt, _jitter_state_global,
	_platform_state_global, _turb_state, _vib_state,
	reset_camera_motion_state, reset_disturbance_state, reset_jitter_state,
	reset_platform_motion_state, reset_turbulence_state, reset_vibration_state,
)
from disturbance.optical.turbulence import _kolmogorov_displacement, apply_turbulence
from disturbance.camera.vibration import apply_platform_vibration

__all__ = [
	"apply_sensor_noise", "apply_turbulence", "apply_platform_vibration",
	"apply_camera_motion", "apply_camera_motion_with_state", "apply_camera_jitter",
	"apply_camera_jitter_with_state", "apply_image_noise", "apply_salt_pepper",
	"apply_gaussian_noise", "apply_poisson_noise", "apply_atmospheric_disturbance",
	"apply_platform_motion", "DisturbanceConfig", "reset_disturbance_state",
	"reset_turbulence_state", "reset_vibration_state", "reset_camera_motion_state",
	"reset_platform_motion_state", "reset_jitter_state", "clear_hot_pixel_cache",
	"_turb_state", "_vib_state", "_cam_motion_state_global", "_platform_state_global",
	"_jitter_state_global", "_elapsed_dt", "_kolmogorov_displacement",
	"_r0_from_intensity", "_rytov_variance",
]