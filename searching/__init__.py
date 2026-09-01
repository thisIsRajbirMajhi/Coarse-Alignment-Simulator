"""
Package: searching
Purpose: Isolated SEARCHING algorithm — no lock, no estimate, active scan for first hit.
Public API: SearchingHandler, SearchingConfig, SearchingStrategy
Notes: Stateless per-frame scan; transitions SEARCHING → ACQUIRED on any hit.
       Separate from detection (which is raw blob finding) and tracking (which holds estimate).
"""

from searching.config import SearchingConfig  # noqa: F401
from searching.constants import SEARCHING_DEFAULTS, SEARCHING_LIMITS  # noqa: F401
from searching.handler import SearchingHandler  # noqa: F401
from searching.scanner import ScanPattern, SearchingStrategy  # noqa: F401

__all__ = ["SearchingHandler", "SearchingConfig", "SEARCHING_DEFAULTS", "SEARCHING_LIMITS", "SearchingStrategy", "ScanPattern"]
