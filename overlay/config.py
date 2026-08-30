"""
Module: overlay.config
Purpose: Typed, validated configuration for crosshair / tracking overlay (robust, modular).
Public API: OverlayConfig, CrosshairStyleType, LockColors, ErrorUnits
Groups:
  - Crosshair: style, size, gap, thickness, centre_dot
  - Lock: colors per state, circle radius, pulse
  - Error: show line/text, units (px/mrad/urad)
Notes: Single source for renderer and panel. HOT-reloaded, validated, serializable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

import numpy as np

from overlay.constants import CROSSHAIR_STYLES, ERROR_UNITS_OPTIONS, LOCK_COLOR_DEFAULTS, OVERLAY_DEFAULTS, OVERLAY_LIMITS

# ============================================================
# SECTION: Enums — style & units
# ============================================================

class CrosshairStyleType(str, Enum):
    CROSS = "cross"
    BRACKET = "bracket"
    CIRCLE = "circle"
    CROSS_BRACKET = "cross+bracket"
    CROSS_CIRCLE = "cross+circle"
    ALL = "all"

class ErrorUnits(str, Enum):
    PX = "px"
    MRAD = "mrad"
    URAD = "urad"
    PX_MRAD = "px+mrad"

# Keep BGR tuples for lock colors
@dataclass
class LockColors:
    searching: tuple[int,int,int] = LOCK_COLOR_DEFAULTS["searching"]
    acquired: tuple[int,int,int] = LOCK_COLOR_DEFAULTS["acquired"]
    tracking: tuple[int,int,int] = LOCK_COLOR_DEFAULTS["tracking"]
    lost: tuple[int,int,int] = LOCK_COLOR_DEFAULTS["lost"]
    detecting: tuple[int,int,int] = LOCK_COLOR_DEFAULTS["detecting"]

    def for_status(self, status: str) -> tuple[int,int,int]:
        return getattr(self, status.lower(), self.searching)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LockColors":
        kwargs = {}
        for k in ["searching","acquired","tracking","lost","detecting"]:
            if k in data:
                v = data[k]
                # Accept list/tuple
                kwargs[k] = tuple(int(x) for x in v) if isinstance(v, (list, tuple)) else LOCK_COLOR_DEFAULTS[k]
        return cls(**kwargs)

# ============================================================
# SECTION: OverlayConfig — full overlay (3 groups)
# ============================================================

@dataclass
class OverlayConfig:
    """
    Crosshair / tracking overlay configuration.

    Crosshair:
      style, size, gap, thickness, centre_dot, centre_dot_radius, crosshair_color
    Lock:
      lock_colors, lock_circle_radius, lock_circle_thickness, pulse_enabled, pulse_duration_ms
    Error:
      show_error_line, show_error_text, error_units, error_text_scale
    """

    # --------------------------------------------------------
    # Crosshair
    # --------------------------------------------------------
    crosshair_style: str = OVERLAY_DEFAULTS["crosshair_style"]
    crosshair_size: int = OVERLAY_DEFAULTS["crosshair_size"]
    crosshair_gap: int = OVERLAY_DEFAULTS["crosshair_gap"]
    crosshair_thickness: int = OVERLAY_DEFAULTS["crosshair_thickness"]
    centre_dot: bool = OVERLAY_DEFAULTS["centre_dot"]
    centre_dot_radius: int = OVERLAY_DEFAULTS["centre_dot_radius"]
    crosshair_color: tuple[int,int,int] = OVERLAY_DEFAULTS["crosshair_color"]

    # --------------------------------------------------------
    # Lock status
    # --------------------------------------------------------
    lock_colors: LockColors = field(default_factory=LockColors)
    lock_circle_radius: int = OVERLAY_DEFAULTS["lock_circle_radius"]
    lock_circle_thickness: int = OVERLAY_DEFAULTS["lock_circle_thickness"]
    pulse_enabled: bool = OVERLAY_DEFAULTS["pulse_enabled"]
    pulse_duration_ms: int = OVERLAY_DEFAULTS["pulse_duration_ms"]

    # --------------------------------------------------------
    # Error visualization
    # --------------------------------------------------------
    show_error_line: bool = OVERLAY_DEFAULTS["show_error_line"]
    show_error_text: bool = OVERLAY_DEFAULTS["show_error_text"]
    error_units: str = OVERLAY_DEFAULTS["error_units"]
    error_text_scale: float = OVERLAY_DEFAULTS["error_text_scale"]

    # ========================================================
    # Validation
    # ========================================================

    def validate(self) -> "OverlayConfig":
        if self.crosshair_style not in CROSSHAIR_STYLES:
            self.crosshair_style = OVERLAY_DEFAULTS["crosshair_style"]
        lo, hi = OVERLAY_LIMITS["crosshair_size"]
        self.crosshair_size = int(np.clip(int(self.crosshair_size), lo, hi))
        lo, hi = OVERLAY_LIMITS["crosshair_gap"]
        self.crosshair_gap = int(np.clip(int(self.crosshair_gap), lo, hi))
        lo, hi = OVERLAY_LIMITS["crosshair_thickness"]
        self.crosshair_thickness = int(np.clip(int(self.crosshair_thickness), lo, hi))
        lo, hi = OVERLAY_LIMITS["centre_dot_radius"]
        self.centre_dot_radius = int(np.clip(int(self.centre_dot_radius), lo, hi))
        self.centre_dot = bool(self.centre_dot)
        # Clamp color BGR 0..255
        self.crosshair_color = tuple(int(np.clip(int(c), 0, 255)) for c in self.crosshair_color)

        lo, hi = OVERLAY_LIMITS["lock_circle_radius"]
        self.lock_circle_radius = int(np.clip(int(self.lock_circle_radius), lo, hi))
        lo, hi = OVERLAY_LIMITS["lock_circle_thickness"]
        self.lock_circle_thickness = int(np.clip(int(self.lock_circle_thickness), lo, hi))
        self.pulse_enabled = bool(self.pulse_enabled)
        lo, hi = OVERLAY_LIMITS["pulse_duration_ms"]
        self.pulse_duration_ms = int(np.clip(int(self.pulse_duration_ms), lo, hi))

        self.show_error_line = bool(self.show_error_line)
        self.show_error_text = bool(self.show_error_text)
        if self.error_units not in ERROR_UNITS_OPTIONS:
            self.error_units = OVERLAY_DEFAULTS["error_units"]
        # error_text_scale kept 0.2..0.6
        self.error_text_scale = float(np.clip(float(self.error_text_scale), 0.2, 0.6))
        # lock_colors validate
        if not isinstance(self.lock_colors, LockColors):
            self.lock_colors = LockColors()
        return self

    # ========================================================
    # Helpers — style predicates
    # ========================================================

    def has_cross(self) -> bool:
        return self.crosshair_style in ("cross", "cross+bracket", "cross+circle", "all")

    def has_bracket(self) -> bool:
        return self.crosshair_style in ("bracket", "cross+bracket", "all")

    def has_circle(self) -> bool:
        return self.crosshair_style in ("circle", "cross+circle", "all")

    def color_for(self, status_value: str) -> tuple[int,int,int]:
        return self.lock_colors.for_status(status_value)

    # ========================================================
    # Serialization
    # ========================================================

    def to_dict(self) -> dict:
        d = asdict(self)
        # lock_colors is nested dataclass
        d["lock_colors"] = self.lock_colors.to_dict() if isinstance(self.lock_colors, LockColors) else dict(self.lock_colors)
        # tuple -> list for JSON
        d["crosshair_color"] = list(self.crosshair_color)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "OverlayConfig":
        # Extract lock_colors separately
        lc_data = data.get("lock_colors", None)
        lc = LockColors.from_dict(lc_data) if isinstance(lc_data, dict) else LockColors()
        # Filter known fields
        known = {k: v for k, v in data.items() if k in OVERLAY_DEFAULTS}
        # Handle crosshair_color list
        if "crosshair_color" in data:
            cc = data["crosshair_color"]
            known["crosshair_color"] = tuple(int(x) for x in cc) if isinstance(cc, (list, tuple)) else OVERLAY_DEFAULTS["crosshair_color"]
        # Map style/units
        if "crosshair_style" in data:
            known["crosshair_style"] = str(data["crosshair_style"]).lower()
        if "error_units" in data:
            known["error_units"] = str(data["error_units"]).lower()
        # Build
        cfg = cls(**{**OVERLAY_DEFAULTS, **known, "lock_colors": lc})
        # Override with explicit if present
        for k in ["crosshair_size","crosshair_gap","crosshair_thickness","centre_dot","centre_dot_radius","lock_circle_radius","lock_circle_thickness","pulse_enabled","pulse_duration_ms","show_error_line","show_error_text","error_text_scale"]:
            if k in data:
                setattr(cfg, k, data[k])
        return cfg.validate()

    # Convenience for renderer
    def lock_color(self, status: str) -> tuple[int,int,int]:
        return self.color_for(status)
