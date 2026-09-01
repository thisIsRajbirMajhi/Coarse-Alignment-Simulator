"""
Package: tracking
Purpose: Orchestrator for lock-state tracking — delegates to isolated phase handlers.
Public API: Tracker, LockStatus, LockStateMachine, ExponentialFilter, TrackerConfig
Architecture (refactored):
  - tracking/tracker.py : Tracker (orchestrates filter + state)
  - tracking/state.py   : LockStateMachine (dispatches to searching/acquired/locked/lost)
  - tracking/filter.py  : ExponentialFilter (also aliased as locked.filter.LockedFilter)
  - searching/          : SearchingHandler (SEARCHING phase)
  - acquired/           : AcquiredHandler (ACQUIRED probation)
  - locked/             : LockedHandler (LOCKED = TRACKING stable)
  - lost/               : LostHandler (LOST hold & grace)
  - detection/          : BeaconDetector (stateless per-frame input)
Notes: This package remains the entry point for `from tracking.tracker import Tracker, LockStatus`
       for backward compat. New code may also `from locked.handler import LockedHandler`, etc.
"""

from tracking.config import TrackerConfig  # noqa: F401
from tracking.constants import TRACKER_DEFAULTS, TRACKER_LIMITS  # noqa: F401
from tracking.filter import ExponentialFilter  # noqa: F401
from tracking.state import LockStateMachine, LockStatus, StateTransition  # noqa: F401
from tracking.tracker import Tracker  # noqa: F401

__all__ = ["Tracker", "LockStatus", "LockStateMachine", "ExponentialFilter", "TrackerConfig", "StateTransition"]
