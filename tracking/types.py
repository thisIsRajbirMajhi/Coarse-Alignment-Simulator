"""
Module: tracking.types
Purpose: Single source for LockStatus enum — eliminates circular + fallback duplication.
Public API: LockStatus
Notes: Moved from tracking.state to tracking.types so handlers (searching/acquired/locked/lost)
       can import without pulling LockStateMachine. State machine and tracker import from here.
       No handler imports here — pure enum, no cycles.
"""

from __future__ import annotations

from enum import Enum


class LockStatus(Enum):
    SEARCHING = "searching"
    ACQUIRED = "acquired"
    TRACKING = "tracking"
    # Alias — LOCKED is the user-facing name for TRACKING (stable lock)
    LOCKED = "tracking"
    LOST = "lost"
