# locked/filter.py - Isolated smoothing filter for LOCKED phase — first-order IIR

from __future__ import annotations

# Re-export from canonical tracking.filter — single implementation, multiple names
from tracking.filter import ExponentialFilter as LockedFilter  # noqa: F401

__all__ = ["LockedFilter"]