"""
Module: camera.config
Purpose: Typed, validated configuration for Camera/Viewport/Screens (all 11 params).
Public API: CameraConfig
Groups:
  - Field of View / Optics: fov_width, fov_height
  - Pan-Tilt Mechanics: pan_min/max, tilt_min/max, home_pan/tilt, max_slew_rate, resolution, latency_ms
  - Display: viewport_width/height, god_width/height
  - Units/Reporting: pixel_scale_mrad (px → mrad)
Notes: Immediate migration — MainWindow stores CameraConfig as single source.
       PTZCamera is constructed from CameraConfig; panel collects it HOT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from camera.constants import CAMERA_DEFAULTS, CAMERA_LIMITS, DISPLAY_DEFAULTS, DISPLAY_LIMITS
from environment.constants import MAX_RES, MIN_RES

# ============================================================
# SECTION: CameraConfig — all 11 camera/viewport params
# ============================================================

@dataclass
class CameraConfig:
    """
    Camera configuration — covers FOV, mechanics, display, and optics.

    Field of View / Optics:
      fov_width, fov_height — sensor resolution (px)

    Pan-Tilt Mechanics:
      pan_min, pan_max — pan range (px scene coords, None=auto)
      tilt_min, tilt_max — tilt range
      home_pan, home_tilt — home/centre on start/reset (None=auto W/2,H/2)
      max_slew_rate — px/s (10..5000, caps per-tick delta)
      resolution — smallest step px (0.01..5.0, quantized)
      latency_ms — delay ms (0..500, queued)

    Display:
      viewport_width/height — on-screen FOV feed size (independent of FOV res)
      god_width/height — on-screen God-view map size

    Units/Reporting:
      pixel_scale_mrad — mrad per px for angular error reporting
    """

    # --------------------------------------------------------
    # Field of View / Optics
    # --------------------------------------------------------
    fov_width: int = CAMERA_DEFAULTS["fov_width"]
    fov_height: int = CAMERA_DEFAULTS["fov_height"]

    # --------------------------------------------------------
    # Pan-Tilt Mechanics
    # --------------------------------------------------------
    pan_min: int | None = CAMERA_DEFAULTS["pan_min"]
    pan_max: int | None = CAMERA_DEFAULTS["pan_max"]
    tilt_min: int | None = CAMERA_DEFAULTS["tilt_min"]
    tilt_max: int | None = CAMERA_DEFAULTS["tilt_max"]
    home_pan: float | None = CAMERA_DEFAULTS["home_pan"]
    home_tilt: float | None = CAMERA_DEFAULTS["home_tilt"]
    max_slew_rate: float = CAMERA_DEFAULTS["max_slew_rate"]
    resolution: float = CAMERA_DEFAULTS["resolution"]
    latency_ms: int = CAMERA_DEFAULTS["latency_ms"]

    # --------------------------------------------------------
    # Display — viewport / God view on-screen sizes
    # --------------------------------------------------------
    viewport_width: int = DISPLAY_DEFAULTS["viewport_width"]
    viewport_height: int = DISPLAY_DEFAULTS["viewport_height"]
    god_width: int = DISPLAY_DEFAULTS["god_width"]
    god_height: int = DISPLAY_DEFAULTS["god_height"]

    # --------------------------------------------------------
    # Units — pixel to angle
    # --------------------------------------------------------
    pixel_scale_mrad: float = CAMERA_DEFAULTS["pixel_scale_mrad"]

    # ========================================================
    # Validation — clamp to limits, resolve autos
    # ========================================================

    def validate(self, scene_bounds: tuple[int,int] | None = None) -> "CameraConfig":
        """Clamp numeric fields to limits; resolve None autos against scene_bounds."""
        # FOV
        lo, hi = CAMERA_LIMITS["fov_width"]
        self.fov_width = int(np.clip(int(self.fov_width), lo, hi))
        lo, hi = CAMERA_LIMITS["fov_height"]
        self.fov_height = int(np.clip(int(self.fov_height), lo, hi))

        # Mechanics — resolution / slew / latency
        lo, hi = CAMERA_LIMITS["max_slew_rate"]
        self.max_slew_rate = float(np.clip(float(self.max_slew_rate), lo, hi))
        lo, hi = CAMERA_LIMITS["resolution"]
        self.resolution = float(np.clip(float(self.resolution), lo, hi))
        lo, hi = CAMERA_LIMITS["latency_ms"]
        self.latency_ms = int(np.clip(int(self.latency_ms), lo, hi))
        lo, hi = CAMERA_LIMITS["pixel_scale_mrad"]
        self.pixel_scale_mrad = float(np.clip(float(self.pixel_scale_mrad), lo, hi))

        # Display
        lo, hi = DISPLAY_LIMITS["viewport_width"]
        self.viewport_width = int(np.clip(int(self.viewport_width), lo, hi))
        lo, hi = DISPLAY_LIMITS["viewport_height"]
        self.viewport_height = int(np.clip(int(self.viewport_height), lo, hi))
        lo, hi = DISPLAY_LIMITS["god_width"]
        self.god_width = int(np.clip(int(self.god_width), lo, hi))
        lo, hi = DISPLAY_LIMITS["god_height"]
        self.god_height = int(np.clip(int(self.god_height), lo, hi))

        # Pan/Tilt ranges and home — resolve autos if scene known
        if scene_bounds is not None:
            sw, sh = scene_bounds
            # Effective FOV half-sizes for auto range
            hw, hh = self.fov_width/2, self.fov_height/2
            # Pan range autos
            if self.pan_min is None:
                self.pan_min = int(hw)
            else:
                lo, hi = CAMERA_LIMITS["pan_min"]
                self.pan_min = int(np.clip(int(self.pan_min), lo, hi))
            if self.pan_max is None:
                self.pan_max = int(sw - hw)
            else:
                lo, hi = CAMERA_LIMITS["pan_max"]
                self.pan_max = int(np.clip(int(self.pan_max), lo, hi))
            if self.pan_min is not None and self.pan_max is not None and self.pan_min > self.pan_max:
                self.pan_min, self.pan_max = int(self.pan_max), int(self.pan_min)
            # Tilt
            if self.tilt_min is None:
                self.tilt_min = int(hh)
            else:
                self.tilt_min = int(np.clip(int(self.tilt_min), *CAMERA_LIMITS["tilt_min"]))
            if self.tilt_max is None:
                self.tilt_max = int(sh - hh)
            else:
                self.tilt_max = int(np.clip(int(self.tilt_max), *CAMERA_LIMITS["tilt_max"]))
            if self.tilt_min is not None and self.tilt_max is not None and self.tilt_min > self.tilt_max:
                self.tilt_min, self.tilt_max = int(self.tilt_max), int(self.tilt_min)
            # Home autos
            if self.home_pan is None:
                self.home_pan = float(sw/2)
            else:
                self.home_pan = float(np.clip(float(self.home_pan), float(self.pan_min), float(self.pan_max)))
            if self.home_tilt is None:
                self.home_tilt = float(sh/2)
            else:
                self.home_tilt = float(np.clip(float(self.home_tilt), float(self.tilt_min), float(self.tilt_max)))
            # Clamp home to range
            self.home_pan = float(np.clip(float(self.home_pan), float(self.pan_min), float(self.pan_max)))
            self.home_tilt = float(np.clip(float(self.home_tilt), float(self.tilt_min), float(self.tilt_max)))

        return self

    # ========================================================
    # Helpers — conversions and dict
    # ========================================================

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
