"""
Package: locked
Purpose: Isolated LOCKED (=TRACKING) algorithm — stable lock, retention metric, smoothing.
Public API: LockedHandler, LockedConfig, LockedFilter (alias for tracking filter)
Notes: LOCKED is the committed state: ≥acquire_hits consecutive hits have confirmed
       the target. Estimate is reported, retention counts, and misses are tolerated
       up to miss_limit before demoting to LOST.
       Alias: TRACKING == LOCKED (spec uses tracking, user request uses locked).
"""

from locked.config import LockedConfig  # noqa: F401
from locked.constants import LOCKED_DEFAULTS, LOCKED_LIMITS  # noqa: F401
from locked.handler import LockedHandler  # noqa: F401

# Filter is shared with tracking — re-export for isolated locked usage
try:
    from locked.filter import LockedFilter  # noqa: F401
except Exception:
    from tracking.filter import ExponentialFilter as LockedFilter  # noqa: F401

__all__ = ["LockedHandler", "LockedConfig", "LOCKED_DEFAULTS", "LOCKED_LIMITS", "LockedFilter"]
