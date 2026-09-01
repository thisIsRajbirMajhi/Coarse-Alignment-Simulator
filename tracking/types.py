# tracking/types.py - Single source for LockStatus enum — eliminates circular + fallback duplication

from __future__ import annotations

from enum import Enum

class LockStatus(Enum):
    SEARCHING = "searching"
    ACQUIRED = "acquired"
    TRACKING = "tracking"
    # Alias — LOCKED is the user-facing name for TRACKING (stable lock)
    LOCKED = "tracking"
    LOST = "lost"