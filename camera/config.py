# camera/config.py - Typed, validated configuration for Camera/Viewport/Screens (all 11 params)

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from camera.constants import CAMERA_DEFAULTS, CAMERA_LIMITS, DISPLAY_DEFAULTS, DISPLAY_LIMITS
from common.config_base import BaseValidatedConfig, clip_field
from environment.constants import MAX_RES, MIN_RES

@dataclass
class CameraConfig(BaseValidatedConfig):
    """
    Camera configuration — covers FOV, mechanics, display, and optics.
    Monochrome Focal Plane Array.

    Sensor Resolution:
      fov_width, fov_height — sensor resolution (px), default 640x640
    FOV in degrees:
      fov_deg_x, fov_deg_y — angular FOV deg, default 4.0x3.0
    Pan-Tilt Mechanics (30Hz):
      pan_min, pan_max — pan range (px scene coords, None=auto)
      tilt_min, tilt_max — tilt range
      home_pan/home_tilt — fixed centre (W/2, H/2), not configurable
      max_slew_rate — px/s (configurable)
      resolution — smallest step px
      latency_ms — delay ms (configurable)
      update_rate_hz — fixed 30Hz
    Display:
      viewport_width/height — Camera Screen Size 2000-5000 (on-screen)
      god_width/height — God View = World size 2000..5000
    Units:
      pixel_scale_mrad — derived from FOV deg / resolution
    """

    LIMITS = {**CAMERA_LIMITS, **DISPLAY_LIMITS}
    DEFAULTS = {**CAMERA_DEFAULTS, **DISPLAY_DEFAULTS}

    # Sensor Resolution
    fov_width: int = CAMERA_DEFAULTS["fov_width"]
    fov_height: int = CAMERA_DEFAULTS["fov_height"]
    fov_deg_x: float = CAMERA_DEFAULTS.get("fov_deg_x", 4.0)
    fov_deg_y: float = CAMERA_DEFAULTS.get("fov_deg_y", 3.0)

    pan_min: int | None = CAMERA_DEFAULTS["pan_min"]
    pan_max: int | None = CAMERA_DEFAULTS["pan_max"]
    tilt_min: int | None = CAMERA_DEFAULTS["tilt_min"]
    tilt_max: int | None = CAMERA_DEFAULTS["tilt_max"]
    home_pan: float | None = CAMERA_DEFAULTS["home_pan"]
    home_tilt: float | None = CAMERA_DEFAULTS["home_tilt"]
    max_pan_speed_deg: float = CAMERA_DEFAULTS["max_pan_speed_deg"]
    max_tilt_speed_deg: float = CAMERA_DEFAULTS["max_tilt_speed_deg"]
    max_slew_rate: float = CAMERA_DEFAULTS["max_slew_rate"]
    resolution: float = CAMERA_DEFAULTS["resolution"]
    latency_ms: int = CAMERA_DEFAULTS["latency_ms"]
    update_rate_hz: int = CAMERA_DEFAULTS.get("update_rate_hz", 30)

    # Display
    viewport_width: int = DISPLAY_DEFAULTS["viewport_width"]
    viewport_height: int = DISPLAY_DEFAULTS["viewport_height"]
    god_width: int = DISPLAY_DEFAULTS["god_width"]
    god_height: int = DISPLAY_DEFAULTS["god_height"]

    # Units — derived
    pixel_scale_mrad: float = CAMERA_DEFAULTS["pixel_scale_mrad"]

    # Validation — clamp to limits, resolve autos

    def validate(self, scene_bounds: tuple[int,int] | None = None) -> "CameraConfig":
        self.fov_width = int(clip_field(self.fov_width, *CAMERA_LIMITS["fov_width"]))
        self.fov_height = int(clip_field(self.fov_height, *CAMERA_LIMITS["fov_height"]))
        # FOV degrees in degree units
        if "fov_deg_x" in CAMERA_LIMITS:
            self.fov_deg_x = float(clip_field(self.fov_deg_x, *CAMERA_LIMITS["fov_deg_x"]))
            self.fov_deg_y = float(clip_field(self.fov_deg_y, *CAMERA_LIMITS["fov_deg_y"]))
        self.max_pan_speed_deg = float(clip_field(self.max_pan_speed_deg, *CAMERA_LIMITS["max_pan_speed_deg"]))
        self.max_tilt_speed_deg = float(clip_field(self.max_tilt_speed_deg, *CAMERA_LIMITS["max_tilt_speed_deg"]))
        self.max_slew_rate = float(clip_field(self.max_slew_rate, *CAMERA_LIMITS["max_slew_rate"]))
        self.resolution = float(clip_field(self.resolution, *CAMERA_LIMITS["resolution"]))
        self.latency_ms = int(clip_field(self.latency_ms, *CAMERA_LIMITS["latency_ms"]))
        self.update_rate_hz = int(clip_field(self.update_rate_hz, *CAMERA_LIMITS["update_rate_hz"]))
        if self.update_rate_hz < 20:
            self.update_rate_hz = 20
        # Derived pixel scale from FOV deg / resolution (mrad per px)
        try:
            deg_to_mrad = 17.453292519943295
            scale_x = float((self.fov_deg_x * deg_to_mrad) / max(1, self.fov_width))
            scale_y = float((self.fov_deg_y * deg_to_mrad) / max(1, self.fov_height))
            # use horizontal for primary, but warn if aspect mismatch >10% (M5)
            if abs(scale_x - scale_y) / max(1e-6, scale_x) > 0.10:
                import logging
                logging.getLogger("camera").debug(f"FOV aspect mismatch scale_x {scale_x:.4f} vs scale_y {scale_y:.4f}, using avg")
                self.pixel_scale_mrad = float((scale_x + scale_y) / 2.0)
            else:
                self.pixel_scale_mrad = float(scale_x)
            self.pixel_scale_mrad = float(clip_field(self.pixel_scale_mrad, *CAMERA_LIMITS["pixel_scale_mrad"]))
            # store y for vertical error conversion if needed
            self.pixel_scale_mrad_y = float(clip_field(scale_y, *CAMERA_LIMITS["pixel_scale_mrad"]))
        except Exception:
            self.pixel_scale_mrad = float(clip_field(getattr(self, "pixel_scale_mrad", 0.109), *CAMERA_LIMITS["pixel_scale_mrad"]))
        self.viewport_width = int(clip_field(self.viewport_width, *DISPLAY_LIMITS["viewport_width"]))
        self.viewport_height = int(clip_field(self.viewport_height, *DISPLAY_LIMITS["viewport_height"]))
        self.god_width = int(clip_field(self.god_width, *DISPLAY_LIMITS["god_width"]))
        self.god_height = int(clip_field(self.god_height, *DISPLAY_LIMITS["god_height"]))

        if scene_bounds is not None:
            sw, sh = scene_bounds
            # clamp FOV to scene (leave 10px margin) with warning if needed
            if self.fov_width > sw - 10 or self.fov_height > sh - 10:
                import logging
                logging.getLogger("camera").warning(f"FOV {self.fov_width}x{self.fov_height} exceeds scene {sw}x{sh}, clamping to {min(self.fov_width, sw-10)}x{min(self.fov_height, sh-10)}")
                self.fov_width = int(min(self.fov_width, sw - 10))
                self.fov_height = int(min(self.fov_height, sh - 10))
                if self.fov_width < 20: self.fov_width = 20
                if self.fov_height < 20: self.fov_height = 20
            hw, hh = self.fov_width/2, self.fov_height/2
            if self.pan_min is None:
                self.pan_min = int(hw)
            else:
                self.pan_min = int(clip_field(self.pan_min, *CAMERA_LIMITS["pan_min"]))
            if self.pan_max is None:
                self.pan_max = int(sw - hw)
            else:
                self.pan_max = int(clip_field(self.pan_max, *CAMERA_LIMITS["pan_max"]))
            if self.pan_min is not None and self.pan_max is not None and self.pan_min > self.pan_max:
                self.pan_min, self.pan_max = int(self.pan_max), int(self.pan_min)
            if self.tilt_min is None:
                self.tilt_min = int(hh)
            else:
                self.tilt_min = int(clip_field(self.tilt_min, *CAMERA_LIMITS["tilt_min"]))
            if self.tilt_max is None:
                self.tilt_max = int(sh - hh)
            else:
                self.tilt_max = int(clip_field(self.tilt_max, *CAMERA_LIMITS["tilt_max"]))
            if self.tilt_min is not None and self.tilt_max is not None and self.tilt_min > self.tilt_max:
                self.tilt_min, self.tilt_max = int(self.tilt_max), int(self.tilt_min)
            # Initial position fixed to centre — not configurable (overwrites any user home)
            user_home_pan = self.home_pan
            user_home_tilt = self.home_tilt
            self.home_pan = float(sw/2)
            self.home_tilt = float(sh/2)
            # warn if custom home was provided (ignored per spec)
            if user_home_pan is not None or user_home_tilt is not None:
                import logging
                logging.getLogger("camera").debug(f"home_pan/tilt ignored per spec, using centre {sw/2},{sh/2}")
            self.home_pan = float(clip_field(self.home_pan, float(self.pan_min), float(self.pan_max)))
            self.home_tilt = float(clip_field(self.home_tilt, float(self.tilt_min), float(self.tilt_max)))
            # god viewport should not exceed world (overview)
            if self.god_width > sw: self.god_width = sw
            if self.god_height > sh: self.god_height = sh

        return self

    # Helpers — conversions and dict

    def effective_pan_range(self, scene_bounds: tuple[int,int]) -> tuple[float,float]:
        self.validate(scene_bounds)
        return (float(self.pan_min), float(self.pan_max))  # type: ignore

    def effective_tilt_range(self, scene_bounds: tuple[int,int]) -> tuple[float,float]:
        self.validate(scene_bounds)
        return (float(self.tilt_min), float(self.tilt_max))  # type: ignore

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CameraConfig":
        # Filter to dataclass fields only (exclude helper defaults like scene_width)
        allowed = set(cls.__dataclass_fields__.keys())
        known = {k: v for k, v in data.items() if k in allowed}
        # Build with defaults for missing fields
        merged = {}
        for k in allowed:
            if k in known:
                merged[k] = known[k]
            elif k in CAMERA_DEFAULTS:
                merged[k] = CAMERA_DEFAULTS[k]
            elif k in DISPLAY_DEFAULTS:
                merged[k] = DISPLAY_DEFAULTS[k]
        return cls(**merged).validate()

    def pixel_to_mrad(self, px: float) -> float:
        return float(px) * float(self.pixel_scale_mrad)

    def pixel_to_urad(self, px: float) -> float:
        return self.pixel_to_mrad(px) * 1000.0