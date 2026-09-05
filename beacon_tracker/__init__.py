"""
Package: beacon_tracker
Purpose: Unified package consolidating detection, searching, acquired, locked, and lost modules.

Sub-packages:
  beacon_tracker/detection/   - Stateless per-frame CV blob finding
  beacon_tracker/search/      - Active scan geometries (spiral / raster / random)
  beacon_tracker/phases/      - Phase-isolated state handlers (acquired, locked, lost)

Public re-exports (backward compat with old top-level packages):
  from beacon_tracker.detection.detector    import BeaconDetector, DetectorConfig
  from beacon_tracker.search.handler        import SearchingHandler
  from beacon_tracker.search.scanner        import SearchingStrategy, ScanPattern
  from beacon_tracker.phases.acquired       import AcquiredHandler, AcquiredConfig
  from beacon_tracker.phases.locked         import LockedHandler, LockedConfig
  from beacon_tracker.phases.lost           import LostHandler, LostConfig
"""

from beacon_tracker.detection.config import DetectorConfig  # noqa: F401
from beacon_tracker.detection.constants import DETECTOR_DEFAULTS, DETECTOR_LIMITS, MORPH_KERNEL  # noqa: F401
from beacon_tracker.detection.detector import BeaconDetector  # noqa: F401
from beacon_tracker.detection.preprocessor import close_gaps, threshold_frame, to_grayscale  # noqa: F401
from beacon_tracker.phases.acquired.config import AcquiredConfig  # noqa: F401
from beacon_tracker.phases.acquired.constants import ACQUIRED_DEFAULTS, ACQUIRED_LIMITS  # noqa: F401
from beacon_tracker.phases.acquired.handler import AcquiredHandler  # noqa: F401
from beacon_tracker.phases.locked.config import LockedConfig  # noqa: F401
from beacon_tracker.phases.locked.constants import LOCKED_DEFAULTS, LOCKED_LIMITS  # noqa: F401
from beacon_tracker.phases.locked.handler import LockedHandler  # noqa: F401
from beacon_tracker.phases.lost.config import LostConfig  # noqa: F401
from beacon_tracker.phases.lost.constants import LOST_DEFAULTS, LOST_LIMITS  # noqa: F401
from beacon_tracker.phases.lost.handler import LostHandler  # noqa: F401
from beacon_tracker.search.config import SearchingConfig  # noqa: F401
from beacon_tracker.search.constants import SCAN_PATTERNS, SEARCHING_DEFAULTS, SEARCHING_LIMITS  # noqa: F401
from beacon_tracker.search.handler import SearchingHandler  # noqa: F401
from beacon_tracker.search.scanner import ScanPattern, SearchingStrategy  # noqa: F401

__all__ = [
    # Detection
    "BeaconDetector", "DetectorConfig",
    "DETECTOR_DEFAULTS", "DETECTOR_LIMITS", "MORPH_KERNEL",
    "to_grayscale", "threshold_frame", "close_gaps",
    # Search
    "SearchingHandler", "SearchingConfig", "SearchingStrategy", "ScanPattern",
    "SEARCHING_DEFAULTS", "SEARCHING_LIMITS", "SCAN_PATTERNS",
    # Phases
    "AcquiredHandler", "AcquiredConfig", "ACQUIRED_DEFAULTS", "ACQUIRED_LIMITS",
    "LockedHandler", "LockedConfig", "LOCKED_DEFAULTS", "LOCKED_LIMITS",
    "LostHandler", "LostConfig", "LOST_DEFAULTS", "LOST_LIMITS",
]
