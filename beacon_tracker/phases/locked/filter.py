# beacon_tracker/phases/locked/filter.py
# Re-export ExponentialFilter as LockedFilter — alias, single implementation

from __future__ import annotations

# Re-export from canonical tracking.filter — single implementation, multiple names
from tracking.filter import ExponentialFilter as LockedFilter  # noqa: F401

__all__ = ["LockedFilter"]
