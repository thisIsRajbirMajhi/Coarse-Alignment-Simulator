# disturbance/config.py - Typed, validated configuration for all Disturbances & Noise

from __future__ import annotations

from dataclasses import asdict, dataclass

from common.config_base import BaseValidatedConfig, clip_field
from disturbance.constants import (
    ATMOSPHERIC_BRIGHTNESS_LIMITS,
    ATMOSPHERIC_CONTRAST_LIMITS,
    ATMOSPHERIC_DEFAULT_PRESET,
    ATMOSPHERIC_PRESETS,
    CAMERA_JITTER_LIMITS,
    GAUSSIAN_SIGMA_LIMITS,
    GAUSSIAN_SIGMA_MAX_USER,
    GAUSSIAN_SIGMA_USER_LIMITS,
    PLATFORM_DEFAULT_PROFILE,
    PLATFORM_PROFILES,
    PLATFORM_SPEED_LIMITS,
    POISSON_PEAK_DEFAULT,
    POISSON_PEAK_LIMITS,
    POISSON_SCALE_DEFAULT,
    POISSON_SCALE_LIMITS,
    SALT_PEPPER_DEFAULT_DENSITY,
    SALT_PEPPER_LIMITS,
    SALT_PEPPER_RATIO_DEFAULT,
    SALT_PEPPER_RATIO_LIMITS,
    SLIDER_MAX,
    SLIDER_MIN,
)


# Unified limits for validated config
# For user-defined max beyond spec default 20, we allow up to 50 for sigma/jitter/platform
DISTURBANCE_LIMITS: dict[str, tuple[float, float]] = {
    # legacy 0..10
    "turbulence": (SLIDER_MIN, SLIDER_MAX),
    "vibration": (SLIDER_MIN, SLIDER_MAX),
    "camera_motion": (SLIDER_MIN, SLIDER_MAX),
    "noise": (SLIDER_MIN, SLIDER_MAX),
    # image noise — sigma user-extensible 0..50 (spec max 20 + user)
    "salt_pepper_density": SALT_PEPPER_LIMITS,
    "salt_pepper_ratio": SALT_PEPPER_RATIO_LIMITS,
    "gaussian_sigma": GAUSSIAN_SIGMA_USER_LIMITS,  # allow up to 50, clipped later to gaussian_sigma_max
    "gaussian_sigma_max": GAUSSIAN_SIGMA_USER_LIMITS,
    "poisson_scale": POISSON_SCALE_LIMITS,
    "poisson_peak": POISSON_PEAK_LIMITS,
    "max_noise_std": (0.0, 50.0),
    # camera jitter px/frame 0..50 (spec 20 + user)
    "camera_jitter": (0.0, 50.0),
    "camera_jitter_max_user": (0.0, 50.0),
    # atmospheric
    "atmospheric_contrast": ATMOSPHERIC_CONTRAST_LIMITS,
    "atmospheric_brightness": ATMOSPHERIC_BRIGHTNESS_LIMITS,
    # platform motion 0..50 (spec 20 + user)
    "platform_speed": (0.0, 50.0),
    "platform_speed_max_user": (0.0, 50.0),
}

DISTURBANCE_DEFAULTS: dict = {
    "turbulence": 0,
    "vibration": 0,
    "camera_motion": 0,
    "noise": 0,
    # image noise — all off by default, density 0.10 when enabled, sigma 8
    "enable_salt_pepper": False,
    "enable_gaussian": False,
    "enable_poisson": False,
    "salt_pepper_density": SALT_PEPPER_DEFAULT_DENSITY,  # 10%
    "salt_pepper_ratio": SALT_PEPPER_RATIO_DEFAULT,  # 0.5 = equal salt/pepper
    "gaussian_sigma": 8.0,
    "gaussian_sigma_max": 20.0,  # user cap; default 20px spec
    "poisson_scale": POISSON_SCALE_DEFAULT,
    "poisson_peak": POISSON_PEAK_DEFAULT,
    "max_noise_std": 20.0,
    # camera jitter
    "camera_jitter": 0.0,
    # atmospheric
    "atmospheric_preset": ATMOSPHERIC_DEFAULT_PRESET,  # Clear
    "atmospheric_contrast": 0.0,
    "atmospheric_brightness": 0.0,
    # platform motion — Linear mandatory default
    "platform_profile": PLATFORM_DEFAULT_PROFILE,
    "platform_speed": 0.0,
}


@dataclass
class DisturbanceConfig(BaseValidatedConfig):
    """
    Unified config for Disturbance & Noise panel.

    Groups:
      Legacy: turbulence, vibration, camera_motion, noise (0..10 each)
      Image Noise: enable_* + salt_pepper_density (0..0.20) + gaussian_sigma (0..20+user50) + poisson
      Camera Jitter: camera_jitter (0..20 px/frame, user-extensible)
      Atmospheric: atmospheric_preset (Clear/Haze/Fog/Rain/Low Light/User Defined) + contrast/brightness 0..100
      Platform Motion: platform_profile (Linear default + 6 optional) + platform_speed 0..20 px/frame

    Validation: clip_field + normalize preset/profile strings, User Defined honours custom contrast/brightness.
    """

    LIMITS = DISTURBANCE_LIMITS
    DEFAULTS = DISTURBANCE_DEFAULTS

    # Legacy sliders 0..10
    turbulence: int = DISTURBANCE_DEFAULTS["turbulence"]
    vibration: int = DISTURBANCE_DEFAULTS["vibration"]
    camera_motion: int = DISTURBANCE_DEFAULTS["camera_motion"]
    noise: int = DISTURBANCE_DEFAULTS["noise"]

    # Image Noise
    enable_salt_pepper: bool = DISTURBANCE_DEFAULTS["enable_salt_pepper"]
    enable_gaussian: bool = DISTURBANCE_DEFAULTS["enable_gaussian"]
    enable_poisson: bool = DISTURBANCE_DEFAULTS["enable_poisson"]
    salt_pepper_density: float = DISTURBANCE_DEFAULTS["salt_pepper_density"]
    salt_pepper_ratio: float = DISTURBANCE_DEFAULTS["salt_pepper_ratio"]
    gaussian_sigma: float = DISTURBANCE_DEFAULTS["gaussian_sigma"]
    gaussian_sigma_max: float = DISTURBANCE_DEFAULTS["gaussian_sigma_max"]
    poisson_scale: float = DISTURBANCE_DEFAULTS["poisson_scale"]
    poisson_peak: float = DISTURBANCE_DEFAULTS["poisson_peak"]
    max_noise_std: float = DISTURBANCE_DEFAULTS["max_noise_std"]

    # Camera Jitter
    camera_jitter: float = DISTURBANCE_DEFAULTS["camera_jitter"]

    # Atmospheric
    atmospheric_preset: str = DISTURBANCE_DEFAULTS["atmospheric_preset"]
    atmospheric_contrast: float = DISTURBANCE_DEFAULTS["atmospheric_contrast"]
    atmospheric_brightness: float = DISTURBANCE_DEFAULTS["atmospheric_brightness"]

    # Platform Motion
    platform_profile: str = DISTURBANCE_DEFAULTS["platform_profile"]
    platform_speed: float = DISTURBANCE_DEFAULTS["platform_speed"]

    def validate(self) -> "DisturbanceConfig":
        # legacy 0..10 ints
        self.turbulence = int(clip_field(self.turbulence, *DISTURBANCE_LIMITS["turbulence"]))
        self.vibration = int(clip_field(self.vibration, *DISTURBANCE_LIMITS["vibration"]))
        self.camera_motion = int(clip_field(self.camera_motion, *DISTURBANCE_LIMITS["camera_motion"]))
        self.noise = int(clip_field(self.noise, *DISTURBANCE_LIMITS["noise"]))

        self.enable_salt_pepper = bool(self.enable_salt_pepper)
        self.enable_gaussian = bool(self.enable_gaussian)
        self.enable_poisson = bool(self.enable_poisson)
        self.salt_pepper_density = float(clip_field(self.salt_pepper_density, *SALT_PEPPER_LIMITS))
        self.salt_pepper_ratio = float(clip_field(self.salt_pepper_ratio, *SALT_PEPPER_RATIO_LIMITS))
        # gaussian_sigma clipped to user max, not just 20 — allows user-defined beyond 20
        # First ensure max cap itself is valid
        self.gaussian_sigma_max = float(clip_field(self.gaussian_sigma_max, *GAUSSIAN_SIGMA_USER_LIMITS))
        if self.gaussian_sigma_max < 1e-9:
            self.gaussian_sigma_max = 20.0
        # sigma limited to max
        self.gaussian_sigma = float(clip_field(self.gaussian_sigma, 0.0, float(self.gaussian_sigma_max)))
        self.poisson_scale = float(clip_field(self.poisson_scale, *POISSON_SCALE_LIMITS))
        self.poisson_peak = float(clip_field(self.poisson_peak, *POISSON_PEAK_LIMITS))
        self.max_noise_std = float(clip_field(self.max_noise_std, 0.0, 50.0))
        # Alias sync — gaussian_sigma_max is authoritative; max_noise_std mirrors it
        # If caller explicitly set max_noise_std != default and different from current max, honour max_noise_std as new max
        # Heuristic: if max_noise_std was explicitly set to non-default and gaussian_sigma_max is default (20), use max_noise_std
        # But simplest: keep both equal to gaussian_sigma_max after validation (single source)
        # If max_noise_std differs and gaussian_sigma_max is default, allow max_noise_std to override
        if abs(self.max_noise_std - 20.0) > 1e-9 and abs(self.gaussian_sigma_max - 20.0) < 1e-9:
            # user set max_noise_std explicitly without touching gaussian_sigma_max
            self.gaussian_sigma_max = float(self.max_noise_std)
            # re-clip sigma to new max
            self.gaussian_sigma = float(clip_field(self.gaussian_sigma, 0.0, float(self.gaussian_sigma_max)))
        else:
            self.max_noise_std = float(self.gaussian_sigma_max)

        self.camera_jitter = float(clip_field(self.camera_jitter, 0.0, 50.0))
        # spec default max 20 but user extensible to 50 — already allowed 0..50

        # Atmospheric preset normalize
        preset = str(self.atmospheric_preset).strip()
        # map case-insensitive
        found = None
        for p in ATMOSPHERIC_PRESETS:
            if p.lower() == preset.lower():
                found = p
                break
            if preset.lower() in (p.lower().replace(" ", "_"), p.lower().replace(" ", "")):
                found = p
                break
        if found is None and preset.lower() in ("low_light", "low-light"):
            found = "Low Light"
        if found is None and preset.lower() in ("user_defined", "user-defined", "userdefined"):
            found = "User Defined"
        self.atmospheric_preset = found if found is not None else ATMOSPHERIC_DEFAULT_PRESET
        # For fixed presets, auto-populate contrast/brightness from map so stored matches what apply uses
        # (User Defined keeps user values)
        if self.atmospheric_preset != "User Defined":
            try:
                from disturbance.constants import ATMOSPHERIC_PRESET_MAP as _AMap2
                mp = _AMap2.get(self.atmospheric_preset, {})
                preset_c = float(mp.get("contrast", 0.0))
                preset_b = float(mp.get("brightness", 0.0))
                # warn if user values will be overwritten (H7)
                if abs(self.atmospheric_contrast - preset_c) > 1e-6 or abs(self.atmospheric_brightness - preset_b) > 1e-6:
                    import logging
                    logging.getLogger("disturbance").debug(f"Preset {self.atmospheric_preset} overwrites contrast {self.atmospheric_contrast}->{preset_c} brightness {self.atmospheric_brightness}->{preset_b}")
                self.atmospheric_contrast = float(preset_c)
                self.atmospheric_brightness = float(preset_b)
            except Exception:
                self.atmospheric_contrast = float(clip_field(self.atmospheric_contrast, *ATMOSPHERIC_CONTRAST_LIMITS))
                self.atmospheric_brightness = float(clip_field(self.atmospheric_brightness, *ATMOSPHERIC_BRIGHTNESS_LIMITS))
        else:
            self.atmospheric_contrast = float(clip_field(self.atmospheric_contrast, *ATMOSPHERIC_CONTRAST_LIMITS))
            self.atmospheric_brightness = float(clip_field(self.atmospheric_brightness, *ATMOSPHERIC_BRIGHTNESS_LIMITS))
        # If not User Defined, contrast/brightness are still stored but not applied unless preset is User Defined;
        # however for reporting we keep them (now they match preset).

        # Platform
        prof = str(self.platform_profile).strip()
        # normalize to display names
        found_prof = None
        for pp in PLATFORM_PROFILES:
            if pp.lower() == prof.lower():
                found_prof = pp
                break
        if found_prof is None:
            # map keys
            low = prof.lower().replace("_", " ").replace("-", " ").strip()
            for pp in PLATFORM_PROFILES:
                if pp.lower().replace("-", " ").replace("_", " ") == low:
                    found_prof = pp
                    break
        if found_prof is None:
            # try internal map
            from disturbance.constants import PLATFORM_PROFILE_MAP as _map
            if prof.lower() in _map.values():
                # reverse lookup
                for k, v in _map.items():
                    if v == prof.lower():
                        found_prof = k
                        break
        self.platform_profile = found_prof if found_prof is not None else PLATFORM_DEFAULT_PROFILE
        self.platform_speed = float(clip_field(self.platform_speed, 0.0, 50.0))
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DisturbanceConfig":
        allowed = set(DISTURBANCE_DEFAULTS.keys()) | set(DISTURBANCE_LIMITS.keys()) | {"atmospheric_preset", "platform_profile", "enable_salt_pepper", "enable_gaussian", "enable_poisson"}
        unknown = [k for k in data.keys() if k not in allowed]
        if unknown:
            import logging
            logging.getLogger("disturbance").warning(f"Ignoring unknown disturbance keys: {unknown}")
        known = {k: v for k, v in data.items() if k in allowed}
        merged = {**DISTURBANCE_DEFAULTS, **known}
        # ensure all dataclass fields covered
        allowed = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in merged.items() if k in allowed}
        return cls(**filtered).validate()  # type: ignore

    def image_noise_enabled(self) -> bool:
        return bool(self.enable_salt_pepper or self.enable_gaussian or self.enable_poisson)
