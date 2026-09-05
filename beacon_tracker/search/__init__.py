"""
Package: beacon_tracker.search
Purpose: Active scan geometries and SEARCHING phase handler.
Public API: SearchingHandler, SearchingConfig, SearchingStrategy, ScanPattern
"""

from beacon_tracker.search.config import SearchingConfig  # noqa: F401
from beacon_tracker.search.constants import SCAN_PATTERNS, SEARCHING_DEFAULTS, SEARCHING_LIMITS  # noqa: F401
from beacon_tracker.search.handler import SearchingHandler  # noqa: F401
from beacon_tracker.search.scanner import ScanPattern, SearchingStrategy  # noqa: F401

__all__ = [
    "SearchingHandler", "SearchingConfig", "SearchingStrategy", "ScanPattern",
    "SEARCHING_DEFAULTS", "SEARCHING_LIMITS", "SCAN_PATTERNS",
]
