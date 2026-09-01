"""
Module: locked.filter
Purpose: Isolated smoothing filter for LOCKED phase — first-order IIR.
Public API: LockedFilter (alias for tracking filter, scoped to locked)
Notes: Re-exports ExponentialFilter with LOCKED-scoped naming.
       Keeping filter in locked isolates LOCKED's algorithmic core (tracking)
       while tracking package orchestrates. Single source remains tracking.filter
       for backward compat; this module provides the locked-scoped alias/view.
"""

from __future__ import annotations

# Re-export from canonical tracking.filter — single implementation, multiple names
from tracking.filter import ExponentialFilter as LockedFilter  # noqa: F401

__all__ = ["LockedFilter"]
