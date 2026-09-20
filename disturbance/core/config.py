# disturbance/config.py - Typed, validated configuration for all Disturbances & Noise

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from common.config_base import BaseValidatedConfig, clip_field
from disturbance.core.constants import (
    ATMOSPHERIC_BRIGHTNESS_LIMITS,
    ATMOSPHERIC_CONTRAST_LIMITS,
    ATMOSPHERIC_DEFAULT_PRESET,
    ATMOSPHERIC_PRESETS,
    CAMERA_JITTER_LIMITS,
    GAUSSIAN_SIGMA_MAX_USER,
    GAUSSIAN_SIGMA_USER_LIMITS,
    PLATFORM_DEFAULT_PROFILE,
    PLATFORM_PROFILES,
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


# Unified limits per PDF spec Sr21.2-21.5 — max 20
# Plus Propagation Channel limits per DisturbanceModel.txt §14.
DISTURBANCE_LIMITS: dict[str, tuple[float, float]] = {
    # legacy 0..10
    "turbulence": (SLIDER_MIN, SLIDER_MAX),
    "vibration": (SLIDER_MIN, SLIDER_MAX),
    "camera_motion": (SLIDER_MIN, SLIDER_MAX),
    "noise": (SLIDER_MIN, SLIDER_MAX),
    # image noise — sigma max 20 per spec Sr21.2
    "salt_pepper_density": SALT_PEPPER_LIMITS,
    "salt_pepper_ratio": SALT_PEPPER_RATIO_LIMITS,
    "gaussian_sigma": GAUSSIAN_SIGMA_USER_LIMITS,  # 0..20 per spec
    "gaussian_sigma_max": GAUSSIAN_SIGMA_USER_LIMITS,
    "poisson_scale": POISSON_SCALE_LIMITS,
    "poisson_peak": POISSON_PEAK_LIMITS,
    "max_noise_std": (0.0, 20.0),
    # camera jitter px/frame 0..20 per spec Sr21.3
    "camera_jitter": (0.0, 20.0),
    "camera_jitter_max_user": (0.0, 20.0),
    "camera_jitter_max_x": (0.0, 20.0),
    "camera_jitter_max_y": (0.0, 20.0),
    "camera_jitter_frequency": (0.0, 50.0),
    # atmospheric
    "atmospheric_contrast": ATMOSPHERIC_CONTRAST_LIMITS,
    "atmospheric_brightness": ATMOSPHERIC_BRIGHTNESS_LIMITS,
    # propagation channel (DisturbanceModel.txt §3/§14)
    "channel_severity": (0.0, 1.0),
    "channel_attenuation_strength": (0.0, 1.0),
    "channel_beam_wander": (0.0, 2.0),
    "channel_beam_spread": (0.0, 2.0),
    "channel_intensity_fluctuation": (0.0, 2.0),
    # platform motion 0..20 per spec Sr21.5
    "platform_speed": (0.0, 20.0),
    "platform_speed_max_user": (0.0, 20.0),
    "platform_amplitude_x": (0.0, 400.0),
    "platform_amplitude_y": (0.0, 400.0),
    "platform_direction": (-180.0, 180.0),
    "platform_frequency": (0.0, 5.0),
    "platform_phase": (-180.0, 180.0),
}

# GUI disturbance presets per DisturbanceModel.txt §15.
CHANNEL_PRESETS: tuple[str, ...] = (
    "Clear", "Haze", "Fog", "Rain", "Low Light", "Moderate", "Severe", "Custom",
)

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
    # propagation channel (DisturbanceModel.txt §3/§14) — beam-state medium
    "global_enabled": True,
    "channel_enabled": True,
    "channel_severity": 1.0,
    "channel_attenuation_enabled": True,
    "channel_attenuation_strength": 1.0,
    "channel_attenuation_model": "Atmospheric",
    "channel_beam_wander": 1.0,
    "channel_beam_spread": 1.0,
    "channel_intensity_fluctuation": 1.0,
    # camera jitter detail (§11)
    "camera_jitter_enabled": True,
    "camera_jitter_max_x": 20.0,
    "camera_jitter_max_y": 20.0,
    "camera_jitter_profile": "Gaussian",
    "camera_jitter_frequency": 8.0,
    # platform motion detail (§12)
    "platform_enabled": True,
    "platform_amplitude_x": 110.0,
    "platform_amplitude_y": 110.0,
    "platform_direction": 0.0,
    "platform_frequency": 1.0,
    "platform_phase": 0.0,
}


@dataclass
class GlobalDisturbanceConfig:
    enabled: bool = True
    seed: int | None = None


@dataclass
class EnvironmentDisturbanceConfig:
    atmospheric_preset: str = ATMOSPHERIC_DEFAULT_PRESET
    atmospheric_contrast: float = 0.0
    atmospheric_brightness: float = 0.0



@dataclass
class PropagationChannelConfig:
    """Optical Propagation Channel — beam-state medium (§2/§14)."""

    enabled: bool = True
    atmospheric_condition: str = ATMOSPHERIC_DEFAULT_PRESET
    severity: float = 1.0
    attenuation_enabled: bool = True
    attenuation_strength: float = 1.0
    attenuation_model: str = "Atmospheric"
    turbulence: int = 0
    beam_wander: float = 1.0
    beam_spread: float = 1.0
    intensity_fluctuation: float = 1.0
    contrast_reduction: float = 0.0
    brightness_reduction: float = 0.0


@dataclass
class PlatformMotionConfig:
    enabled: bool = True
    profile: str = PLATFORM_DEFAULT_PROFILE
    amplitude_x: float = 110.0
    amplitude_y: float = 110.0
    speed: float = 0.0
    direction: float = 0.0
    frequency: float = 1.0
    phase: float = 0.0


@dataclass
class CameraDisturbanceConfig:
    vibration: float = 0.0
    camera_motion: float = 0.0
    camera_jitter: float = 0.0
    jitter_enabled: bool = True
    jitter_max_x: float = 20.0
    jitter_max_y: float = 20.0
    jitter_profile: str = "Gaussian"
    jitter_frequency: float = 8.0
    platform_profile: str = PLATFORM_DEFAULT_PROFILE
    platform_speed: float = 0.0


@dataclass
class OpticalDisturbanceConfig:
    turbulence: int = 0
    channel: PropagationChannelConfig = field(default_factory=PropagationChannelConfig)


@dataclass
class SensorDisturbanceConfig:
    noise: int = 0
    enable_salt_pepper: bool = False
    enable_gaussian: bool = False
    enable_poisson: bool = False
    salt_pepper_density: float = SALT_PEPPER_DEFAULT_DENSITY
    salt_pepper_ratio: float = SALT_PEPPER_RATIO_DEFAULT
    gaussian_sigma: float = 8.0
    gaussian_sigma_max: float = 20.0
    poisson_scale: float = POISSON_SCALE_DEFAULT
    poisson_peak: float = POISSON_PEAK_DEFAULT
    max_noise_std: float = 20.0


@dataclass
class DisturbanceConfig(BaseValidatedConfig):
    """
    Unified config for Disturbance & Noise panel.

    Groups:
      Legacy: turbulence, vibration, camera_motion, noise (0..10 each)
      Image Noise: enable_* + salt_pepper_density (0..0.20) + gaussian_sigma (0..20+user50) + poisson
      Camera Jitter: camera_jitter (0..20 px/frame, user-extensible)
      Atmospheric: atmospheric_preset (Clear/Haze/Fog/User Defined) + contrast/brightness 0..100
      Platform Motion: platform_profile (Linear default + 6 optional) + platform_speed 0..20 px/frame

    Validation: clip_field + normalize preset/profile strings, User Defined honours custom contrast/brightness.
    """

    LIMITS = DISTURBANCE_LIMITS
    DEFAULTS = DISTURBANCE_DEFAULTS

    # Ownership-aligned configuration. Legacy scalar fields below remain the
    # serialization and GUI compatibility surface during migration.
    global_: GlobalDisturbanceConfig = field(default_factory=GlobalDisturbanceConfig)
    environment: EnvironmentDisturbanceConfig = field(default_factory=EnvironmentDisturbanceConfig)
    camera: CameraDisturbanceConfig = field(default_factory=CameraDisturbanceConfig)
    optical: OpticalDisturbanceConfig = field(default_factory=OpticalDisturbanceConfig)
    sensor: SensorDisturbanceConfig = field(default_factory=SensorDisturbanceConfig)

    # Legacy mount sliders 0..10 (float — fractional intensities are
    # preserved; int inputs still validate to whole floats).
    turbulence: int = DISTURBANCE_DEFAULTS["turbulence"]
    vibration: float = 0.0
    camera_motion: float = 0.0
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
    camera_jitter_enabled: bool = DISTURBANCE_DEFAULTS["camera_jitter_enabled"]
    camera_jitter_max_x: float = DISTURBANCE_DEFAULTS["camera_jitter_max_x"]
    camera_jitter_max_y: float = DISTURBANCE_DEFAULTS["camera_jitter_max_y"]
    camera_jitter_profile: str = DISTURBANCE_DEFAULTS["camera_jitter_profile"]
    camera_jitter_frequency: float = DISTURBANCE_DEFAULTS["camera_jitter_frequency"]

    # Atmospheric
    atmospheric_preset: str = DISTURBANCE_DEFAULTS["atmospheric_preset"]
    atmospheric_contrast: float = DISTURBANCE_DEFAULTS["atmospheric_contrast"]
    atmospheric_brightness: float = DISTURBANCE_DEFAULTS["atmospheric_brightness"]

    # Platform Motion (§12 — own subsystem, geometry-level)
    platform_enabled: bool = DISTURBANCE_DEFAULTS["platform_enabled"]
    platform_profile: str = DISTURBANCE_DEFAULTS["platform_profile"]
    platform_speed: float = DISTURBANCE_DEFAULTS["platform_speed"]
    platform_amplitude_x: float = DISTURBANCE_DEFAULTS["platform_amplitude_x"]
    platform_amplitude_y: float = DISTURBANCE_DEFAULTS["platform_amplitude_y"]
    platform_direction: float = DISTURBANCE_DEFAULTS["platform_direction"]
    platform_frequency: float = DISTURBANCE_DEFAULTS["platform_frequency"]
    platform_phase: float = DISTURBANCE_DEFAULTS["platform_phase"]

    # Propagation Channel (§2/§14 — beam-state medium before the camera)
    global_enabled: bool = DISTURBANCE_DEFAULTS["global_enabled"]
    channel_enabled: bool = DISTURBANCE_DEFAULTS["channel_enabled"]
    channel_severity: float = DISTURBANCE_DEFAULTS["channel_severity"]
    channel_attenuation_enabled: bool = DISTURBANCE_DEFAULTS["channel_attenuation_enabled"]
    channel_attenuation_strength: float = DISTURBANCE_DEFAULTS["channel_attenuation_strength"]
    channel_attenuation_model: str = DISTURBANCE_DEFAULTS["channel_attenuation_model"]
    channel_beam_wander: float = DISTURBANCE_DEFAULTS["channel_beam_wander"]
    channel_beam_spread: float = DISTURBANCE_DEFAULTS["channel_beam_spread"]
    channel_intensity_fluctuation: float = DISTURBANCE_DEFAULTS["channel_intensity_fluctuation"]

    # Ownership-aligned platform view (geometry-level, separate from channel).
    platform: PlatformMotionConfig = field(default_factory=PlatformMotionConfig)

    def validate(self) -> "DisturbanceConfig":
        # Accept ownership-aligned construction while retaining legacy keyword
        # compatibility. Explicit nested values override untouched old defaults.
        if self.turbulence == DISTURBANCE_DEFAULTS["turbulence"]:
            self.turbulence = self.optical.turbulence
        if self.vibration == DISTURBANCE_DEFAULTS["vibration"]:
            self.vibration = self.camera.vibration
        if self.camera_motion == DISTURBANCE_DEFAULTS["camera_motion"]:
            self.camera_motion = self.camera.camera_motion
        if self.camera_jitter == DISTURBANCE_DEFAULTS["camera_jitter"]:
            self.camera_jitter = self.camera.camera_jitter
        if self.platform_profile == DISTURBANCE_DEFAULTS["platform_profile"]:
            self.platform_profile = self.camera.platform_profile
        if self.platform_speed == DISTURBANCE_DEFAULTS["platform_speed"]:
            self.platform_speed = self.camera.platform_speed
        if self.atmospheric_preset == DISTURBANCE_DEFAULTS["atmospheric_preset"]:
            self.atmospheric_preset = self.environment.atmospheric_preset
        if self.atmospheric_contrast == DISTURBANCE_DEFAULTS["atmospheric_contrast"]:
            self.atmospheric_contrast = self.environment.atmospheric_contrast
        if self.atmospheric_brightness == DISTURBANCE_DEFAULTS["atmospheric_brightness"]:
            self.atmospheric_brightness = self.environment.atmospheric_brightness
        for name in ("noise", "enable_salt_pepper", "enable_gaussian", "enable_poisson", "salt_pepper_density", "salt_pepper_ratio", "gaussian_sigma", "gaussian_sigma_max", "poisson_scale", "poisson_peak", "max_noise_std"):
            if getattr(self, name) == DISTURBANCE_DEFAULTS[name]:
                setattr(self, name, getattr(self.sensor, name))
        # Nested-first sync for new channel/platform/jitter fields (same pattern).
        try:
            _ch = self.optical.channel
            if self.channel_enabled == DISTURBANCE_DEFAULTS["channel_enabled"]:
                self.channel_enabled = bool(getattr(_ch, "enabled", True))
            if self.channel_severity == DISTURBANCE_DEFAULTS["channel_severity"]:
                self.channel_severity = float(getattr(_ch, "severity", 1.0))
            if self.channel_attenuation_enabled == DISTURBANCE_DEFAULTS["channel_attenuation_enabled"]:
                self.channel_attenuation_enabled = bool(getattr(_ch, "attenuation_enabled", True))
            if self.channel_attenuation_strength == DISTURBANCE_DEFAULTS["channel_attenuation_strength"]:
                self.channel_attenuation_strength = float(getattr(_ch, "attenuation_strength", 1.0))
            if self.channel_attenuation_model == DISTURBANCE_DEFAULTS["channel_attenuation_model"]:
                self.channel_attenuation_model = str(getattr(_ch, "attenuation_model", "Atmospheric"))
            if self.channel_beam_wander == DISTURBANCE_DEFAULTS["channel_beam_wander"]:
                self.channel_beam_wander = float(getattr(_ch, "beam_wander", 1.0))
            if self.channel_beam_spread == DISTURBANCE_DEFAULTS["channel_beam_spread"]:
                self.channel_beam_spread = float(getattr(_ch, "beam_spread", 1.0))
            if self.channel_intensity_fluctuation == DISTURBANCE_DEFAULTS["channel_intensity_fluctuation"]:
                self.channel_intensity_fluctuation = float(getattr(_ch, "intensity_fluctuation", 1.0))
        except Exception:
            pass
        try:
            _pl = self.platform
            if self.platform_enabled == DISTURBANCE_DEFAULTS["platform_enabled"]:
                self.platform_enabled = bool(getattr(_pl, "enabled", True))
            if self.platform_amplitude_x == DISTURBANCE_DEFAULTS["platform_amplitude_x"]:
                self.platform_amplitude_x = float(getattr(_pl, "amplitude_x", 110.0))
            if self.platform_amplitude_y == DISTURBANCE_DEFAULTS["platform_amplitude_y"]:
                self.platform_amplitude_y = float(getattr(_pl, "amplitude_y", 110.0))
            if self.platform_direction == DISTURBANCE_DEFAULTS["platform_direction"]:
                self.platform_direction = float(getattr(_pl, "direction", 0.0))
            if self.platform_frequency == DISTURBANCE_DEFAULTS["platform_frequency"]:
                self.platform_frequency = float(getattr(_pl, "frequency", 1.0))
            if self.platform_phase == DISTURBANCE_DEFAULTS["platform_phase"]:
                self.platform_phase = float(getattr(_pl, "phase", 0.0))
            if self.global_enabled == DISTURBANCE_DEFAULTS["global_enabled"]:
                self.global_enabled = bool(getattr(self.global_, "enabled", True))
        except Exception:
            pass

        # legacy turbulence/noise stay int; vibration/camera_motion are float
        # (fractional mount intensities must survive validation).
        self.turbulence = int(clip_field(self.turbulence, *DISTURBANCE_LIMITS["turbulence"]))
        self.vibration = float(clip_field(float(self.vibration), *DISTURBANCE_LIMITS["vibration"]))
        self.camera_motion = float(clip_field(float(self.camera_motion), *DISTURBANCE_LIMITS["camera_motion"]))
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
        self.max_noise_std = float(clip_field(self.max_noise_std, 0.0, 20.0))
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

        self.camera_jitter = float(clip_field(self.camera_jitter, 0.0, 20.0))

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
        if found is None and preset.lower() in ("user_defined", "user-defined", "userdefined"):
            found = "User Defined"
        self.atmospheric_preset = found if found is not None else ATMOSPHERIC_DEFAULT_PRESET
        # Preserve user contrast/brightness (validate only clips). The apply
        # layer (_resolve_preset) already selects preset-map values for fixed
        # presets and user values only for "User Defined", so overwriting here
        # would silently discard tuning and break training randomization.
        self.atmospheric_contrast = float(clip_field(self.atmospheric_contrast, *ATMOSPHERIC_CONTRAST_LIMITS))
        self.atmospheric_brightness = float(clip_field(self.atmospheric_brightness, *ATMOSPHERIC_BRIGHTNESS_LIMITS))
        # Fixed presets ignore stored contrast/brightness at apply time;
        # "User Defined" honours them.

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
            from disturbance.core.constants import PLATFORM_PROFILE_MAP as _map
            if prof.lower() in _map.values():
                # reverse lookup
                for k, v in _map.items():
                    if v == prof.lower():
                        found_prof = k
                        break
        self.platform_profile = found_prof if found_prof is not None else PLATFORM_DEFAULT_PROFILE
        self.platform_speed = float(clip_field(self.platform_speed, 0.0, 20.0))
        self.platform_enabled = bool(getattr(self, "platform_enabled", True))
        self.platform_amplitude_x = float(clip_field(float(getattr(self, "platform_amplitude_x", 110.0)), *DISTURBANCE_LIMITS["platform_amplitude_x"]))
        self.platform_amplitude_y = float(clip_field(float(getattr(self, "platform_amplitude_y", 110.0)), *DISTURBANCE_LIMITS["platform_amplitude_y"]))
        self.platform_direction = float(clip_field(float(getattr(self, "platform_direction", 0.0)), *DISTURBANCE_LIMITS["platform_direction"]))
        self.platform_frequency = float(clip_field(float(getattr(self, "platform_frequency", 1.0)), *DISTURBANCE_LIMITS["platform_frequency"]))
        self.platform_phase = float(clip_field(float(getattr(self, "platform_phase", 0.0)), *DISTURBANCE_LIMITS["platform_phase"]))

        # Camera jitter detail (§11 — camera effect, distinct from channel wander)
        self.camera_jitter_enabled = bool(getattr(self, "camera_jitter_enabled", True))
        self.camera_jitter_max_x = float(clip_field(float(getattr(self, "camera_jitter_max_x", 20.0)), *DISTURBANCE_LIMITS["camera_jitter_max_x"]))
        self.camera_jitter_max_y = float(clip_field(float(getattr(self, "camera_jitter_max_y", 20.0)), *DISTURBANCE_LIMITS["camera_jitter_max_y"]))
        self.camera_jitter_frequency = float(clip_field(float(getattr(self, "camera_jitter_frequency", 8.0)), *DISTURBANCE_LIMITS["camera_jitter_frequency"]))
        prof_j = str(getattr(self, "camera_jitter_profile", "Gaussian")).strip() or "Gaussian"
        self.camera_jitter_profile = prof_j

        # Propagation channel (§2/§3/§14 — beam-state medium)
        self.global_enabled = bool(getattr(self, "global_enabled", True))
        # legacy global_ alias
        try:
            self.global_.enabled = bool(self.global_enabled)
        except Exception:
            pass
        self.channel_enabled = bool(getattr(self, "channel_enabled", True))
        self.channel_severity = float(clip_field(float(getattr(self, "channel_severity", 1.0)), *DISTURBANCE_LIMITS["channel_severity"]))
        # Clear passes (almost) ideally even at severity 1 — severity scales losses only
        self.channel_attenuation_enabled = bool(getattr(self, "channel_attenuation_enabled", True))
        self.channel_attenuation_strength = float(clip_field(float(getattr(self, "channel_attenuation_strength", 1.0)), *DISTURBANCE_LIMITS["channel_attenuation_strength"]))
        model = str(getattr(self, "channel_attenuation_model", "Atmospheric")).strip()
        valid_models = ("Fixed", "Distance Based", "Atmospheric", "Custom")
        found_m = next((m for m in valid_models if m.lower() == model.lower()), "Atmospheric")
        self.channel_attenuation_model = found_m
        self.channel_beam_wander = float(clip_field(float(getattr(self, "channel_beam_wander", 1.0)), *DISTURBANCE_LIMITS["channel_beam_wander"]))
        self.channel_beam_spread = float(clip_field(float(getattr(self, "channel_beam_spread", 1.0)), *DISTURBANCE_LIMITS["channel_beam_spread"]))
        self.channel_intensity_fluctuation = float(clip_field(float(getattr(self, "channel_intensity_fluctuation", 1.0)), *DISTURBANCE_LIMITS["channel_intensity_fluctuation"]))

        # Keep the ownership-aligned view synchronized with the legacy view.
        self.optical.turbulence = self.turbulence
        try:
            ch = self.optical.channel
            ch.enabled = bool(self.channel_enabled)
            ch.atmospheric_condition = str(self.atmospheric_preset)
            ch.severity = float(self.channel_severity)
            ch.attenuation_enabled = bool(self.channel_attenuation_enabled)
            ch.attenuation_strength = float(self.channel_attenuation_strength)
            ch.attenuation_model = str(self.channel_attenuation_model)
            ch.turbulence = int(self.turbulence)
            ch.beam_wander = float(self.channel_beam_wander)
            ch.beam_spread = float(self.channel_beam_spread)
            ch.intensity_fluctuation = float(self.channel_intensity_fluctuation)
            ch.contrast_reduction = float(self.atmospheric_contrast)
            ch.brightness_reduction = float(self.atmospheric_brightness)
        except Exception:
            pass
        self.camera.vibration = self.vibration
        self.camera.camera_motion = self.camera_motion
        self.camera.camera_jitter = self.camera_jitter
        try:
            self.camera.jitter_enabled = bool(self.camera_jitter_enabled)
            self.camera.jitter_max_x = float(self.camera_jitter_max_x)
            self.camera.jitter_max_y = float(self.camera_jitter_max_y)
            self.camera.jitter_profile = str(self.camera_jitter_profile)
            self.camera.jitter_frequency = float(self.camera_jitter_frequency)
        except Exception:
            pass
        self.camera.platform_profile = self.platform_profile
        self.camera.platform_speed = self.platform_speed
        try:
            self.platform.enabled = bool(self.platform_enabled)
            self.platform.profile = str(self.platform_profile)
            self.platform.speed = float(self.platform_speed)
            self.platform.amplitude_x = float(self.platform_amplitude_x)
            self.platform.amplitude_y = float(self.platform_amplitude_y)
            self.platform.direction = float(self.platform_direction)
            self.platform.frequency = float(self.platform_frequency)
            self.platform.phase = float(self.platform_phase)
        except Exception:
            pass
        self.environment.atmospheric_preset = self.atmospheric_preset
        self.environment.atmospheric_contrast = self.atmospheric_contrast
        self.environment.atmospheric_brightness = self.atmospheric_brightness
        self.sensor.noise = self.noise
        self.sensor.enable_salt_pepper = self.enable_salt_pepper
        self.sensor.enable_gaussian = self.enable_gaussian
        self.sensor.enable_poisson = self.enable_poisson
        self.sensor.salt_pepper_density = self.salt_pepper_density
        self.sensor.salt_pepper_ratio = self.salt_pepper_ratio
        self.sensor.gaussian_sigma = self.gaussian_sigma
        self.sensor.gaussian_sigma_max = self.gaussian_sigma_max
        self.sensor.poisson_scale = self.poisson_scale
        self.sensor.poisson_peak = self.poisson_peak
        self.sensor.max_noise_std = self.max_noise_std
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DisturbanceConfig":
        data = dict(data)
        # Nested optical.channel may arrive as a plain dict — coerce it.
        _opt = dict(data.pop("optical", {}))
        _ch = _opt.pop("channel", {})
        if isinstance(_ch, dict):
            _ch_known = {k: v for k, v in _ch.items() if k in PropagationChannelConfig.__dataclass_fields__}
            _opt["channel"] = PropagationChannelConfig(**_ch_known)
        _plat = data.pop("platform", {})
        if isinstance(_plat, dict):
            _plat_known = {k: v for k, v in _plat.items() if k in PlatformMotionConfig.__dataclass_fields__}
        else:
            _plat_known = {}
        # Filter nested dicts to known dataclass fields (forward-compat).
        def _filter(dc_cls, d):
            if not isinstance(d, dict):
                return {}
            return {k: v for k, v in d.items() if k in dc_cls.__dataclass_fields__}
        nested = {
            "global_": GlobalDisturbanceConfig(**_filter(GlobalDisturbanceConfig, data.pop("global_", {}))),
            "environment": EnvironmentDisturbanceConfig(**_filter(EnvironmentDisturbanceConfig, data.pop("environment", {}))),
            "camera": CameraDisturbanceConfig(**_filter(CameraDisturbanceConfig, data.pop("camera", {}))),
            "optical": OpticalDisturbanceConfig(**{k: v for k, v in _opt.items() if k in OpticalDisturbanceConfig.__dataclass_fields__}),
            "sensor": SensorDisturbanceConfig(**_filter(SensorDisturbanceConfig, data.pop("sensor", {}))),
            "platform": PlatformMotionConfig(**_plat_known),
        }
        allowed = set(DISTURBANCE_DEFAULTS.keys()) | set(DISTURBANCE_LIMITS.keys()) | {"atmospheric_preset", "platform_profile", "enable_salt_pepper", "enable_gaussian", "enable_poisson"}
        unknown = [k for k in data.keys() if k not in allowed]
        if unknown:
            import logging
            logging.getLogger("disturbance").warning(f"Ignoring unknown disturbance keys: {unknown}")
        known = {k: v for k, v in data.items() if k in allowed}
        merged = {**DISTURBANCE_DEFAULTS, **known, **nested}
        # ensure all dataclass fields covered
        allowed = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in merged.items() if k in allowed}
        return cls(**filtered).validate()  # type: ignore

    def image_noise_enabled(self) -> bool:
        return bool(self.enable_salt_pepper or self.enable_gaussian or self.enable_poisson)

    # ---------- Propagation Channel helpers (DisturbanceModel.txt §14/§15) ----------
    def propagation_channel_config(self):
        """Build the live channel object from this config (beam-state medium)."""
        from disturbance.optical.channel import AttenuationConfig, PropagationChannel
        return PropagationChannel(
            atmospheric_condition=str(self.atmospheric_preset),
            severity=float(self.channel_severity),
            attenuation=AttenuationConfig(
                enabled=bool(self.channel_attenuation_enabled),
                strength=float(self.channel_attenuation_strength),
                model=str(self.channel_attenuation_model),
            ),
            turbulence=float(self.turbulence),
            beam_wander=float(self.channel_beam_wander),
            beam_spread=float(self.channel_beam_spread),
            intensity_fluctuation=float(self.channel_intensity_fluctuation),
            enabled=bool(self.channel_enabled and self.global_enabled),
        )

    def apply_preset(self, preset: str) -> "DisturbanceConfig":
        """GUI/Pipeline presets: Clear/Haze/Fog/Rain/Low Light/Moderate/Severe/Custom."""
        p = str(preset).strip().lower().replace("-", " ").replace("_", " ")
        if p == "clear":
            self.atmospheric_preset = "Clear"
            self.channel_severity = 0.0
            self.channel_beam_wander = 0.0
            self.channel_beam_spread = 0.0
            self.channel_intensity_fluctuation = 0.0
            self.turbulence = 0
            # Clear must actually clear sensor/camera stages (was leaking prior noise)
            self.enable_gaussian = False
            self.enable_salt_pepper = False
            self.enable_poisson = False
            self.camera_jitter = 0.0
            self.platform_speed = 0.0
        elif p == "haze":
            self.atmospheric_preset = "Haze"
            self.channel_severity = 0.6
            self.channel_beam_wander = 0.8
            self.channel_beam_spread = 0.8
            self.channel_intensity_fluctuation = 0.8
            self.turbulence = 2
        elif p == "fog":
            self.atmospheric_preset = "Fog"
            self.channel_severity = 1.0
            self.channel_beam_wander = 1.0
            self.channel_beam_spread = 1.0
            self.channel_intensity_fluctuation = 1.0
            self.turbulence = 4
        elif p == "rain":
            self.atmospheric_preset = "Rain"
            self.channel_severity = 0.8
            self.channel_beam_wander = 1.0
            self.channel_beam_spread = 1.0
            self.channel_intensity_fluctuation = 1.0
            self.turbulence = 3
        elif p in ("low light", "lowlight", "low"):
            self.atmospheric_preset = "Low light"
            self.channel_severity = 0.9
            self.turbulence = 1
        elif p == "moderate":
            self.atmospheric_preset = "Haze"
            self.channel_severity = 0.7
            self.enable_gaussian = True
            self.gaussian_sigma = 6.0
            self.camera_jitter = 5.0
            self.platform_speed = 5.0
            self.turbulence = 3
        elif p == "severe":
            self.atmospheric_preset = "Fog"
            self.channel_severity = 1.0
            self.enable_gaussian = True
            self.enable_salt_pepper = True
            self.gaussian_sigma = 12.0
            self.salt_pepper_density = 0.10
            self.camera_jitter = 12.0
            self.platform_speed = 12.0
            self.turbulence = 6
        elif p == "custom":
            self.atmospheric_preset = "User Defined"
        return self.validate()

    def channel_telemetry_baseline(self) -> dict:
        try:
            return self.propagation_channel_config().telemetry()
        except Exception:
            return {}

    # ---------- AI Training Helpers (robust-simple) ----------
    def randomize_for_training(self, rng=None, difficulty: str = "mixed") -> "DisturbanceConfig":
        """
        Domain randomization for AI data generation — challenging but valid combos.

        difficulty: "easy" | "medium" | "hard" | "mixed"
        """
        import random as _rnd
        import numpy as _np
        if rng is None:
            rng = _np.random.default_rng(_rnd.randint(0, 999999))
        diff = str(difficulty).lower()
        if diff == "easy":
            self.enable_salt_pepper = bool(rng.random() < 0.15)
            self.enable_gaussian = bool(rng.random() < 0.25)
            self.enable_poisson = False
            if self.enable_salt_pepper:
                self.salt_pepper_density = float(rng.uniform(0.01, 0.04))
            if self.enable_gaussian:
                self.gaussian_sigma = float(rng.uniform(2, 6))
            self.camera_jitter = float(rng.uniform(0, 3))
            self.atmospheric_preset = str(rng.choice(["Clear", "Clear", "Haze"]))
            if self.atmospheric_preset != "Clear":
                self.atmospheric_preset = "Haze"
            self.platform_speed = float(rng.uniform(0, 4))
            self.turbulence = int(rng.integers(0, 2))
        elif diff == "medium":
            # 40% chance each noise type, mixed presets
            self.enable_salt_pepper = bool(rng.random() < 0.35)
            self.enable_gaussian = bool(rng.random() < 0.45)
            self.enable_poisson = bool(rng.random() < 0.30)
            if self.enable_salt_pepper:
                self.salt_pepper_density = float(rng.uniform(0.03, 0.10))
            if self.enable_gaussian:
                self.gaussian_sigma = float(rng.uniform(5, 12))
            if self.enable_poisson:
                self.poisson_scale = float(rng.uniform(0.8, 1.6))
            self.camera_jitter = float(rng.uniform(2, 10))
            self.atmospheric_preset = str(rng.choice(["Clear", "Haze", "Fog"], p=[0.30, 0.40, 0.30]))
            self.platform_speed = float(rng.uniform(3, 12))
            self.platform_profile = str(rng.choice(["Linear", "Circular", "Random", "Sin"]))
            self.turbulence = int(rng.integers(1, 5))
        elif diff == "hard":
            # All noises on, worst case — beacon barely visible
            self.enable_salt_pepper = True
            self.enable_gaussian = True
            self.enable_poisson = bool(rng.random() < 0.7)
            self.salt_pepper_density = float(rng.uniform(0.08, 0.16))
            self.salt_pepper_ratio = float(rng.uniform(0.45, 0.55))
            self.gaussian_sigma = float(rng.uniform(10, 18))
            self.gaussian_sigma_max = 20.0
            self.poisson_scale = float(rng.uniform(1.0, 2.2))
            self.poisson_peak = float(rng.uniform(60, 120))
            self.camera_jitter = float(rng.uniform(10, 18))
            self.atmospheric_preset = "Fog"
            self.atmospheric_contrast = float(rng.uniform(35, 55))
            self.atmospheric_brightness = float(rng.uniform(18, 32))
            self.platform_speed = float(rng.uniform(12, 20))
            self.platform_profile = str(rng.choice(["Random", "Spiral", "Figure 8", "Zig-Zag"]))
            self.turbulence = int(rng.integers(4, 9))
            self.vibration = int(rng.integers(3, 8))
        else:  # mixed
            pick = rng.choice(["easy", "medium", "hard"], p=[0.30, 0.40, 0.30])
            return self.randomize_for_training(rng, str(pick))
        # Common
        if rng.random() < 0.12 and diff != "easy":
            # Occasional hot-pixel heavy case
            self.salt_pepper_density = max(self.salt_pepper_density, 0.12)
        return self.validate()

    @classmethod
    def generate_training_batch(cls, n: int = 100, difficulty: str = "mixed", seed: int | None = 42) -> list["DisturbanceConfig"]:
        import numpy as _np
        rng = _np.random.default_rng(seed)
        return [cls().randomize_for_training(rng, difficulty) for _ in range(n)]
