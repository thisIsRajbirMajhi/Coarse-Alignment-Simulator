"""
Package: common
Purpose: Shared foundations — BaseConfig, limits helpers, color scheme, dt provider.
"""

from common.config_base import BaseValidatedConfig, clip_field  # noqa: F401
from common.colors import (  # noqa: F401
    LOCK_STATUS_COLORS_BGR,
    LOCK_STATUS_COLORS_HEX,
    lock_color_bgr,
    lock_color_hex,
)
from common.rng import get_rng, resolve_rng, seed_global, substream  # noqa: F401

__all__ = [
    "BaseValidatedConfig",
    "clip_field",
    "LOCK_STATUS_COLORS_HEX",
    "LOCK_STATUS_COLORS_BGR",
    "lock_color_hex",
    "lock_color_bgr",
    "get_rng",
    "resolve_rng",
    "seed_global",
    "substream",
]