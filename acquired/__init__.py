"""
Package: acquired
Purpose: Isolated ACQUIRED algorithm — probation after first hit, before lock.
Public API: AcquiredHandler, AcquiredConfig
Notes: ACQUIRED is provisional: needs acquire_hits consecutive hits to promote to LOCKED/TRACKING,
       or miss_limit consecutive misses to demote to LOST. No estimate discard yet.
"""

from acquired.config import AcquiredConfig  # noqa: F401
from acquired.constants import ACQUIRED_DEFAULTS, ACQUIRED_LIMITS  # noqa: F401
from acquired.handler import AcquiredHandler  # noqa: F401

__all__ = ["AcquiredHandler", "AcquiredConfig", "ACQUIRED_DEFAULTS", "ACQUIRED_LIMITS"]