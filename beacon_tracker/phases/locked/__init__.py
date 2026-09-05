"""
Package: beacon_tracker.phases.locked
Purpose: LOCKED (=TRACKING) phase handler and config.
Public API: LockedHandler, LockedConfig, LockedFilter
"""

from beacon_tracker.phases.locked.config import LockedConfig  # noqa: F401
from beacon_tracker.phases.locked.constants import LOCKED_DEFAULTS, LOCKED_LIMITS  # noqa: F401
from beacon_tracker.phases.locked.handler import LockedHandler  # noqa: F401

# Filter is shared with tracking — re-export for isolated locked usage
try:
    from beacon_tracker.phases.locked.filter import LockedFilter  # noqa: F401
except Exception:
    from tracking.filter import ExponentialFilter as LockedFilter  # noqa: F401

__all__ = ["LockedHandler", "LockedConfig", "LOCKED_DEFAULTS", "LOCKED_LIMITS", "LockedFilter"]
