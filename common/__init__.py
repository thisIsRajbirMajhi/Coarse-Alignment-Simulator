"""
Package: common
Purpose: Shared foundations — BaseConfig, limits helpers, color scheme, dt provider.
"""

from common.config_base import BaseValidatedConfig, clip_field  # noqa: F401

__all__ = ["BaseValidatedConfig", "clip_field"]
